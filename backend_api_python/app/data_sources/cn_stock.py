"""
中国A股数据源 — 多层 fallback

有 TWELVE_DATA_API_KEY:
  所有周期 → Twelve Data（主） → 腾讯（日/周 + 分钟 mkline） → yfinance → 东方财富直连 → AkShare

无 API Key:
  分钟/小时 → 腾讯 mkline → yfinance → 东方财富直连（带正确 headers） → AkShare
  日/周线 → 腾讯 fqkline → yfinance → 东方财富直连 → AkShare
"""

from __future__ import annotations

import threading
import time as _time

from typing import Dict, List, Any, Optional

from app.data_sources.base import BaseDataSource
from app.data_sources.tencent import (
    normalize_cn_code,
    fetch_quote,
    parse_quote_to_ticker,
    fetch_kline,
    fetch_minute_klines,
    tencent_kline_rows_to_dicts,
)
from app.data_sources.asia_stock_kline import (
    normalize_chart_timeframe,
    fetch_twelvedata_klines,
    fetch_yfinance_klines,
    fetch_eastmoney_klines,
    fetch_akshare_minute_klines,
    fetch_akshare_weekly_klines,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class _CircuitBreaker:
    """Simple circuit breaker for a single data source.

    States:
      closed    – normal operation, requests pass through.
      open      – tripped (consecutive failures >= threshold), requests blocked.
      half-open – recovery timeout elapsed, one probe request is allowed.
    """

    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.name = name
        self._threshold = failure_threshold
        self._timeout = recovery_timeout
        self._failures = 0
        self._state = "closed"          # closed | open | half-open
        self._last_failure_time: float = 0
        self._lock = threading.Lock()

    # -- public API --------------------------------------------------------

    def is_open(self) -> bool:
        """Return True when the breaker is blocking requests."""
        with self._lock:
            if self._state == "open":
                if _time.time() - self._last_failure_time > self._timeout:
                    # Recovery timeout elapsed → allow one probe request.
                    self._state = "half-open"
                    return False
                return True
            return False

    def record_success(self) -> None:
        """Reset breaker on successful call (closes from any state)."""
        with self._lock:
            self._failures = 0
            self._state = "closed"

    def record_failure(self) -> None:
        """Record a failure; trip the breaker when threshold is reached."""
        with self._lock:
            self._failures += 1
            self._last_failure_time = _time.time()
            if self._failures >= self._threshold:
                self._state = "open"

    @property
    def state(self) -> str:
        """Current state string (for diagnostics / status endpoint)."""
        # Trigger implicit open→half-open transition so status is accurate.
        if self._state == "open":
            self.is_open()
        return self._state


# Create one breaker per data source
_twelve_data_breaker = _CircuitBreaker("twelve_data")
_tencent_breaker = _CircuitBreaker("tencent")
_yfinance_breaker = _CircuitBreaker("yfinance")
_eastmoney_breaker = _CircuitBreaker("eastmoney")
_akshare_breaker = _CircuitBreaker("akshare")


def _check_akshare_available() -> bool:
    """Lightweight check: can akshare be imported?"""
    try:
        import akshare  # noqa: F401
        return True
    except Exception:
        return False


class CNStockDataSource(BaseDataSource):
    """A股数据源（TwelveData + Tencent + yfinance + AkShare）"""

    name = "CNStock/multi-source"

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        code = normalize_cn_code(symbol)
        parts = fetch_quote(code)
        if not parts:
            return {"last": 0, "symbol": code}
        t = parse_quote_to_ticker(parts)
        return {
            "last": t.get("last", 0),
            "change": t.get("change", 0),
            "changePercent": t.get("changePercent", 0),
            "high": t.get("high", 0),
            "low": t.get("low", 0),
            "open": t.get("open", 0),
            "previousClose": t.get("previousClose", 0),
            "name": t.get("name", ""),
            "symbol": code,
        }

    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        code = normalize_cn_code(symbol)
        tf = normalize_chart_timeframe(timeframe)
        lim = max(int(limit or 300), 1)

        # Tier 1: Twelve Data (paid, most reliable)
        if _twelve_data_breaker.is_open():
            logger.debug("Circuit breaker OPEN for twelve_data, skipping")
        else:
            try:
                rows = fetch_twelvedata_klines(
                    is_hk=False, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
                )
                if rows:
                    _twelve_data_breaker.record_success()
                    return self.filter_and_limit(
                        rows,
                        limit=lim,
                        before_time=before_time,
                        after_time=after_time,
                        truncate=(after_time is None),
                    )
            except Exception as e:
                _twelve_data_breaker.record_failure()
                logger.warning("twelve_data kline fetch failed: %s", e)

        # Tier 2: Tencent — daily/weekly via fqkline; minutes via mkline (free, no key)
        if tf in ("1D", "1W"):
            if _tencent_breaker.is_open():
                logger.debug("Circuit breaker OPEN for tencent, skipping")
            else:
                try:
                    tf_map = {"1D": "day", "1W": "week"}
                    period = tf_map.get(tf, "day")
                    raw_rows = fetch_kline(code, period=period, count=lim, adj="qfq")
                    out = tencent_kline_rows_to_dicts(raw_rows)
                    if out:
                        _tencent_breaker.record_success()
                        return self.filter_and_limit(
                            out,
                            limit=lim,
                            before_time=before_time,
                            after_time=after_time,
                            truncate=(after_time is None),
                        )
                except Exception as e:
                    _tencent_breaker.record_failure()
                    logger.warning("tencent kline fetch failed: %s", e)
        elif tf in ("1m", "3m", "5m", "15m", "30m", "1H", "4H"):
            if _tencent_breaker.is_open():
                logger.debug("Circuit breaker OPEN for tencent, skipping")
            else:
                try:
                    out = fetch_minute_klines(code, timeframe=tf, count=lim)
                    if out:
                        _tencent_breaker.record_success()
                        return self.filter_and_limit(
                            out,
                            limit=lim,
                            before_time=before_time,
                            after_time=after_time,
                            truncate=(after_time is None),
                        )
                except Exception as e:
                    _tencent_breaker.record_failure()
                    logger.warning("tencent minute kline fetch failed: %s", e)

        # Tier 3: yfinance (works when Yahoo not rate-limited)
        if _yfinance_breaker.is_open():
            logger.debug("Circuit breaker OPEN for yfinance, skipping")
        else:
            try:
                rows = fetch_yfinance_klines(
                    is_hk=False, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
                )
                if rows:
                    _yfinance_breaker.record_success()
                    return self.filter_and_limit(
                        rows,
                        limit=lim,
                        before_time=before_time,
                        after_time=after_time,
                        truncate=(after_time is None),
                    )
            except Exception as e:
                _yfinance_breaker.record_failure()
                logger.warning("yfinance kline fetch failed: %s", e)

        # Tier 3.5: East Money direct API (sends proper headers — fixes Docker RemoteDisconnected)
        if _eastmoney_breaker.is_open():
            logger.debug("Circuit breaker OPEN for eastmoney, skipping")
        else:
            try:
                rows = fetch_eastmoney_klines(
                    is_hk=False, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
                )
                if rows:
                    _eastmoney_breaker.record_success()
                    return self.filter_and_limit(
                        rows,
                        limit=lim,
                        before_time=before_time,
                        after_time=after_time,
                        truncate=(after_time is None),
                    )
            except Exception as e:
                _eastmoney_breaker.record_failure()
                logger.warning("eastmoney direct kline fetch failed: %s", e)

        # Tier 4: AkShare (fragile overseas, last resort)
        rows: List[Dict[str, Any]] = []
        if _akshare_breaker.is_open():
            logger.debug("Circuit breaker OPEN for akshare, skipping")
        else:
            try:
                if tf in ("1m", "5m", "15m", "30m", "1H", "4H"):
                    rows = fetch_akshare_minute_klines(
                        is_hk=False, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
                    )
                elif tf == "1W":
                    rows = fetch_akshare_weekly_klines(
                        is_hk=False, tencent_code=code, limit=lim, before_time=before_time
                    )
                if rows:
                    _akshare_breaker.record_success()
            except Exception as e:
                _akshare_breaker.record_failure()
                logger.warning("akshare kline fetch failed: %s", e)
                rows = []

        result = self.filter_and_limit(
            rows,
            limit=lim,
            before_time=before_time,
            after_time=after_time,
            truncate=(after_time is None),
        )
        if not result:
            logger.warning(
                "CNStock/multi-source: all providers returned 0 bars for %s tf=%s "
                "(configure TWELVE_DATA_API_KEY, ensure QMT/Bridge is up, or check "
                "Tencent/yfinance/AkShare reachability)",
                code,
                tf,
            )
        return result

    @classmethod
    def get_data_source_status(cls) -> dict:
        """Return CN stock data-source availability summary.

        Response shape::

            {
              "market": "CNStock",
              "sources": [
                {"provider": "twelvedata", "enabled": True,
                 "tier": 1, "last_success_iso": "...", "recent_error_count": 0},
                ...
              ],
            }
        """
        import os

        # -- Try to pull AvailabilityRecord from registry (graceful fallback) --
        _registry = None
        try:
            from app.data_sources.registry import get_registry  # type: ignore
            _registry = get_registry()
        except Exception:
            pass

        def _rec(provider: str, enabled: bool, tier: int) -> dict:
            item = _registry.get(provider) if _registry else None
            return {
                "provider": provider,
                "enabled": enabled,
                "tier": tier,
                "last_success_iso": (
                    item.last_success.isoformat()
                    if item and item.last_success
                    else None
                ),
                "recent_error_count": (
                    item.recent_error_count if item else 0
                ),
            }

        sources = [
            _rec("twelvedata", bool(os.environ.get("TWELVE_DATA_API_KEY")), 1),
            _rec("tencent", True, 2),
            _rec("yfinance", True, 3),
            _rec("eastmoney", True, 4),
            _rec("akshare", _check_akshare_available(), 5),
        ]
        total_errors = sum(s["recent_error_count"] for s in sources)
        return {
            "market": "CNStock",
            "sources": sources,
            "recent_error_count": total_errors,
        }
