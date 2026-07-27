"""A-share (CNStock) batch data fetching for ChanQuant.

Uses AkShare's bulk market snapshot APIs to fetch data for all A-shares
in 1-2 requests instead of 5000+ individual requests.
"""
from __future__ import annotations

import threading
import time
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_AKSHARE_AVAILABLE = False
try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
except ImportError:
    logger.debug("akshare not available for batch fetching")


class CNStockBatchFetcher:
    _SNAPSHOT_TTL = 30  # seconds

    def __init__(self):
        self._snapshot_cache: Optional[list] = None
        self._snapshot_ts: float = 0
        self._lock = threading.Lock()

    def get_market_snapshot(self) -> List[Dict]:
        """Get real-time snapshot for all A-shares (cached for 30s)."""
        if not _AKSHARE_AVAILABLE:
            return []
        with self._lock:
            now = time.time()
            if self._snapshot_cache and (now - self._snapshot_ts) < self._SNAPSHOT_TTL:
                return self._snapshot_cache
            try:
                df = ak.stock_zh_a_spot_em()
                self._snapshot_cache = df.to_dict("records")
                self._snapshot_ts = now
                return self._snapshot_cache
            except Exception as e:
                logger.warning(f"Failed to fetch A-share snapshot: {e}")
                return self._snapshot_cache or []

    def get_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get current quotes for a list of symbols from cached snapshot."""
        snapshot = self.get_market_snapshot()
        if not snapshot:
            return {}
        result = {}
        symbol_set = set(symbols)
        for row in snapshot:
            code = str(row.get("代码", ""))
            if code in symbol_set:
                result[code] = {
                    "symbol": code,
                    "name": row.get("名称", ""),
                    "price": row.get("最新价", 0),
                    "change_pct": row.get("涨跌幅", 0),
                    "volume": row.get("成交量", 0),
                    "amount": row.get("成交额", 0),
                }
        return result

    def is_available(self) -> bool:
        return _AKSHARE_AVAILABLE


# Module-level singleton
_batch_fetcher: Optional[CNStockBatchFetcher] = None


def get_batch_fetcher() -> CNStockBatchFetcher:
    global _batch_fetcher
    if _batch_fetcher is None:
        _batch_fetcher = CNStockBatchFetcher()
    return _batch_fetcher
