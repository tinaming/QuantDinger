"""
Factory for direct exchange clients.

Supports:
- Crypto exchanges: Binance, OKX, Bitget, Bybit, Coinbase, Kraken, Gate, HTX
- Traditional brokers: Interactive Brokers (IBKR) for US stocks
- Forex brokers: MetaTrader 5 (MT5)
- Alpaca: REST broker for US stocks + crypto
- QMT (miniQMT): A-share (China A-Stock) broker via xtquant SDK
"""

from __future__ import annotations

import logging
import os
import platform
import requests
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)

from app.services.live_trading.base import BaseRestClient, LiveTradingError
from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.okx import OkxClient
from app.services.live_trading.bitget import BitgetMixClient
from app.services.live_trading.bitget_spot import BitgetSpotClient
from app.services.live_trading.bybit import BybitClient
from app.services.live_trading.coinbase_exchange import CoinbaseExchangeClient
from app.services.live_trading.kraken import KrakenClient
from app.services.live_trading.kraken_futures import KrakenFuturesClient
from app.services.live_trading.gate import GateSpotClient, GateUsdtFuturesClient
from app.services.live_trading.htx import HtxClient

# Lazy import IBKR to avoid ImportError if ib_insync not installed
IBKRClient = None
IBKRConfig = None

# Lazy import MT5 to avoid ImportError if MetaTrader5 not installed
MT5Client = None
MT5Config = None

# Lazy import Alpaca to avoid ImportError if alpaca-py not installed
AlpacaClient = None
AlpacaConfig = None

# Lazy import QMT to avoid ImportError if xtquant not installed
QMTClient = None
QMTConfig = None


def _get(cfg: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = cfg.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


# Merged from HTTP JSON root into nested `exchange_config` for /strategies/test-connection
# when the UI sends demo/testnet toggles next to the nested object.
EXCHANGE_CONFIG_ROOT_OVERLAY_KEYS = (
    "enable_demo_trading",
    "enableDemoTrading",
    "simulated_trading",
    "simulatedTrading",
    "use_testnet",
    "is_testnet",
    "isTestnet",
    "sandbox",
    "paper_trading",
    "paperTrading",
    "network",
    "environment",
    "env",
    "base_url",
    "baseUrl",
    "futures_base_url",
    "futuresBaseUrl",
)


def merge_root_exchange_config_overlay(*, root: Dict[str, Any], exchange_config: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay selected keys from the request root onto exchange_config (copying the latter)."""
    out = dict(exchange_config or {})
    if not isinstance(root, dict):
        return out
    for k in EXCHANGE_CONFIG_ROOT_OVERLAY_KEYS:
        if k in root:
            out[k] = root[k]
    return out


def exchange_demo_mode_enabled(cfg: Dict[str, Any]) -> bool:
    """
    Whether config indicates demo / testnet / simulated / paper mode for live-trading clients.

    Accepts common frontend / exchange naming variants so test-connection matches create_client.
    """
    if not isinstance(cfg, dict):
        return False
    env = str(cfg.get("network") or cfg.get("environment") or cfg.get("env") or "").strip().lower()
    if env in ("testnet", "sandbox", "demo", "paper", "simulate", "simulation"):
        return True
    for k in (
        "enable_demo_trading",
        "enableDemoTrading",
        "simulated_trading",
        "simulatedTrading",
        "use_testnet",
        "is_testnet",
        "isTestnet",
        "sandbox",
        "paper_trading",
        "paperTrading",
        # Alpaca stores its paper/live flag as a bare `paper` boolean — alias it
        # so /api/credentials/list shows the right paper badge on Alpaca rows.
        "paper",
        "is_paper",
    ):
        v = cfg.get(k)
        if v is None:
            continue
        if isinstance(v, bool) and v:
            return True
        if isinstance(v, (int, float)) and int(v) == 1:
            return True
        if isinstance(v, str) and str(v).strip().lower() in ("true", "1", "yes", "on"):
            return True
    return False


def _demo_enabled(cfg: Dict[str, Any]) -> bool:
    return exchange_demo_mode_enabled(cfg)


def create_client(exchange_config: Dict[str, Any], *, market_type: str = "swap") -> BaseRestClient:
    if not isinstance(exchange_config, dict):
        raise LiveTradingError("Invalid exchange_config")
    exchange_id = _get(exchange_config, "exchange_id", "exchangeId").lower()
    api_key = _get(exchange_config, "api_key", "apiKey")
    secret_key = _get(exchange_config, "secret_key", "secret")
    passphrase = _get(exchange_config, "passphrase", "password")

    mt = (market_type or exchange_config.get("market_type") or exchange_config.get("defaultType") or "swap").strip().lower()
    if mt in ("futures", "future", "perp", "perpetual"):
        mt = "swap"

    is_demo = _demo_enabled(exchange_config)

    if exchange_id == "binance":
        spot_broker_id = _get(exchange_config, "spot_broker_id", "spotBrokerId", "broker_id", "brokerId") or "A2NAPZAC"
        futures_broker_id = _get(exchange_config, "futures_broker_id", "futuresBrokerId", "broker_id", "brokerId") or "HBpUbQjT"
        if mt == "spot":
            # Binance Spot Testnet: https://testnet.binance.vision (official)
            default_url = "https://testnet.binance.vision" if is_demo else "https://api.binance.com"
            base_url = _get(exchange_config, "base_url", "baseUrl") or default_url
            return BinanceSpotClient(api_key=api_key, secret_key=secret_key, base_url=base_url, enable_demo_trading=is_demo, broker_id=spot_broker_id)
        # Default to USDT-M futures
        # Binance Futures Testnet: https://testnet.binancefuture.com (official)
        default_url = "https://testnet.binancefuture.com" if is_demo else "https://fapi.binance.com"
        base_url = _get(exchange_config, "base_url", "baseUrl") or default_url
        return BinanceFuturesClient(api_key=api_key, secret_key=secret_key, base_url=base_url, enable_demo_trading=is_demo, broker_id=futures_broker_id)
    if exchange_id == "okx":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://www.okx.com"
        broker_code = "56fa80b0ce8cBCDE"
        return OkxClient(
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
            base_url=base_url,
            broker_code=broker_code,
            simulated_trading=is_demo,
        )
    if exchange_id == "bitget":
        # Bitget simulated trading uses the same REST host; keys must be created in Bitget demo trading.
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.bitget.com"
        if mt == "spot":
            channel_api_code = _get(exchange_config, "channel_api_code", "channelApiCode") or "qvz9x"
            return BitgetSpotClient(
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
                base_url=base_url,
                channel_api_code=channel_api_code,
                simulated_trading=is_demo,
            )
        channel_api_code = _get(exchange_config, "channel_api_code", "channelApiCode") or "qvz9x"
        return BitgetMixClient(
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
            base_url=base_url,
            channel_api_code=channel_api_code,
            simulated_trading=is_demo,
        )

    if exchange_id == "bybit":
        default_bybit = "https://api-testnet.bybit.com" if is_demo else "https://api.bybit.com"
        base_url = _get(exchange_config, "base_url", "baseUrl") or default_bybit
        category = "spot" if mt == "spot" else "linear"
        recv_window_ms = int(exchange_config.get("recv_window_ms") or exchange_config.get("recvWindow") or 12000)
        broker_referer = _get(exchange_config, "bybit_referer", "broker_referer", "brokerReferer") or "Ri001020"
        hedge_mode_raw = exchange_config.get("hedge_mode")
        if hedge_mode_raw is None:
            hedge_mode_raw = exchange_config.get("hedgeMode")
        if hedge_mode_raw is None:
            hedge_mode_raw = exchange_config.get("position_mode") or exchange_config.get("positionMode")
        hedge_mode = False
        if isinstance(hedge_mode_raw, bool):
            hedge_mode = hedge_mode_raw
        else:
            hedge_mode = str(hedge_mode_raw or "").strip().lower() in ("true", "1", "yes", "hedge", "both_side")
        return BybitClient(
            api_key=api_key,
            secret_key=secret_key,
            base_url=base_url,
            category=category,
            recv_window_ms=recv_window_ms,
            broker_referer=broker_referer,
            hedge_mode=hedge_mode,
        )

    if exchange_id in ("coinbaseexchange", "coinbase_exchange"):
        default_cb = "https://api-public.sandbox.exchange.coinbase.com" if is_demo else "https://api.exchange.coinbase.com"
        base_url = _get(exchange_config, "base_url", "baseUrl") or default_cb
        if mt != "spot":
            raise LiveTradingError("CoinbaseExchange only supports spot market_type in this project")
        return CoinbaseExchangeClient(api_key=api_key, secret_key=secret_key, passphrase=passphrase, base_url=base_url)

    if exchange_id == "kraken":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.kraken.com"
        if mt == "spot":
            # Kraken spot REST has no separate public sandbox URL; use demo keys on production API if offered by Kraken.
            return KrakenClient(api_key=api_key, secret_key=secret_key, base_url=base_url)
        fut_default = "https://demo-futures.kraken.com" if is_demo else "https://futures.kraken.com"
        fut_url = _get(exchange_config, "futures_base_url", "futuresBaseUrl") or fut_default
        return KrakenFuturesClient(api_key=api_key, secret_key=secret_key, base_url=fut_url)

    if exchange_id == "gate":
        gate_channel_id = _get(exchange_config, "gate_channel_id", "gateChannelId") or "dinger"
        if mt == "spot":
            default_gate = "https://api-testnet.gateio.ws" if is_demo else "https://api.gateio.ws"
            base_url = _get(exchange_config, "base_url", "baseUrl") or default_gate
            return GateSpotClient(api_key=api_key, secret_key=secret_key, base_url=base_url, channel_id=gate_channel_id)
        default_fut = "https://fx-api-testnet.gateio.ws" if is_demo else "https://fx-api.gateio.ws"
        base_url = _get(exchange_config, "base_url", "baseUrl") or default_fut
        return GateUsdtFuturesClient(api_key=api_key, secret_key=secret_key, base_url=base_url, channel_id=gate_channel_id)

    if exchange_id == "htx":
        if is_demo and not (_get(exchange_config, "base_url", "baseUrl") or _get(exchange_config, "futures_base_url", "futuresBaseUrl")):
            raise LiveTradingError("HTX demo/testnet is not configured in this project yet. Please disable demo mode or provide explicit testnet base_url/futures_base_url.")
        spot_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.htx.com"
        futures_url = _get(exchange_config, "futures_base_url", "futuresBaseUrl") or "https://api.hbdm.com"
        broker_id = _get(exchange_config, "broker_id", "brokerId") or "AA7b890547"
        return HtxClient(
            api_key=api_key,
            secret_key=secret_key,
            base_url=spot_url,
            futures_base_url=futures_url,
            market_type=mt,
            broker_id=broker_id,
        )

    # Traditional brokers (IBKR for US stocks only)
    if exchange_id == "ibkr":
        # Note: Market category validation should be done at the caller level
        # This factory only creates clients based on exchange_id
        return create_ibkr_client(exchange_config)

    # Forex brokers (MT5 for Forex only)
    if exchange_id == "mt5":
        # Note: Market category validation should be done at the caller level
        # This factory only creates clients based on exchange_id
        return create_mt5_client(exchange_config)

    # Alpaca: REST broker for US stocks + crypto (no local terminal needed).
    # Caller is responsible for validating market_category in (USStock, Crypto).
    if exchange_id == "alpaca":
        return create_alpaca_client(exchange_config)

    # QMT (miniQMT): A-share (CNStock) broker via xtquant SDK
    # (local desktop only — miniQMT client must be running and logged in).
    if exchange_id == "qmt":
        return create_qmt_client(exchange_config)

    raise LiveTradingError(f"Unsupported exchange_id: {exchange_id}")


def create_ibkr_client(exchange_config: Dict[str, Any]):
    """
    Create IBKR client for US stock trading.

    exchange_config should contain:
    - ibkr_host: TWS/Gateway host (default: 127.0.0.1)
    - ibkr_port: TWS/Gateway port (default: 7497 = TWS Paper; TWS Live default is 7496)
    - ibkr_client_id: Client ID (see below — must not collide with /api/ibkr UI)
    - ibkr_account: Account ID (optional, auto-select if empty)

    TWS allows one TCP session per clientId. The admin UI ``POST /api/ibkr/connect``
    defaults to clientId=1; live orders therefore default to ``IBKR_ORDER_CLIENT_ID``
    (7) when credentials omit ibkr_client_id, so manual testing does not evict the worker
    (and vice versa).
    """
    global IBKRClient, IBKRConfig

    # Lazy import to avoid ImportError if ib_insync not installed
    if IBKRClient is None or IBKRConfig is None:
        try:
            from app.services.ibkr_trading import IBKRClient as _IBKRClient, IBKRConfig as _IBKRConfig
            IBKRClient = _IBKRClient
            IBKRConfig = _IBKRConfig
        except ImportError:
            raise LiveTradingError("IBKR trading requires ib_insync. Run: pip install ib_insync")

    host = str(exchange_config.get("ibkr_host") or "127.0.0.1").strip()
    port = int(exchange_config.get("ibkr_port") or 7497)
    default_order_cid = int(os.getenv("IBKR_ORDER_CLIENT_ID", "7"))
    _cid_raw = exchange_config.get("ibkr_client_id")
    if _cid_raw is None or (isinstance(_cid_raw, str) and not str(_cid_raw).strip()):
        client_id = default_order_cid
    else:
        try:
            client_id = int(_cid_raw)
        except (TypeError, ValueError):
            client_id = default_order_cid
    account = str(exchange_config.get("ibkr_account") or "").strip()

    if client_id == 1:
        logger.warning(
            "IBKR strategy/order client uses clientId=1 — same default as POST /api/ibkr/connect; "
            "TWS will drop the other session. Prefer ibkr_client_id=7 or IBKR_ORDER_CLIENT_ID."
        )

    config = IBKRConfig(
        host=host,
        port=port,
        client_id=client_id,
        account=account,
        readonly=False,
    )

    client = IBKRClient(config)

    # Connect immediately (IBKR requires active connection)
    if not client.connect():
        raise LiveTradingError("Failed to connect to IBKR TWS/Gateway. Please check if it's running.")

    return client


def create_mt5_client(exchange_config: Dict[str, Any]):
    """
    Create MT5 client for forex trading.

    exchange_config should contain:
    - mt5_login: MT5 account number
    - mt5_password: MT5 password
    - mt5_server: Broker server name (e.g., "ICMarkets-Demo")
    - mt5_terminal_path: Optional path to terminal64.exe
    - market_category: Must be "Forex" (validated)
    
    Note: MT5 is ONLY for Forex trading, not for Crypto or Stocks.
    """
    global MT5Client, MT5Config

    # Validate market category - MT5 is ONLY for Forex
    market_category = str(exchange_config.get("market_category") or "").strip()
    if market_category and market_category != "Forex":
        raise LiveTradingError(
            f"MT5 can only be used for Forex trading, but market_category is '{market_category}'. "
            f"MT5 does not support Crypto or Stock trading. Please use MT5 only with Forex market."
        )

    # Lazy import to avoid ImportError if MetaTrader5 not installed
    if MT5Client is None or MT5Config is None:
        try:
            from app.services.mt5_trading import MT5Client as _MT5Client, MT5Config as _MT5Config
            MT5Client = _MT5Client
            MT5Config = _MT5Config
        except ImportError:
            raise LiveTradingError(
                "MT5 trading requires MetaTrader5 library. Run: pip install MetaTrader5\n"
                "Note: This library only works on Windows."
            )

    # Handle login as int (may come as string from JSON)
    login_raw = exchange_config.get("mt5_login") or 0
    try:
        login = int(login_raw) if login_raw else 0
    except (ValueError, TypeError):
        # Try converting string to int
        try:
            login = int(str(login_raw).strip())
        except (ValueError, TypeError):
            login = 0
    
    password = str(exchange_config.get("mt5_password") or "").strip()
    server = str(exchange_config.get("mt5_server") or "").strip()
    terminal_path = str(exchange_config.get("mt5_terminal_path") or "").strip()

    if not login or not password or not server:
        raise LiveTradingError("MT5 requires login, password, and server")

    config = MT5Config(
        login=login,
        password=password,
        server=server,
        terminal_path=terminal_path,
    )

    client = MT5Client(config)

    # Connect immediately
    if not client.connect():
        raise LiveTradingError(
            "Failed to connect to MT5 terminal. Please check:\n"
            "1. MT5 terminal is running\n"
            "2. Credentials are correct\n"
            "3. You are on Windows"
        )

    return client


def create_alpaca_client(exchange_config: Dict[str, Any]):
    """
    Create Alpaca client for US stock + crypto trading.

    exchange_config should contain:
    - api_key:    Alpaca API key (PK*=paper, AK*=live)
    - secret_key: Alpaca API secret
    - paper:      Boolean (default True). 'true'/'false' strings also accepted.
    - base_url:   Optional explicit URL override (otherwise paper/live decides)

    Unlike IBKR/MT5, Alpaca is stateless REST — no terminal/gateway needed,
    so it's the recommended USStock broker on cloud / SaaS deployments where
    ALLOW_LOCAL_DESKTOP_BROKERS is false.
    """
    global AlpacaClient, AlpacaConfig

    if AlpacaClient is None or AlpacaConfig is None:
        try:
            from app.services.alpaca_trading import AlpacaClient as _AlpacaClient, AlpacaConfig as _AlpacaConfig
            AlpacaClient = _AlpacaClient
            AlpacaConfig = _AlpacaConfig
        except ImportError:
            raise LiveTradingError("Alpaca trading requires alpaca-py. Run: pip install alpaca-py")

    api_key = (_get(exchange_config, "api_key", "apiKey") or "").strip()
    secret_key = (_get(exchange_config, "secret_key", "secret", "secretKey") or "").strip()
    if not api_key or not secret_key:
        raise LiveTradingError("Alpaca requires api_key and secret_key")

    # Paper mode: explicit flag wins; otherwise infer from key prefix (PK = paper).
    paper_raw = exchange_config.get("paper")
    if paper_raw is None:
        paper_raw = exchange_config.get("is_paper")
    if isinstance(paper_raw, bool):
        paper = paper_raw
    elif isinstance(paper_raw, str) and paper_raw.strip():
        paper = paper_raw.strip().lower() in ("1", "true", "yes", "on", "paper")
    else:
        paper = api_key.upper().startswith("PK")

    base_url = _get(exchange_config, "base_url", "baseUrl") or None

    config = AlpacaConfig(
        api_key=api_key,
        secret_key=secret_key,
        paper=paper,
        base_url=base_url,
    )

    client = AlpacaClient(config)
    if not client.connect():
        raise LiveTradingError(
            "Failed to connect to Alpaca (REST trading API). Check api_key/secret, "
            "paper/live (PK*=paper, AK*=live), and network access. "
            "HTTP 400 'invalid syntax' on market-data WebSocket is usually a bad "
            "auth/subscribe JSON or symbol (use BTC/USD not BTC/USDT for crypto)."
        )
    return client


class QMTBridgeRestClient:
    """
    Lightweight HTTP wrapper around the QMT Bridge running on the Windows host.
    Used when the backend runs in Docker and cannot access xtquant directly.
    Implements the minimum interface needed by pending_order_worker for A-share orders.
    """

    def __init__(self, bridge_url: str, account_id: str, timeout: float = 15.0):
        self.bridge_url = bridge_url.rstrip("/")
        self.account_id = account_id
        self.timeout = timeout
        self.exchange_id = "qmt"

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        r = requests.get(f"{self.bridge_url}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: Optional[Dict] = None) -> Dict:
        r = requests.post(f"{self.bridge_url}{path}", json=body or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> Dict:
        r = requests.delete(f"{self.bridge_url}{path}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_status(self) -> Dict:
        resp = self._get("/qmt/status")
        return resp.get("data", {})

    def get_asset(self) -> Dict:
        resp = self._get("/qmt/asset")
        return resp.get("data", {})

    def get_positions(self) -> list:
        resp = self._get("/qmt/positions")
        return resp.get("data", [])

    def get_quote(self, symbol: str) -> Dict:
        resp = self._get("/qmt/quote", params={"symbol": symbol})
        return resp.get("data", {})

    def place_order(self, symbol: str, side: str, volume: int,
                    order_type: str = "market", price: float = 0.0,
                    comment: str = "ChanQuant") -> Dict:
        """
        Place an order via QMT Bridge.
        Args:
            symbol: Stock code (e.g., '600519.SH')
            side: 'buy' or 'sell'
            volume: Number of shares (must be positive integer, min 100 for A-share)
            order_type: 'market' or 'limit'
            price: Limit price (required for limit orders)
        Returns:
            Dict with order_id, filled, price, status
        """
        resp = self._post("/qmt/orders", {
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "order_type": order_type,
            "price": price,
            "comment": comment,
        })
        if resp.get("code", 0) != 0:
            raise LiveTradingError(f"QMT Bridge order failed: {resp.get('message', 'unknown error')}")
        return resp.get("data", {})

    def cancel_order(self, order_id: int) -> Dict:
        resp = self._delete(f"/qmt/orders/{order_id}")
        return resp.get("data", {})

    def query_order(self, order_id) -> Optional[Dict]:
        """Query a single order by ID. Returns None if not found."""
        try:
            r = requests.get(
                f"{self.bridge_url}/qmt/orders/{order_id}",
                timeout=self.timeout,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            resp = r.json()
            if resp.get("code", 0) != 0:
                return None
            return resp.get("data", {})
        except Exception:
            return None

    def get_orders(self) -> list:
        resp = self._get("/qmt/orders")
        return resp.get("data", [])

    def connect(self) -> bool:
        """Verify bridge connectivity."""
        try:
            status = self.get_status()
            return bool(status.get("connected"))
        except Exception:
            return False


def create_qmt_client(exchange_config: Dict[str, Any]):
    """
    Create QMT (miniQMT) client for A-share (China A-Stock) trading.

    On Linux/Docker, returns a QMTBridgeRestClient that proxies to the QMT Bridge
    running on the Windows host (port 5001). The Docker container cannot access
    miniQMT directly (xtquant uses Windows IPC).

    On Windows, uses the native xtquant SDK via QMTClient.

    exchange_config should contain:
    - qmt_path:        Path to miniQMT ``userdata_mini`` directory
    - qmt_account_id:  Funded securities account id (资金账号)
    - qmt_session_id:  Session id (int, default 123456)
    - qmt_username:    miniQMT login username (for reference)
    - qmt_password:    miniQMT login password (for reference)
    - qmt_lib_path:    Path to site-packages containing the xtquant package
    - qmt_bridge_url:  Bridge URL override (default: http://host.docker.internal:5001)
    """
    qmt_account_id = _get(exchange_config, "qmt_account_id", "qmtAccountId", "qmt_account")
    if not qmt_account_id:
        raise LiveTradingError(
            "QMT requires qmt_account_id (funded securities account id / 资金账号)."
        )

    # On Linux/Docker: use bridge HTTP API
    _is_linux = platform.system() != "Windows"
    if _is_linux:
        bridge_url = _get(exchange_config, "qmt_bridge_url", "qmtBridgeUrl") or \
            os.getenv("QMT_BRIDGE_URL", "http://host.docker.internal:5001")
        logger.info(f"[QMT] Using bridge client at {bridge_url} for account {qmt_account_id}")
        client = QMTBridgeRestClient(
            bridge_url=bridge_url,
            account_id=qmt_account_id,
        )
        # Verify bridge connectivity
        try:
            status = client.get_status()
            if not status.get("connected"):
                raise LiveTradingError(
                    f"QMT Bridge reports not connected at {bridge_url}. "
                    "Ensure miniQMT is running and logged in on the Windows host."
                )
            logger.info(f"[QMT] Bridge connected: {status}")
        except Exception as e:
            raise LiveTradingError(
                f"Cannot reach QMT Bridge at {bridge_url}: {e}. "
                "Ensure qmt_bridge.py is running on the Windows host (python scripts/qmt_bridge.py)."
            )
        return client

    # On Windows: use native xtquant SDK
    global QMTClient, QMTConfig

    if QMTClient is None or QMTConfig is None:
        try:
            from app.services.qmt_trading import QMTClient as _QMTClient, QMTConfig as _QMTConfig
            QMTClient = _QMTClient
            QMTConfig = _QMTConfig
        except ImportError:
            raise LiveTradingError(
                "QMT trading requires the xtquant package (shipped with miniQMT). "
                "Ensure miniQMT is installed and qmt_lib_path points to the "
                "site-packages directory containing the xtquant package."
            )

    qmt_path = _get(exchange_config, "qmt_path", "qmtPath")
    qmt_lib_path = _get(exchange_config, "qmt_lib_path", "qmtLibPath")

    session_id_raw = exchange_config.get("qmt_session_id", 123456)
    try:
        session_id = int(session_id_raw)
    except (TypeError, ValueError):
        session_id = 123456

    qmt_username = _get(exchange_config, "qmt_username", "qmtUsername")
    qmt_password = _get(exchange_config, "qmt_password", "qmtPassword")

    if not qmt_path:
        raise LiveTradingError(
            "QMT requires qmt_path (path to miniQMT userdata_mini directory)."
        )

    config = QMTConfig(
        qmt_path=qmt_path,
        qmt_account_id=qmt_account_id,
        qmt_session_id=session_id,
        qmt_username=qmt_username,
        qmt_password=qmt_password,
        qmt_lib_path=qmt_lib_path,
    )

    client = QMTClient(config)
    if not client.connect():
        raise LiveTradingError(
            "Failed to connect to miniQMT (xtquant). Please check:\n"
            "1. miniQMT client is running and logged in\n"
            "2. qmt_path points to the correct userdata_mini directory\n"
            "3. qmt_account_id is a valid funded account\n"
            "4. qmt_lib_path points to the site-packages with xtquant\n"
            "5. You are on Windows"
        )
    return client


def query_fee_rate(
    exchange_config: Dict[str, Any],
    symbol: str,
    market_type: str = "swap",
) -> Optional[Dict[str, float]]:
    """
    Best-effort: create a temporary client and query the account's fee tier
    for the given symbol.  Returns {"maker": 0.0002, "taker": 0.0005} or None.
    """
    try:
        client = create_client(exchange_config, market_type=market_type)
        return client.get_fee_rate(symbol, market_type=market_type)
    except Exception as e:
        logger.debug(f"query_fee_rate failed for {symbol}: {e}")
        return None


