"""
数据源工厂
根据市场类型返回对应的数据源
"""
import os
import threading
import time
from typing import Dict, List, Any, Optional

from app.data_sources.base import BaseDataSource
from app.data_sources.errors import UnsupportedMarketError
from app.utils.logger import get_logger
from app.utils.resource_guard import (
    ResourceExhaustedError,
    assert_fd_available,
    is_fd_exhaustion,
    mark_fd_exhausted,
)

logger = get_logger(__name__)


class QMTBridgeDataSource(BaseDataSource):
    """CNStock data source that fetches K-lines and quotes via the QMT Bridge HTTP API.

    Used when the backend runs in Docker (Linux) and cannot access xtquant directly.
    The QMT Bridge (scripts/qmt_bridge.py) runs on the Windows host and proxies
    requests to the miniQMT xtquant SDK.
    """

    name = "QMT-Bridge"

    def __init__(self, bridge_url: str = "http://host.docker.internal:5001", timeout: float = 15.0):
        self.bridge_url = bridge_url.rstrip("/")
        self.timeout = timeout

    def check_connection(self) -> bool:
        """Check if the bridge is reachable and QMT is connected."""
        try:
            import requests
            resp = requests.get(f"{self.bridge_url}/qmt/status", timeout=self.timeout)
            if resp.status_code != 200:
                return False
            data = resp.json().get("data", {})
            return bool(data.get("connected"))
        except Exception:
            return False

    def get_kline(self, symbol: str, timeframe: str, limit: int,
                  before_time: Optional[int] = None, after_time: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch K-lines via QMT Bridge /qmt/klines endpoint."""
        import requests
        # Map our timeframe format to bridge period
        tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1H": "1H", "4H": "1H",  # QMT doesn't have 4H, use 1H
            "1D": "1D", "1W": "1W",
        }
        period = tf_map.get(timeframe, timeframe)
        try:
            resp = requests.get(
                f"{self.bridge_url}/qmt/klines",
                params={"symbol": symbol, "period": period, "count": max(limit, 300)},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning("QMT Bridge kline HTTP %d for %s", resp.status_code, symbol)
                return []
            body = resp.json()
            if body.get("code", -1) != 0:
                logger.warning("QMT Bridge kline error: %s", body.get("message", ""))
                return []
            bars = body.get("data", {}).get("bars", [])
            if not bars:
                return []
            # Filter by time range if provided
            result = []
            for b in bars:
                t = int(b.get("time", 0))
                if before_time and t >= before_time:
                    continue
                if after_time and t < after_time:
                    continue
                result.append({
                    "time": t,
                    "open": float(b.get("open", 0)),
                    "high": float(b.get("high", 0)),
                    "low": float(b.get("low", 0)),
                    "close": float(b.get("close", 0)),
                    "volume": float(b.get("volume", 0)),
                })
            result.sort(key=lambda x: x["time"])
            return result
        except Exception as e:
            logger.warning("QMT Bridge kline fetch failed for %s: %s", symbol, e)
            return []

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fetch real-time quote via QMT Bridge /qmt/quote endpoint."""
        import requests
        try:
            resp = requests.get(
                f"{self.bridge_url}/qmt/quote",
                params={"symbol": symbol},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return {"last": 0, "symbol": symbol}
            body = resp.json()
            if body.get("code", -1) != 0:
                return {"last": 0, "symbol": symbol}
            d = body.get("data", {})
            return {
                "last": float(d.get("last_price", 0)),
                "open": float(d.get("open", 0)),
                "high": float(d.get("high", 0)),
                "low": float(d.get("low", 0)),
                "volume": int(d.get("volume", 0)),
                "symbol": symbol,
            }
        except Exception as e:
            logger.warning("QMT Bridge quote fetch failed for %s: %s", symbol, e)
            return {"last": 0, "symbol": symbol}


def _env_positive_int(key: str, default: int) -> int:
    try:
        value = int(os.getenv(key, str(default)))
        return value if value > 0 else default
    except Exception:
        return default

_MARKET_ALIASES: Dict[str, str] = {
    "crypto": "Crypto",
    "cryptocurrency": "Crypto",
    "forex": "Forex",
    "fx": "Forex",
    "usstock": "USStock",
    "us_stocks": "USStock",
    "usstocks": "USStock",
    "us_stock": "USStock",
    "stock": "USStock",
    "stocks": "USStock",
    "equity": "USStock",
    "equities": "USStock",
    "alpaca": "USStock",
    "ibkr": "USStock",
    "cnstock": "CNStock",
    "cn_stock": "CNStock",
    "ashare": "CNStock",
    "a_share": "CNStock",
    "astock": "CNStock",
    "a_stock": "CNStock",
    "cn": "CNStock",
    "china": "CNStock",
    "chinastock": "CNStock",
    "hkstock": "HKStock",
    "hk_stock": "HKStock",
    "hshare": "HKStock",
    "h_share": "HKStock",
    "hkshare": "HKStock",
    "hk_share": "HKStock",
    "hk": "HKStock",
    "hongkong": "HKStock",
    "futures": "Futures",
    "moex": "MOEX",
    "rustock": "MOEX",
    "rustocks": "MOEX",
    "russianstock": "MOEX",
    "russia": "MOEX",
}


class DataSourceFactory:
    """
    数据源工厂。
    K 线 / 报价 使用哪个接口完全由调用方传入的 market（与自选分类一致）决定，不做根据 symbol 字符串的推断。
    """
    
    _sources: Dict[str, BaseDataSource] = {}
    _noise_lock = threading.Lock()
    _noise_seen: Dict[str, tuple[float, int]] = {}
    _noise_interval_sec = _env_positive_int("LOG_DEDUPE_INTERVAL_SEC", 60)
    
    # Markets that pass through normalize_market unchanged.
    _CANONICAL_MARKETS = ("Crypto", "Forex", "Futures", "USStock", "CNStock", "HKStock", "MOEX")

    @classmethod
    def _log_limited(cls, level: str, key: str, message: str, *args: Any) -> None:
        """Log noisy market-data failures at most once per key per interval."""
        now = time.monotonic()
        with cls._noise_lock:
            last, suppressed = cls._noise_seen.get(key, (0.0, 0))
            if last > 0 and now - last < cls._noise_interval_sec:
                cls._noise_seen[key] = (last, suppressed + 1)
                return
            cls._noise_seen[key] = (now, 0)

        if suppressed:
            message = f"{message} (suppressed {suppressed} duplicate log(s))"
        log_fn = getattr(logger, level, logger.warning)
        log_fn(message, *args)

    @classmethod
    def normalize_market(cls, market: str) -> str:
        """
        Normalize a market category string.

        IMPORTANT: empty / unknown input used to silently degrade to "Crypto",
        which made stock symbols like TSLA quietly route to CCXT/Coinbase. We
        keep that fallback for backward compatibility (some callers still rely
        on it) but emit a loud WARNING so the misroute is no longer invisible.
        Always pass a real market category from the caller.
        """
        if not market:
            logger.warning(
                "DataSourceFactory.normalize_market(): empty market category — "
                "falling back to 'Crypto'. Caller MUST supply an explicit market "
                "(USStock / Forex / Futures / Crypto / CNStock / HKStock / MOEX). "
                "This fallback is deprecated and will become a hard error.",
                stack_info=False,
            )
            return "Crypto"
        raw = str(market).strip()
        if raw in cls._CANONICAL_MARKETS:
            return raw
        key = raw.lower().replace(" ", "").replace("-", "_")
        if key in _MARKET_ALIASES:
            return _MARKET_ALIASES[key]
        cls._log_limited(
            "warning",
            f"unknown-market:{raw}",
            "DataSourceFactory.normalize_market(): unknown market %r; "
            "passing through as-is; downstream get_source() will likely fail.",
            raw,
        )
        return raw

    @classmethod
    def get_source(cls, market: str) -> BaseDataSource:
        """
        获取指定市场的数据源
        
        Args:
            market: 市场类型 (Crypto, USStock, Forex, Futures)
            
        Returns:
            数据源实例
        """
        market = cls.normalize_market(market or "")
        if market not in cls._sources:
            cls._sources[market] = cls._create_source(market)
        return cls._sources[market]

    @classmethod
    def get_source_name(cls, market: str) -> str:
        """Return human-readable name of the data source for a market.

        Used by the strategy executor to log which concrete provider is used
        for K-line fetching, so failures are debuggable (e.g. QMT vs fallback).
        """
        try:
            m = cls.normalize_market(market or "")
            src = cls.get_source(m)
            return getattr(src, 'name', type(src).__name__)
        except Exception:
            return "unknown"

    @classmethod
    def get_data_source(cls, name: str) -> BaseDataSource:
        """
        Backward compatible alias used by older code paths.

        Some modules historically called `get_data_source("binance")` to fetch a crypto data source.
        In the localized Python backend we primarily use `get_source("Crypto")`.
        """
        key = (name or "").strip().lower()
        if key in ("crypto", "binance", "okx", "bybit", "bitget", "gate", "mexc", "kraken", "coinbase", "alpaca_crypto"):
            return cls.get_source("Crypto")
        if key in ("futures",):
            return cls.get_source("Futures")
        if key in ("forex", "fx", "mt5"):
            return cls.get_source("Forex")
        if key in ("usstock", "us_stocks", "stock", "stocks", "ibkr", "alpaca"):
            return cls.get_source("USStock")
        # Unknown alias — log and default to Crypto (legacy behavior). Callers
        # should migrate to the explicit `get_source(market)` API.
        logger.warning(
            "DataSourceFactory.get_data_source(%r): unknown alias — falling back "
            "to Crypto. Migrate caller to get_source(market) with an explicit "
            "market category.",
            name,
        )
        return cls.get_source("Crypto")
    
    @classmethod
    def _create_source(cls, market: str) -> BaseDataSource:
        """创建数据源实例"""
        if market == 'Crypto':
            from app.data_sources.crypto import CryptoDataSource
            return CryptoDataSource()
        elif market == 'CNStock':
            return cls._create_cn_stock_source()
        elif market == 'HKStock':
            from app.data_sources.hk_stock import HKStockDataSource
            return HKStockDataSource()
        elif market == 'USStock':
            from app.data_sources.us_stock import USStockDataSource
            return USStockDataSource()
        elif market == 'Forex':
            from app.data_sources.forex import ForexDataSource
            return ForexDataSource()
        elif market == 'Futures':
            from app.data_sources.futures import FuturesDataSource
            return FuturesDataSource()
        elif market == 'MOEX':
            from app.data_sources.moex import MOEXDataSource
            return MOEXDataSource()
        else:
            raise UnsupportedMarketError(market)

    @classmethod
    def _create_cn_stock_source(cls) -> BaseDataSource:
        """
        创建 A 股数据源，根据 CN_STOCK_DATA_SOURCE 配置选择实现。

        配置值:
          auto       — 优先 QMT（Windows）或 QMT Bridge（Docker），失败 fallback 到外部 API
          qmt        — 强制使用 QMT/xtdata（仅 Windows）
          bridge     — 强制使用 QMT Bridge HTTP 代理（Docker）
          twelvedata — 使用 TwelveData API
          tencent    — 使用腾讯财经
          default    — 使用内置多层 fallback（原始 CNStockDataSource）
        """
        import os
        import sys

        mode = (os.environ.get('CN_STOCK_DATA_SOURCE', 'auto') or 'auto').strip().lower()
        logger.info("CNStock data source: mode=%s (env CN_STOCK_DATA_SOURCE)", mode)

        if mode == 'qmt':
            src = cls._try_create_qmt_source(required=True)
            logger.info("CNStock data source: forced QMT (xtdata) → %s", getattr(src, 'name', type(src).__name__))
            return src

        if mode == 'bridge':
            bridge_url = os.getenv('QMT_BRIDGE_URL', 'http://host.docker.internal:5001')
            logger.info("CNStock data source: forced QMT Bridge (url=%s)", bridge_url)
            return QMTBridgeDataSource(bridge_url=bridge_url)

        if mode == 'twelvedata' or mode == 'tencent' or mode == 'default':
            from app.data_sources.cn_stock import CNStockDataSource
            logger.info("CNStock data source: using %s mode (CNStockDataSource)", mode)
            return CNStockDataSource()

        # mode == 'auto': 
        # 1) On Windows: try native QMT (xtdata) first
        # 2) On Linux/Docker: try QMT Bridge HTTP proxy
        # 3) Fallback to CNStockDataSource
        qmt_source = cls._try_create_qmt_source(required=False)
        if qmt_source is not None:
            logger.info("CNStock data source: auto mode → QMT (xtdata) selected ✓")
            return qmt_source

        # Docker/Linux: try QMT Bridge
        bridge_url = os.getenv('QMT_BRIDGE_URL', '')
        if not bridge_url and sys.platform != 'win32':
            bridge_url = 'http://host.docker.internal:5001'
        if bridge_url:
            bridge_src = cls._try_create_bridge_source(bridge_url)
            if bridge_src is not None:
                logger.info("CNStock data source: auto mode → QMT Bridge selected ✓ (url=%s)", bridge_url)
                return bridge_src

        logger.warning(
            "CNStock data source: auto mode → QMT unavailable, falling back to CNStockDataSource. "
            "Set CN_STOCK_DATA_SOURCE=qmt in .env to force QMT and see the import error."
        )
        from app.data_sources.cn_stock import CNStockDataSource
        return CNStockDataSource()

    @staticmethod
    def _try_create_bridge_source(bridge_url: str):
        """Try to create a QMTBridgeDataSource, returns None if bridge is unreachable."""
        try:
            src = QMTBridgeDataSource(bridge_url=bridge_url)
            # Verify connectivity
            if src.check_connection():
                return src
            logger.warning("QMT Bridge at %s is not reachable or not connected", bridge_url)
            return None
        except Exception as e:
            logger.warning("QMT Bridge at %s init failed: %s", bridge_url, e)
            return None

    @staticmethod
    def _try_create_qmt_source(required: bool = False):
        """
        尝试创建 QMTDataSource。失败时返回 None（非 required 模式）。
        """
        import os
        import sys

        lib_path = (os.environ.get('QMT_LIB_PATH', '') or '').strip()

        # QMT 仅支持 Windows
        if sys.platform != 'win32':
            if required:
                raise RuntimeError("QMT data source is only available on Windows")
            logger.debug("QMT data source: not Windows, skipping")
            return None

        # 检查 xtquant 是否可导入
        try:
            _test_path = lib_path if lib_path else None
            if _test_path and _test_path not in sys.path:
                sys.path.insert(0, _test_path)
            from xtquant import xtdata  # noqa: F401
        except ImportError as e:
            if required:
                raise RuntimeError(
                    f"xtquant is not available. Install miniQMT and set QMT_LIB_PATH "
                    f"to the site-packages directory containing xtquant. Error: {e}"
                )
            logger.warning(
                "QMT data source: xtquant import failed (lib_path=%r): %s",
                lib_path, e,
            )
            return None

        from app.data_sources.qmt_data import QMTDataSource
        logger.info("QMT data source: xtquant imported OK (lib_path=%r)", lib_path)
        return QMTDataSource(lib_path=lib_path)
    
    @classmethod
    def get_kline(
        cls,
        market: str,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
        exchange_id: Optional[str] = None,
        market_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取K线数据的便捷方法
        
        Args:
            market: 市场类型
            symbol: 交易对/股票代码
            timeframe: 时间周期
            limit: 数据条数
            before_time: 获取此时间之前的数据
            after_time: 可选，Unix 秒，K 线 time 需 >= 此值（回测左边界）
            exchange_id: 加密货币运行中策略 — 与策略绑定的交易所 (binance/okx/...)
            market_type: 加密货币运行中策略 — spot 或 swap
            
        Returns:
            K线数据列表
        """
        m = cls.normalize_market(market or "")
        try:
            assert_fd_available(f"market-data kline {m}:{symbol}")
            source = cls._resolve_source(m, exchange_id=exchange_id, market_type=market_type)
            klines = source.get_kline(symbol, timeframe, limit, before_time, after_time)
            
            klines.sort(key=lambda x: x['time'])
            
            return klines
        except ResourceExhaustedError as e:
            cls._log_limited(
                "error",
                f"fd-cooldown:kline:{m}:{symbol}",
                "Skipped K-lines %s:%s because resource guard is active: %s",
                market,
                symbol,
                str(e),
            )
            return []
        except Exception as e:
            if is_fd_exhaustion(e):
                mark_fd_exhausted(e)
            cls._log_limited(
                "error",
                f"kline:{m}:{symbol}:{type(e).__name__}:{str(e)[:160]}",
                "Failed to fetch K-lines %s:%s (normalized=%s) - %s",
                market,
                symbol,
                m,
                str(e),
            )
            return []
    
    @classmethod
    def _resolve_source(
        cls,
        market: str,
        *,
        exchange_id: Optional[str] = None,
        market_type: Optional[str] = None,
    ) -> BaseDataSource:
        """Pick data source; crypto live strategies may scope to execution exchange."""
        ex = (exchange_id or "").strip().lower()
        mt = (market_type or "").strip().lower()
        if mt in ("futures", "future", "perp", "perpetual"):
            mt = "swap"
        if market == "Crypto" and (ex or mt == "swap"):
            from app.data_sources.crypto import CryptoDataSource

            return CryptoDataSource.for_exchange(ex, mt or "swap")
        return cls.get_source(market)

    @classmethod
    def get_ticker(cls, market: str, symbol: str, exchange_id: Optional[str] = None, market_type: Optional[str] = None) -> Dict[str, Any]:
        """
        获取实时报价的便捷方法
        
        Args:
            market: 市场类型
            symbol: 交易对/股票代码
            exchange_id: 加密货币运行中策略 — 与策略绑定的交易所
            market_type: 加密货币运行中策略 — spot 或 swap
            
        Returns:
            实时报价数据: {
                'last': 最新价,
                'change': 涨跌额,
                'changePercent': 涨跌幅,
                ...
            }
        """
        m = cls.normalize_market(market or "")
        try:
            assert_fd_available(f"market-data ticker {m}:{symbol}")
            source = cls._resolve_source(m, exchange_id=exchange_id, market_type=market_type)
            return source.get_ticker(symbol)
        except ResourceExhaustedError as e:
            cls._log_limited(
                "error",
                f"fd-cooldown:ticker:{m}:{symbol}",
                "Skipped ticker %s:%s because resource guard is active: %s",
                market,
                symbol,
                str(e),
            )
            return {'last': 0, 'symbol': symbol}
        except NotImplementedError:
            cls._log_limited(
                "warning",
                f"ticker-not-implemented:{m}",
                "get_ticker not implemented for market: %s",
                market,
            )
            return {'last': 0, 'symbol': symbol}
        except Exception as e:
            if is_fd_exhaustion(e):
                mark_fd_exhausted(e)
            cls._log_limited(
                "error",
                f"ticker:{m}:{symbol}:{type(e).__name__}:{str(e)[:160]}",
                "Failed to fetch ticker %s:%s - %s",
                market,
                symbol,
                str(e),
            )
            return {'last': 0, 'symbol': symbol}

