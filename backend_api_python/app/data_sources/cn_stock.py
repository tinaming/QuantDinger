"""
中国A股数据源 — 多层 fallback

有 TWELVE_DATA_API_KEY:
  所有周期 → Twelve Data（主） → 腾讯日/周线 → yfinance → AkShare

无 API Key:
  分钟/小时 → yfinance → AkShare
  日/周线 → 腾讯 fqkline → yfinance → AkShare
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional

from app.data_sources.base import BaseDataSource
from app.data_sources.tencent import normalize_cn_code, fetch_quote, parse_quote_to_ticker, fetch_kline, tencent_kline_rows_to_dicts
from app.data_sources.asia_stock_kline import (
    normalize_chart_timeframe,
    fetch_twelvedata_klines,
    fetch_yfinance_klines,
    fetch_akshare_minute_klines,
    fetch_akshare_weekly_klines,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
        rows = fetch_twelvedata_klines(
            is_hk=False, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
        )
        if rows:
            return self.filter_and_limit(
                rows,
                limit=lim,
                before_time=before_time,
                after_time=after_time,
                truncate=(after_time is None),
            )

        # Tier 2: Tencent for daily/weekly (fast, free)
        if tf in ("1D", "1W"):
            tf_map = {"1D": "day", "1W": "week"}
            period = tf_map.get(tf, "day")
            raw_rows = fetch_kline(code, period=period, count=lim, adj="qfq")
            out = tencent_kline_rows_to_dicts(raw_rows)
            if out:
                return self.filter_and_limit(
                    out,
                    limit=lim,
                    before_time=before_time,
                    after_time=after_time,
                    truncate=(after_time is None),
                )

        # Tier 3: yfinance (works when Yahoo not rate-limited)
        rows = fetch_yfinance_klines(
            is_hk=False, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
        )
        if rows:
            return self.filter_and_limit(
                rows,
                limit=lim,
                before_time=before_time,
                after_time=after_time,
                truncate=(after_time is None),
            )

        # Tier 4: AkShare (fragile overseas, last resort)
        if tf in ("1m", "5m", "15m", "30m", "1H", "4H"):
            rows = fetch_akshare_minute_klines(
                is_hk=False, tencent_code=code, timeframe=tf, limit=lim, before_time=before_time
            )
        elif tf == "1W":
            rows = fetch_akshare_weekly_klines(
                is_hk=False, tencent_code=code, limit=lim, before_time=before_time
            )
        else:
            rows = []

        return self.filter_and_limit(
            rows,
            limit=lim,
            before_time=before_time,
            after_time=after_time,
            truncate=(after_time is None),
        )

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
            _rec("akshare", _check_akshare_available(), 4),
        ]
        total_errors = sum(s["recent_error_count"] for s in sources)
        return {
            "market": "CNStock",
            "sources": sources,
            "recent_error_count": total_errors,
        }
