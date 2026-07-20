"""
QMT (迅投 miniQMT) Trading Client

Uses the xtquant Python SDK to connect to a locally running miniQMT client
for A-share (China A-Stock) trading.

Note: Requires Windows platform, miniQMT client installed and logged in,
and the xtquant package available on sys.path (shipped with miniQMT, not on PyPI).
"""

import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from app.utils.logger import get_logger
from app.services.qmt_trading.symbols import normalize_symbol, parse_symbol

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy import xtquant — the package ships with miniQMT, not on PyPI.
# We add the miniQMT site-packages directory to sys.path, then import.
# ---------------------------------------------------------------------------

_xtquant_modules = None  # will hold a namespace with XtQuantTrader, StockAccount, xtconstant


def _ensure_xtquant(qmt_lib_path: str = ""):
    """
    Ensure xtquant is importable.

    Args:
        qmt_lib_path: Path to the site-packages directory containing the
                      ``xtquant`` package.  Typically::

                          <miniQMT_install>/userdata_mini/site-packages

                      or a user-configured Python lib path.

    Returns:
        A namespace object with attributes:
            XtQuantTrader, XtQuantTraderCallback, StockAccount, xtconstant
    """
    global _xtquant_modules

    if _xtquant_modules is not None:
        return _xtquant_modules

    lib_path = (qmt_lib_path or "").strip()
    if lib_path and lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    try:
        from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
        from xtquant.xttype import StockAccount
        from xtquant import xtconstant
    except ImportError as e:
        raise ImportError(
            "xtquant is not available. Ensure miniQMT is installed and the "
            "qmt_lib_path points to the directory containing the xtquant package "
            "(e.g. .../userdata_mini/site-packages). "
            f"Original error: {e}"
        )

    class _NS:
        pass

    ns = _NS()
    ns.XtQuantTrader = XtQuantTrader
    ns.XtQuantTraderCallback = XtQuantTraderCallback
    ns.StockAccount = StockAccount
    ns.xtconstant = xtconstant
    _xtquant_modules = ns
    return ns


# ---------------------------------------------------------------------------
# Callback for async order/asset/position updates from miniQMT
# ---------------------------------------------------------------------------

def _make_callback(logger_ref):
    """Create an XtQuantTraderCallback subclass that logs events."""

    from xtquant.xttrader import XtQuantTraderCallback

    class _QMTCallback(XtQuantTraderCallback):
        def on_disconnected(self):
            logger_ref.warning("QMT: trader disconnected")

        def on_stock_order(self, order):
            logger_ref.debug(
                "QMT order callback: code=%s order_id=%s status=%s",
                getattr(order, "stock_code", ""),
                getattr(order, "order_id", ""),
                getattr(order, "order_status", ""),
            )

        def on_stock_trade(self, trade):
            logger_ref.debug(
                "QMT trade callback: code=%s order_id=%s traded=%s price=%s",
                getattr(trade, "stock_code", ""),
                getattr(trade, "order_id", ""),
                getattr(trade, "traded_volume", ""),
                getattr(trade, "traded_price", ""),
            )

        def on_order_error(self, order_error):
            logger_ref.warning(
                "QMT order error: order_id=%s error_id=%s error_msg=%s",
                getattr(order_error, "order_id", ""),
                getattr(order_error, "error_id", ""),
                getattr(order_error, "error_msg", ""),
            )

        def on_cancel_error(self, cancel_error):
            logger_ref.warning(
                "QMT cancel error: order_id=%s error_id=%s error_msg=%s",
                getattr(cancel_error, "order_id", ""),
                getattr(cancel_error, "error_id", ""),
                getattr(cancel_error, "error_msg", ""),
            )

        def on_account_status(self, status):
            logger_ref.debug(
                "QMT account status: account_id=%s status=%s",
                getattr(status, "account_id", ""),
                getattr(status, "status", ""),
            )

    return _QMTCallback


# ---------------------------------------------------------------------------
# Config & result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class QMTConfig:
    """QMT / miniQMT connection configuration."""
    qmt_path: str = ""             # miniQMT userdata_mini 完整路径
    qmt_account_id: str = ""       # 资金账号 (e.g. "12345678")
    qmt_session_id: int = 123456   # 会话ID (任意正整数, 需唯一)
    qmt_username: str = ""         # miniQMT 登录用户名 (for reference/logging)
    qmt_password: str = ""         # miniQMT 登录密码 (for reference/logging)
    qmt_lib_path: str = ""         # xtquant 所在 site-packages 路径
    strategy_name: str = "QuantDinger"  # 策略名称 (下单时传入)


@dataclass
class OrderResult:
    """Order execution result."""
    success: bool
    order_id: int = 0
    filled: float = 0.0
    price: float = 0.0
    status: str = ""
    message: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# QMT Client
# ---------------------------------------------------------------------------

class QMTClient:
    """
    QMT (miniQMT) Trading Client for A-shares.

    Usage:
        config = QMTConfig(
            qmt_path=r"C:\\miniQMT\\userdata_mini",
            qmt_account_id="12345678",
            qmt_session_id=123456,
            qmt_lib_path=r"C:\\miniQMT\\userdata_mini\\site-packages",
        )
        client = QMTClient(config)

        if client.connect():
            # Place market order (最新价)
            result = client.place_market_order("600000", "buy", 100)

            # Place limit order (限价)
            result = client.place_limit_order("600000", "buy", 100, 10.50)

            # Get positions
            positions = client.get_positions()

            client.disconnect()
    """

    # xtquant order status constants (defined in xtconstant module)
    # These are resolved at connect time from the loaded xtconstant module.
    _ORDER_SUCCEEDED = 56     # 全部成交
    _ORDER_PART_SUCC = 55     # 部分成交
    _ORDER_JUNK = 57          # 废单
    _ORDER_CANCELED = 54      # 已撤

    def __init__(self, config: Optional[QMTConfig] = None):
        self.config = config or QMTConfig()
        self._connected = False
        self._trader = None       # XtQuantTrader instance
        self._account = None      # StockAccount instance
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        """Check if connected to miniQMT."""
        if not self._connected or self._trader is None:
            return False
        try:
            # XtQuantTrader does not have a simple is_connected method;
            # we check if the connection is still alive by querying asset.
            # For property-style checks, we just return the flag — the real
            # liveness check happens in _ensure_connected before each action.
            return self._connected
        except Exception:
            return False

    def connect(self) -> bool:
        """
        Connect to miniQMT via xtquant.

        Returns:
            True if connected and subscribed successfully.
        """
        with self._lock:
            if self._connected:
                return True

            try:
                xt = _ensure_xtquant(self.config.qmt_lib_path)
                XtQuantTrader = xt.XtQuantTrader
                StockAccount = xt.StockAccount

                path = (self.config.qmt_path or "").strip()
                account_id = (self.config.qmt_account_id or "").strip()
                session_id = int(self.config.qmt_session_id or 123456)

                if not path:
                    logger.error("QMT connect failed: qmt_path is empty")
                    return False
                if not account_id:
                    logger.error("QMT connect failed: qmt_account_id is empty")
                    return False

                logger.info(
                    "Connecting to QMT: path=%s, account=%s, session=%d",
                    path, account_id, session_id,
                )

                # Create trader instance
                self._trader = XtQuantTrader(path, session_id)

                # Register callback
                CallbackCls = _make_callback(logger)
                self._trader.register_callback(CallbackCls())

                # Start the trader
                self._trader.start()

                # Connect to the running miniQMT process
                connect_result = self._trader.connect()
                if connect_result != 0:
                    logger.error(
                        "QMT connect failed: return code=%d. "
                        "Ensure miniQMT is running and logged in.",
                        connect_result,
                    )
                    self._trader.stop()
                    self._trader = None
                    return False

                # Subscribe to the securities account
                self._account = StockAccount(account_id)
                sub_result = self._trader.subscribe(self._account)
                if sub_result != 0:
                    logger.error(
                        "QMT subscribe failed: return code=%d, account=%s",
                        sub_result, account_id,
                    )
                    self._trader.stop()
                    self._trader = None
                    self._account = None
                    return False

                self._connected = True
                logger.info("QMT connected: account=%s", account_id)

                # Try to get account info as a sanity check
                try:
                    asset = self._trader.query_stock_asset(self._account)
                    if asset:
                        logger.info(
                            "QMT account verified: total_asset=%.2f, cash=%.2f",
                            asset.total_asset, asset.cash,
                        )
                except Exception:
                    pass

                return True

            except Exception as e:
                logger.error(f"QMT connection failed: {e}")
                self._connected = False
                if self._trader:
                    try:
                        self._trader.stop()
                    except Exception:
                        pass
                    self._trader = None
                return False

    def disconnect(self):
        """Disconnect from miniQMT."""
        with self._lock:
            if self._trader:
                try:
                    self._trader.stop()
                except Exception as e:
                    logger.warning(f"QMT disconnect exception: {e}")
                finally:
                    self._trader = None
                    self._account = None
                    self._connected = False
                    logger.info("QMT disconnected")

    def _ensure_connected(self):
        """Ensure connection is established."""
        if not self.connected:
            if not self.connect():
                raise ConnectionError("Cannot connect to miniQMT. Ensure it is running and logged in.")

    # ==================== Order Methods ====================

    def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        comment: str = "QuantDinger",
    ) -> OrderResult:
        """
        Place a market order at the latest price (最新价).

        Args:
            symbol: A-share code, e.g. "600000" or "600000.SH".
            side: "buy" or "sell".
            volume: Number of shares (must be multiple of 100 for A-shares).
            comment: Order remark.

        Returns:
            OrderResult
        """
        return self._place_order(
            symbol=symbol,
            side=side,
            volume=volume,
            price=0.0,
            price_type="latest",
            comment=comment,
        )

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        price: float,
        comment: str = "QuantDinger",
    ) -> OrderResult:
        """
        Place a limit order at the specified price (限价).

        Args:
            symbol: A-share code, e.g. "600000" or "600000.SH".
            side: "buy" or "sell".
            volume: Number of shares (must be multiple of 100 for A-shares).
            price: Limit price.
            comment: Order remark.

        Returns:
            OrderResult
        """
        return self._place_order(
            symbol=symbol,
            side=side,
            volume=volume,
            price=price,
            price_type="fix",
            comment=comment,
        )

    def _place_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        price: float,
        price_type: str,   # "latest" or "fix"
        comment: str = "QuantDinger",
    ) -> OrderResult:
        """Internal: place an order via xtquant order_stock."""
        try:
            self._ensure_connected()
            xt = _ensure_xtquant(self.config.qmt_lib_path)
            xtconstant = xt.xtconstant

            # Normalize symbol to QMT format (e.g. "600000.SH")
            qmt_symbol = normalize_symbol(symbol)

            # Determine order type (buy/sell)
            side_lower = (side or "").strip().lower()
            if side_lower == "buy":
                order_type = xtconstant.STOCK_BUY
            elif side_lower == "sell":
                order_type = xtconstant.STOCK_SELL
            else:
                return OrderResult(
                    success=False,
                    message=f"Invalid side: '{side}'. Must be 'buy' or 'sell'.",
                )

            # Determine price type
            if price_type == "fix":
                pt = xtconstant.FIX_PRICE
                if price <= 0:
                    return OrderResult(
                        success=False,
                        message="Limit order requires price > 0",
                    )
            else:
                pt = xtconstant.LATEST_PRICE
                price = 0.0  # price is ignored for latest-price orders

            # A-shares: volume must be integer (number of shares)
            order_volume = int(volume)
            if order_volume <= 0:
                return OrderResult(
                    success=False,
                    message=f"Invalid volume: {volume}. Must be a positive integer (shares).",
                )

            # Warn if not a multiple of 100 (1 lot)
            if order_volume % 100 != 0:
                logger.warning(
                    "QMT order volume %d is not a multiple of 100 (1 lot). "
                    "Most A-share brokers require 100-share lots.",
                    order_volume,
                )

            strategy_name = self.config.strategy_name or "QuantDinger"
            remark = comment or "QuantDinger"

            logger.info(
                "QMT placing order: symbol=%s side=%s volume=%d price=%.4f price_type=%s",
                qmt_symbol, side_lower, order_volume, price, price_type,
            )

            # Call order_stock(account, stock_code, order_type, order_volume,
            #                  price_type, price, strategy_name, order_remark)
            order_id = self._trader.order_stock(
                self._account,
                qmt_symbol,
                order_type,
                order_volume,
                pt,
                price,
                strategy_name,
                remark,
            )

            if order_id is None or order_id < 0:
                return OrderResult(
                    success=False,
                    message=f"order_stock returned error code: {order_id}",
                    raw={"order_id": order_id, "symbol": qmt_symbol, "side": side_lower},
                )

            # Query the order to get initial status
            filled = 0.0
            fill_price = 0.0
            status_str = "submitted"
            try:
                order = self._trader.query_stock_order(self._account, order_id)
                if order:
                    filled = float(getattr(order, "traded_volume", 0) or 0)
                    fill_price = float(getattr(order, "traded_price", 0) or 0)
                    status_str = self._order_status_str(getattr(order, "order_status", 0))
            except Exception:
                pass

            return OrderResult(
                success=True,
                order_id=order_id,
                filled=filled,
                price=fill_price,
                status=status_str,
                message="Order submitted to miniQMT",
                raw={
                    "symbol": qmt_symbol,
                    "side": side_lower,
                    "volume": order_volume,
                    "price": price,
                    "price_type": price_type,
                    "order_id": order_id,
                },
            )

        except Exception as e:
            logger.error(f"QMT order failed: {e}")
            return OrderResult(
                success=False,
                message=str(e),
            )

    def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an order by order_id.

        Args:
            order_id: The order ID returned by place_market_order / place_limit_order.

        Returns:
            True if cancel request was accepted.
        """
        try:
            self._ensure_connected()
            result = self._trader.cancel_order_stock(self._account, int(order_id))
            # cancel_order_stock returns 0 on success, -1 on failure
            if result == 0:
                logger.info(f"QMT cancel order accepted: order_id={order_id}")
                return True
            else:
                logger.warning(f"QMT cancel order failed: order_id={order_id}, code={result}")
                return False
        except Exception as e:
            logger.error(f"QMT cancel order failed: {e}")
            return False

    # ==================== Query Methods ====================

    def get_account_info(self) -> Dict[str, Any]:
        """
        Get account asset information.

        Returns:
            Dict with cash, frozen_cash, market_value, total_asset.
        """
        try:
            self._ensure_connected()
            asset = self._trader.query_stock_asset(self._account)
            if asset is None:
                return {"success": False, "error": "Failed to get account asset"}
            return {
                "success": True,
                "account_id": self.config.qmt_account_id,
                "cash": float(asset.cash),
                "frozen_cash": float(asset.frozen_cash),
                "market_value": float(asset.market_value),
                "total_asset": float(asset.total_asset),
            }
        except Exception as e:
            logger.error(f"QMT get_account_info failed: {e}")
            return {"success": False, "error": str(e)}

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get stock positions.

        Args:
            symbol: Optional filter by symbol (will be normalized).

        Returns:
            List of position dicts.
        """
        try:
            self._ensure_connected()
            positions = self._trader.query_stock_positions(self._account)
            if positions is None:
                return []

            result = []
            sym_filter = normalize_symbol(symbol) if symbol else None

            for pos in positions:
                code = getattr(pos, "stock_code", "")
                if sym_filter and code.upper() != sym_filter.upper():
                    continue

                # For A-shares: volume = total held, can_use_volume = available to sell (T+1)
                volume = int(getattr(pos, "volume", 0) or 0)
                can_use = int(getattr(pos, "can_use_volume", 0) or 0)
                open_price = float(getattr(pos, "open_price", 0) or 0)
                avg_price = float(getattr(pos, "avg_price", 0) or 0)
                market_value = float(getattr(pos, "market_value", 0) or 0)
                profit = float(getattr(pos, "float_profit", 0) or 0)

                result.append({
                    "symbol": code,
                    "volume": volume,
                    "can_use_volume": can_use,
                    "open_price": open_price,
                    "avg_price": avg_price,
                    "market_value": market_value,
                    "profit": profit,
                    "frozen_volume": int(getattr(pos, "frozen_volume", 0) or 0),
                    "on_hand_volume": int(getattr(pos, "on_hand_volume", 0) or 0),
                })

            return result

        except Exception as e:
            logger.error(f"QMT get_positions failed: {e}")
            return []

    def get_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get today's orders.

        Args:
            symbol: Optional filter by symbol (will be normalized).

        Returns:
            List of order dicts.
        """
        try:
            self._ensure_connected()
            orders = self._trader.query_stock_orders(self._account)
            if orders is None:
                return []

            result = []
            sym_filter = normalize_symbol(symbol) if symbol else None

            for order in orders:
                code = getattr(order, "stock_code", "")
                if sym_filter and code.upper() != sym_filter.upper():
                    continue

                status_val = getattr(order, "order_status", 0)
                result.append({
                    "order_id": getattr(order, "order_id", 0),
                    "symbol": code,
                    "side": "buy" if getattr(order, "order_type", 0) in (23, 24) else "sell",
                    "volume": int(getattr(order, "order_volume", 0) or 0),
                    "traded_volume": int(getattr(order, "traded_volume", 0) or 0),
                    "traded_price": float(getattr(order, "traded_price", 0) or 0),
                    "order_status": self._order_status_str(status_val),
                    "status_msg": getattr(order, "status_msg", ""),
                    "price": float(getattr(order, "price", 0) or 0),
                    "strategy_name": getattr(order, "strategy_name", ""),
                    "order_remark": getattr(order, "order_remark", ""),
                    "order_time": getattr(order, "order_time", 0),
                })

            return result

        except Exception as e:
            logger.error(f"QMT get_orders failed: {e}")
            return []

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get real-time quote for an A-share.

        Uses xtdata.get_quote if available; falls back to empty dict.

        Args:
            symbol: A-share code, e.g. "600000" or "600000.SH".

        Returns:
            Quote data dict.
        """
        try:
            self._ensure_connected()
            qmt_symbol = normalize_symbol(symbol)

            # xtdata is a separate module within xtquant
            try:
                from xtquant import xtdata
            except ImportError:
                return {"success": False, "error": "xtdata module not available"}

            xtdata.download_quote_data(qmt_symbol)
            quote = xtdata.get_quote(qmt_symbol)

            if quote is None:
                return {"success": False, "error": f"Failed to get quote for: {qmt_symbol}"}

            return {
                "success": True,
                "symbol": qmt_symbol,
                "last_price": float(getattr(quote, "last_price", 0) or 0),
                "open": float(getattr(quote, "open", 0) or 0),
                "high": float(getattr(quote, "high", 0) or 0),
                "low": float(getattr(quote, "low", 0) or 0),
                "last_close": float(getattr(quote, "last_close", 0) or 0),
                "volume": int(getattr(quote, "volume", 0) or 0),
                "amount": float(getattr(quote, "amount", 0) or 0),
                "bid_price": float(getattr(quote, "bid_price", [0])[0] if getattr(quote, "bid_price", None) else 0),
                "ask_price": float(getattr(quote, "ask_price", [0])[0] if getattr(quote, "ask_price", None) else 0),
            }

        except Exception as e:
            logger.error(f"QMT get_quote failed: {e}")
            return {"success": False, "error": str(e)}

    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status."""
        return {
            "connected": self.connected,
            "account_id": self.config.qmt_account_id,
            "qmt_path": self.config.qmt_path,
            "session_id": self.config.qmt_session_id,
        }

    # ==================== Helpers ====================

    @staticmethod
    def _order_status_str(status_val: int) -> str:
        """Map xtquant order status int to a readable string."""
        mapping = {
            56: "filled",        # ORDER_SUCCEEDED — 全部成交
            55: "partially_filled",  # ORDER_PART_SUCC — 部分成交
            57: "rejected",      # ORDER_JUNK — 废单
            54: "canceled",      # ORDER_CANCELED — 已撤
            50: "pending",       # ORDER_WAIT — 等待
            53: "cancelling",    # ORDER_CANCLEING — 撤单中
            58: "partially_canceled",  # ORDER_PART_CANCEL — 部撤
            59: "queueing",      # ORDER_QUEUE — 排队中
        }
        return mapping.get(int(status_val), f"unknown({status_val})")


# ---------------------------------------------------------------------------
# Global singleton (optional, aligned with MT5Client pattern)
# ---------------------------------------------------------------------------

_global_client: Optional[QMTClient] = None
_global_lock = threading.Lock()


def get_qmt_client(config: Optional[QMTConfig] = None) -> QMTClient:
    """
    Get global QMT client singleton.

    Args:
        config: Configuration (only effective on first call).

    Returns:
        QMTClient instance.
    """
    global _global_client

    with _global_lock:
        if _global_client is None:
            _global_client = QMTClient(config)
        return _global_client


def reset_qmt_client():
    """Reset global client (disconnect and clear instance)."""
    global _global_client

    with _global_lock:
        if _global_client is not None:
            _global_client.disconnect()
            _global_client = None
