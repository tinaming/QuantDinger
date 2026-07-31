"""
QMT Bridge — lightweight HTTP service running on Windows host.

The Docker backend cannot access miniQMT (xtquant uses Windows IPC).
This bridge runs on the Windows host (port 5002) and exposes the same
QMT trading API. The Docker backend's QMT routes proxy to this bridge
when xtquant is not available locally.

Usage:
    python scripts/qmt_bridge.py
    # Prefer (idempotent + logs): powershell -File scripts/start_qmt_bridge.ps1
    # Autostart watchdog:       powershell -File scripts/install_qmt_bridge_autostart.ps1

Requires:
    - Windows
    - miniQMT running and logged in
    - xtquant available (shipped with miniQMT)
"""
import os
import sys
import json
import time
import threading
from flask import Flask, request, jsonify

# ── xtquant setup ──────────────────────────────────────────────────────
QMT_PATH = os.getenv(
    "QMT_PATH",
    r"D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\userdata_mini",
)
QMT_ACCOUNT_ID = os.getenv("QMT_ACCOUNT_ID", "00930599")
QMT_SESSION_ID = int(os.getenv("QMT_SESSION_ID", "123456"))


def _resolve_qmt_lib_path() -> str:
    """Prefer env, then userdata_mini/site-packages, then already-importable xtquant."""
    env = (os.getenv("QMT_LIB_PATH") or "").strip()
    if env and os.path.isdir(os.path.join(env, "xtquant")):
        return env
    bundled = os.path.join(QMT_PATH, "site-packages")
    if os.path.isdir(os.path.join(bundled, "xtquant")):
        return bundled
    try:
        import xtquant as _xt  # noqa: WPS433 — probe only

        return os.path.dirname(os.path.dirname(_xt.__file__))
    except Exception:
        return env or bundled


QMT_LIB_PATH = _resolve_qmt_lib_path()

if QMT_LIB_PATH and QMT_LIB_PATH not in sys.path:
    sys.path.insert(0, QMT_LIB_PATH)

from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant

# ── Symbol normalization (inline, no dependency on app/) ───────────────

SH_SUFFIX = ".SH"
SZ_SUFFIX = ".SZ"
BJ_SUFFIX = ".BJ"
CN_SUFFIXES = {SH_SUFFIX, SZ_SUFFIX, BJ_SUFFIX}


def _detect_exchange(code: str) -> str:
    c = code.strip()
    if not c or not c[0].isdigit():
        return SH_SUFFIX
    prefix = c[:3]
    sh_prefixes = {"600", "601", "603", "605", "688", "689",
                   "110", "113", "118", "130", "500", "501", "502", "510",
                   "511", "512", "513", "515", "516", "517", "518", "520",
                   "522", "523", "525", "526", "588"}
    sz_prefixes = {"000", "001", "002", "003", "300", "301",
                   "120", "123", "125", "128", "159", "150", "151",
                   "152", "153", "154", "155", "159", "184", "185", "188"}
    bj_prefixes = {"430", "830", "831", "832", "833", "834", "835",
                   "836", "837", "838", "839", "870", "871", "872", "873",
                   "874", "875", "876", "877", "878", "879", "880", "889", "920"}
    if prefix in sh_prefixes:
        return SH_SUFFIX
    if prefix in sz_prefixes:
        return SZ_SUFFIX
    if prefix in bj_prefixes:
        return BJ_SUFFIX
    if c.startswith("6"):
        return SH_SUFFIX
    if c.startswith("0") or c.startswith("3"):
        return SZ_SUFFIX
    if c.startswith("8") or c.startswith("4") or c.startswith("9"):
        return BJ_SUFFIX
    return SH_SUFFIX


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    s = s.replace(" ", "").replace("-", "").replace("_", "").replace("/", "")
    for pfx, sfx in (("SH", SH_SUFFIX), ("SZ", SZ_SUFFIX), ("BJ", BJ_SUFFIX), ("SS", SH_SUFFIX)):
        if s.startswith(pfx) and len(s) > len(pfx):
            rest = s[len(pfx):]
            if rest and rest[0].isdigit():
                s = rest + sfx
                break
    for alias, real in ((".XSHG", SH_SUFFIX), (".XSHE", SZ_SUFFIX),
                         (".SS", SH_SUFFIX), (".SZ", SZ_SUFFIX),
                         (".SH", SH_SUFFIX), (".BJ", BJ_SUFFIX)):
        if s.endswith(alias):
            s = s[: -len(alias)] + real
            break
    for sfx in CN_SUFFIXES:
        if s.endswith(sfx):
            return s
    if "." in s:
        tail = s[s.rfind("."):]
        if tail.upper() in CN_SUFFIXES:
            return s
        s = s[: s.rfind(".")]
    return s + _detect_exchange(s)


# ── QMT connection management ──────────────────────────────────────────

_lock = threading.Lock()
_trader: XtQuantTrader | None = None
_account: StockAccount | None = None
_connected = False


class _BridgeCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        global _connected
        _connected = False
        print("[bridge] miniQMT disconnected")

    def on_stock_order(self, order):
        pass

    def on_stock_trade(self, trade):
        pass

    def on_order_error(self, err):
        print(f"[bridge] order error: {getattr(err, 'error_msg', '')}")

    def on_cancel_error(self, err):
        print(f"[bridge] cancel error: {getattr(err, 'error_msg', '')}")

    def on_account_status(self, status):
        pass


def _stop_trader_unlocked() -> None:
    """Stop and clear trader/account. Caller must hold ``_lock``."""
    global _trader, _account, _connected
    if _trader is not None:
        try:
            _trader.stop()
        except Exception:
            pass
    _trader = None
    _account = None
    _connected = False


def _ensure_connected() -> bool:
    global _trader, _account, _connected
    if _connected and _trader is not None:
        return True
    with _lock:
        if _connected and _trader is not None:
            return True
        # Stale session after on_disconnected: trader may still exist with
        # _connected=False. Tear it down before creating a new session, or
        # xtquant IPC / session_id conflicts cause intermittent connect failures.
        _stop_trader_unlocked()
        try:
            _trader = XtQuantTrader(QMT_PATH, QMT_SESSION_ID)
            _trader.register_callback(_BridgeCallback())
            _trader.start()
            time.sleep(1)
            # miniQMT IPC can briefly refuse connect right after restart/login.
            result = -1
            for attempt in range(1, 6):
                result = _trader.connect()
                if result == 0:
                    break
                print(f"[bridge] connect attempt {attempt}/5 failed: {result}")
                time.sleep(2)
            if result != 0:
                print(f"[bridge] connect failed: {result}")
                _stop_trader_unlocked()
                return False
            _account = StockAccount(QMT_ACCOUNT_ID)
            sub = _trader.subscribe(_account)
            if sub != 0:
                print(f"[bridge] subscribe failed: {sub}")
                _stop_trader_unlocked()
                return False
            _connected = True
            print(f"[bridge] connected: account={QMT_ACCOUNT_ID}")
            return True
        except Exception as e:
            print(f"[bridge] connection error: {e}")
            _stop_trader_unlocked()
            return False


def _disconnect():
    with _lock:
        _stop_trader_unlocked()


# ── Flask app ──────────────────────────────────────────────────────────

app = Flask(__name__)


def _ok(data, message="ok"):
    return jsonify({"code": 0, "message": message, "data": data})


def _err(code, message, details=""):
    return jsonify({"code": code, "message": message, "details": details})


def _lot_size_for_symbol(symbol: str) -> int:
    """Main-board A-shares: 100; STAR/ChiNext/BJ often allow 1."""
    code = (symbol or "").split(".")[0]
    if code.startswith(("688", "689", "300", "301", "8", "4", "9")):
        return 1
    return 100


def _reject_if_below_lot(symbol: str, volume: int):
    lot = _lot_size_for_symbol(symbol)
    if volume < lot or (lot > 1 and volume % lot != 0):
        return _err(
            400,
            f"qmt_volume_below_lot:{volume} (board lot is {lot} shares for {symbol})",
        )
    return None


@app.route("/qmt/status")
def status():
    return _ok({
        "connected": _connected,
        "account_id": QMT_ACCOUNT_ID,
        "qmt_path": QMT_PATH,
        "session_id": QMT_SESSION_ID,
    })


@app.route("/qmt/connect", methods=["POST"])
def connect():
    if _connected:
        return _ok({"connected": True, "message": "Already connected"})
    ok = _ensure_connected()
    if not ok:
        return _err(502, "Failed to connect to miniQMT")
    return _ok({"connected": True, "message": "Connected successfully"})


@app.route("/qmt/disconnect", methods=["POST"])
def disconnect():
    _disconnect()
    return _ok({"connected": False, "message": "Disconnected"})


@app.route("/qmt/asset")
def asset():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        a = _trader.query_stock_asset(_account)
        if a is None:
            return _err(502, "Failed to query asset")
        return _ok({
            "success": True,
            "account_id": QMT_ACCOUNT_ID,
            "cash": float(a.cash),
            "frozen_cash": float(a.frozen_cash),
            "market_value": float(a.market_value),
            "total_asset": float(a.total_asset),
        })
    except Exception as e:
        return _err(500, f"Asset query error: {e}")


@app.route("/qmt/positions")
def positions():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        sym_filter = normalize_symbol(request.args.get("symbol", "")) if request.args.get("symbol") else None
        raw = _trader.query_stock_positions(_account) or []
        result = []
        for p in raw:
            code = getattr(p, "stock_code", "")
            if sym_filter and code.upper() != sym_filter:
                continue
            result.append({
                "symbol": code,
                "volume": int(getattr(p, "volume", 0) or 0),
                "can_use_volume": int(getattr(p, "can_use_volume", 0) or 0),
                "open_price": float(getattr(p, "open_price", 0) or 0),
                "avg_price": float(getattr(p, "avg_price", 0) or 0),
                "last_price": float(getattr(p, "last_price", 0) or 0),
                "market_value": float(getattr(p, "market_value", 0) or 0),
                "float_profit": float(getattr(p, "float_profit", 0) or 0),
                "frozen_volume": int(getattr(p, "frozen_volume", 0) or 0),
            })
        return _ok({"positions": result, "count": len(result)})
    except Exception as e:
        return _err(500, f"Positions query error: {e}")


@app.route("/qmt/orders")
def orders():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        sym_filter = normalize_symbol(request.args.get("symbol", "")) if request.args.get("symbol") else None
        raw = _trader.query_stock_orders(_account) or []
        result = []
        for o in raw:
            code = getattr(o, "stock_code", "")
            if sym_filter and code.upper() != sym_filter:
                continue
            status_val = getattr(o, "order_status", 0)
            status_map = {56: "filled", 55: "partially_filled", 57: "rejected",
                          54: "canceled", 50: "pending", 53: "cancelling",
                          58: "partially_canceled", 59: "queueing"}
            result.append({
                "order_id": getattr(o, "order_id", 0),
                "symbol": code,
                "side": "buy" if getattr(o, "order_type", 0) in (23, 24) else "sell",
                "volume": int(getattr(o, "order_volume", 0) or 0),
                "traded_volume": int(getattr(o, "traded_volume", 0) or 0),
                "traded_price": float(getattr(o, "traded_price", 0) or 0),
                "order_status": status_map.get(int(status_val), f"unknown({status_val})"),
                "price": float(getattr(o, "price", 0) or 0),
                "order_time": getattr(o, "order_time", 0),
            })
        return _ok({"orders": result, "count": len(result)})
    except Exception as e:
        return _err(500, f"Orders query error: {e}")


@app.route("/qmt/quote")
def quote():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return _err(400, "symbol parameter is required")
    try:
        from xtquant import xtdata
        qmt_symbol = normalize_symbol(symbol)

        # 1. Try get_full_tick (requires prior subscription)
        try:
            tick = xtdata.get_full_tick([qmt_symbol])
            if tick and qmt_symbol in tick:
                t = tick[qmt_symbol]
                lp = float(t.get('lastPrice', 0))
                if lp > 0:
                    return _ok({
                        "success": True,
                        "symbol": qmt_symbol,
                        "last_price": lp,
                        "open": float(t.get('open', 0)),
                        "high": float(t.get('high', 0)),
                        "low": float(t.get('low', 0)),
                        "last_close": float(t.get('lastClose', 0)),
                        "volume": int(t.get('volume', 0)),
                        "amount": float(t.get('amount', 0)),
                        "bid_price": float(t.get('bidPrice', [0])[0] if t.get('bidPrice') else 0),
                        "ask_price": float(t.get('askPrice', [0])[0] if t.get('askPrice') else 0),
                    })
        except Exception:
            pass

        # 2. Subscribe and use get_market_data_ex (always works, auto-downloads)
        try:
            xtdata.subscribe_quote(qmt_symbol, period='1m')
        except Exception:
            pass

        data = xtdata.get_market_data_ex(
            field_list=[],
            stock_list=[qmt_symbol],
            period='1m',
            count=2,
            dividend_type="front",
        )
        if data and qmt_symbol in data and len(data[qmt_symbol]) > 0:
            df = data[qmt_symbol]
            last_row = df.iloc[-1]
            prev_close = float(df.iloc[-2].get('close', 0)) if len(df) >= 2 else 0.0
            last_price = float(last_row.get('close', 0))
            if last_price > 0:
                return _ok({
                    "success": True,
                    "symbol": qmt_symbol,
                    "last_price": last_price,
                    "open": float(last_row.get('open', 0)),
                    "high": float(last_row.get('high', 0)),
                    "low": float(last_row.get('low', 0)),
                    "last_close": prev_close,
                    "volume": int(last_row.get('volume', 0)),
                    "amount": float(last_row.get('amount', 0)),
                })
        return _err(502, f"No quote for {qmt_symbol}")
    except Exception as e:
        return _err(500, f"Quote error: {e}")


@app.route("/qmt/klines")
def klines():
    """Fetch K-line (candlestick) data via xtdata.

    Query params:
      symbol   — e.g. 600519.SH
      period   — 1m, 5m, 15m, 30m, 1H, 1D, 1W (default: 1m)
      count    — number of bars (default: 300)
    """
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    symbol = request.args.get("symbol", "").strip()
    period = request.args.get("period", "1m").strip().lower()
    count = int(request.args.get("count", 300))
    if not symbol:
        return _err(400, "symbol parameter is required")

    # Map common timeframe strings to xtdata period codes
    period_map = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "60m": "1H",
        "1d": "1D", "day": "1D", "1w": "1W", "week": "1W",
    }
    xt_period = period_map.get(period, period)

    try:
        from xtquant import xtdata
        qmt_symbol = normalize_symbol(symbol)

        # Subscribe and download history data
        try:
            xtdata.subscribe_quote(qmt_symbol, period=xt_period)
            # Download history data to ensure availability
            xtdata.download_history_data(qmt_symbol, period=xt_period, start_time='20250101')
            import time; time.sleep(0.5)  # Wait for download
        except Exception as e:
            pass

        # Use get_market_data_ex for historical K-lines
        data = xtdata.get_market_data_ex(
            field_list=[],
            stock_list=[qmt_symbol],
            period=xt_period,
            count=count,
            dividend_type="front",
        )

        if not data or qmt_symbol not in data or len(data[qmt_symbol]) == 0:
            return _err(502, f"No kline data for {qmt_symbol} period={xt_period}")

        df = data[qmt_symbol]
        bars = []
        for ts, row in df.iterrows():
            # xtdata returns index as string like '20260701145900' (YYYYMMDDHHMMSS)
            epoch = 0
            try:
                from datetime import datetime
                ts_str = str(ts)
                # Try YYYYMMDDHHMMSS format (xtdata native)
                if len(ts_str) >= 14 and ts_str.isdigit():
                    dt = datetime.strptime(ts_str[:14], "%Y%m%d%H%M%S")
                # Try standard datetime format
                elif "-" in ts_str:
                    clean = ts_str.replace(".000", "")[:19]
                    dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
                else:
                    dt = None
                if dt:
                    epoch = int(dt.timestamp())
            except Exception:
                epoch = 0

            bars.append({
                "time": epoch,
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": float(row.get("volume", 0)),
            })

        return _ok({
            "symbol": qmt_symbol,
            "period": xt_period,
            "count": len(bars),
            "bars": bars,
        })
    except Exception as e:
        return _err(500, f"Kline error: {e}")


@app.route("/qmt/orders", methods=["POST"])
def place_order():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    body = request.get_json(force=True) or {}
    symbol = (body.get("symbol") or "").strip()
    side = (body.get("side") or "").strip().lower()
    order_type = (body.get("order_type") or body.get("orderType") or "market").strip().lower()
    volume = int(body.get("volume") or body.get("qty") or 0)
    price = float(body.get("price") or body.get("limit_price") or 0)
    comment = (body.get("comment") or "ChanQuant").strip()

    if not symbol:
        return _err(400, "symbol is required")
    if side not in ("buy", "sell"):
        return _err(400, "side must be 'buy' or 'sell'")
    if volume <= 0:
        return _err(400, "volume must be positive")

    qmt_symbol = normalize_symbol(symbol)
    lot_err = _reject_if_below_lot(qmt_symbol, volume)
    if lot_err is not None:
        return lot_err
    order_dir = xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL

    # Always use FIX_PRICE (limit order) to avoid LATEST_PRICE rejection
    # in QMT simulation / non-trading hours.  For "market" orders we fetch
    # the latest quote and use it as the limit price.
    pt = xtconstant.FIX_PRICE
    if order_type == "limit" and price <= 0:
        return _err(400, "price required for limit orders")
    if order_type != "limit" or price <= 0:
        # Fetch latest price from quote for market orders
        try:
            from xtquant import xtdata as _xd
            tick = _xd.get_full_tick([qmt_symbol])
            if tick and qmt_symbol in tick:
                lp = float(tick[qmt_symbol].get("lastPrice", 0) or 0)
                if lp > 0:
                    price = lp
        except Exception:
            pass
        if price <= 0:
            # Fallback: try get_market_data_ex
            try:
                from xtquant import xtdata as _xd
                md = _xd.get_market_data_ex([], [qmt_symbol], period="1m", count=1)
                if md and qmt_symbol in md and len(md[qmt_symbol]) > 0:
                    price = float(md[qmt_symbol].iloc[-1].get("close", 0))
            except Exception:
                pass
        if price <= 0:
            return _err(400, f"Cannot determine price for {qmt_symbol}; market order needs a valid quote")
        print(f"[Bridge] Market order converted to limit: {side} {volume} {qmt_symbol} @ {price}")

    try:
        order_id = _trader.order_stock(
            _account, qmt_symbol, order_dir, volume, pt, price,
            "ChanQuant", comment,
        )
        if order_id is None or order_id < 0:
            return _err(500, f"order_stock returned error: {order_id}")

        filled = 0.0
        fill_price = 0.0
        status_str = "submitted"
        status_map = {
            56: "filled", 55: "partially_filled", 57: "rejected",
            54: "canceled", 50: "pending", 53: "cancelling",
            58: "partially_canceled", 59: "queueing",
        }

        # Poll for order fill — market orders on A-shares usually fill within
        # seconds, but we must NOT return 0/0 as fill data; that would cause
        # the caller to use the reference price instead of the real fill price.
        # Keep under typical upstream HTTP timeouts (routes/worker use >=45s).
        _POLL_MAX = 12          # max seconds to wait
        _POLL_INTERVAL = 0.5    # seconds between polls
        _elapsed = 0.0
        while _elapsed < _POLL_MAX:
            try:
                o = _trader.query_stock_order(_account, order_id)
                if o:
                    status_val = int(getattr(o, "order_status", 0) or 0)
                    mapped = status_map.get(status_val, "")
                    traded_vol = float(getattr(o, "traded_volume", 0) or 0)
                    traded_px = float(getattr(o, "traded_price", 0) or 0)
                    if mapped in ("rejected", "canceled"):
                        return _err(
                            400,
                            f"qmt_order_{mapped}:{order_id}",
                            details=f"order_status={status_val}",
                        )
                    if traded_vol > 0 and traded_px > 0:
                        filled = traded_vol
                        fill_price = traded_px
                        status_str = "filled" if mapped == "filled" else "partial"
                        if mapped == "filled":
                            break
                    # Partial fill or still pending — keep waiting
                    elif traded_vol > 0:
                        filled = traded_vol
                        fill_price = traded_px
                        status_str = "partial"
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL)
            _elapsed += _POLL_INTERVAL

        if status_str == "submitted":
            # Still no fill data after timeout — return order_id only,
            # explicitly mark filled/price as None so caller knows it's unknown.
            return _ok({
                "order_id": order_id,
                "filled": 0,
                "price": 0.0,
                "status": "submitted",
                "message": f"Order submitted but not filled within {_POLL_MAX}s",
                "paper": False,
            }, message="live-order-pending")

        return _ok({
            "order_id": order_id,
            "filled": filled,
            "price": fill_price,
            "status": status_str,
            "message": "Order filled" if status_str == "filled" else "Order partially filled",
            "paper": False,
        }, message="live-order")
    except Exception as e:
        return _err(500, f"Order error: {e}")


@app.route("/qmt/orders/<int:order_id>", methods=["GET"])
def query_order(order_id: int):
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        o = _trader.query_stock_order(_account, order_id)
        if not o:
            return _err(404, f"Order {order_id} not found")
        status_val = getattr(o, "order_status", 0)
        status_map = {56: "filled", 55: "partially_filled", 57: "rejected",
                      54: "canceled", 50: "pending", 53: "cancelling",
                      58: "partially_canceled", 59: "queueing"}
        return _ok({
            "order_id": getattr(o, "order_id", 0),
            "symbol": getattr(o, "stock_code", ""),
            "side": "buy" if getattr(o, "order_type", 0) in (23, 24) else "sell",
            "volume": int(getattr(o, "order_volume", 0) or 0),
            "traded_volume": int(getattr(o, "traded_volume", 0) or 0),
            "traded_price": float(getattr(o, "traded_price", 0) or 0),
            "order_status": status_map.get(int(status_val), f"unknown({status_val})"),
            "price": float(getattr(o, "price", 0) or 0),
            "order_time": getattr(o, "order_time", 0),
        })
    except Exception as e:
        return _err(500, f"Order query error: {e}")


@app.route("/qmt/orders/<int:order_id>", methods=["DELETE"])
def cancel_order(order_id: int):
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        result = _trader.cancel_order_stock(_account, order_id)
        if result == 0:
            return _ok({"order_id": order_id, "cancelled": True, "message": "Cancel accepted"})
        return _err(500, f"Cancel failed: code={result}")
    except Exception as e:
        return _err(500, f"Cancel error: {e}")


# ── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("QMT_BRIDGE_PORT", "5002"))
    print(f"=== QMT Bridge starting on port {port} ===")
    print(f"  QMT_PATH: {QMT_PATH}")
    print(f"  ACCOUNT:  {QMT_ACCOUNT_ID}")
    print(f"  SESSION:  {QMT_SESSION_ID}")

    # Auto-connect on startup
    if _ensure_connected():
        print("  Status:   CONNECTED")
    else:
        print("  Status:   NOT CONNECTED (miniQMT may not be running)")

    app.run(host="0.0.0.0", port=port, debug=False)
