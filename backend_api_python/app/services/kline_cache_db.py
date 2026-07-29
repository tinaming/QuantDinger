"""
Persistent K-line cache backed by PostgreSQL.

Historical OHLCV candles are immutable once closed, so we store them in the
database forever.  This eliminates repeated CCXT API calls for the same data
and avoids exchange rate limits during batch backtests.

Usage (internal, called by BacktestService._fetch_kline_data)::

    from app.services.kline_cache_db import get_cached_kline, store_kline

    df = get_cached_kline(market, symbol, timeframe, market_type, exchange_id,
                          start_ts, end_ts, tf_seconds)
    if df is not None:
        return df  # cache hit

    df = fetch_from_exchange(...)
    store_kline(market, symbol, timeframe, market_type, exchange_id, df)
    return df
"""

from __future__ import annotations

import time
from typing import Optional, Sequence

import pandas as pd
from psycopg2.extras import execute_values

from app.data_sources.base import TIMEFRAME_SECONDS
from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Require near-complete continuous coverage for a DB cache hit.
# Silent partial hits (e.g. 90%) are not allowed — gaps must miss and refetch.
# Strict uniform-grid checks apply to Crypto (24/7); other markets use edge coverage.
CACHE_COVERAGE_THRESHOLD = 0.999

# Adjacent candle open times must be exactly one bar apart (crypto 24/7 grid).
# Allow 1s slack for integer rounding; any larger gap is treated as a hole.
_GAP_SLACK_SECONDS = 1


def _is_crypto_market(market: str) -> bool:
    return str(market or "").strip().lower() in {"crypto", "cryptocurrency"}


def _resolve_tf_seconds(timeframe: str, tf_seconds: Optional[int] = None) -> int:
    if tf_seconds and tf_seconds > 0:
        return int(tf_seconds)
    return int(TIMEFRAME_SECONDS.get(timeframe, 3600))


def has_candle_gaps(
    candle_ts: Sequence[int],
    tf_seconds: int,
    *,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    max_internal_gap: Optional[int] = None,
) -> bool:
    """Return True if the series has a substantial hole vs a bar grid.

    Checks:
    - Adjacent open times differ by more than ``max_internal_gap``
      (default: ``tf_seconds`` + slack — uniform crypto grid)
    - Optional: series does not start/end within one bar of ``[start_ts, end_ts]``
    """
    if tf_seconds <= 0:
        return True
    if not candle_ts:
        return True

    limit = (
        int(max_internal_gap)
        if max_internal_gap is not None
        else tf_seconds + _GAP_SLACK_SECONDS
    )
    ts = sorted(int(t) for t in candle_ts)
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > limit:
            return True

    if start_ts is not None:
        if ts[0] - int(start_ts) > tf_seconds + _GAP_SLACK_SECONDS:
            return True
    if end_ts is not None:
        if int(end_ts) - ts[-1] > tf_seconds + _GAP_SLACK_SECONDS:
            return True
    return False


def expected_bar_count(start_ts: int, end_ts: int, tf_seconds: int) -> int:
    """Expected candle count on a uniform grid over inclusive ``[start_ts, end_ts]``.

    Assumes candle opens fall on a ``tf_seconds`` grid and both bounds are
    aligned (or close). Under-counting is unsafe (false HIT); we use
    ``(end - start) // tf + 1`` which matches aligned inclusive endpoints.
    """
    if tf_seconds <= 0 or end_ts < start_ts:
        return 1
    return max(1, (int(end_ts) - int(start_ts)) // tf_seconds + 1)


def drop_unclosed_candles(
    candle_ts: Sequence[int],
    tf_seconds: int,
    *,
    now_ts: Optional[int] = None,
) -> list[int]:
    """Return indices of rows whose candle is fully closed (open + tf <= now)."""
    now = int(now_ts if now_ts is not None else time.time())
    keep: list[int] = []
    for i, ts in enumerate(candle_ts):
        # Candle with open time ts closes at ts + tf_seconds.
        # Skip if it has not closed yet (open >= now - tf).
        if int(ts) >= now - tf_seconds:
            continue
        keep.append(i)
    return keep


def get_cached_kline(
    market: str,
    symbol: str,
    timeframe: str,
    market_type: str,
    exchange_id: str,
    start_ts: int,
    end_ts: int,
    tf_seconds: int,
) -> Optional[pd.DataFrame]:
    """Try to retrieve kline data from the persistent DB cache.

    ``start_ts`` / ``end_ts`` must be the real request window (same bounds used
    for the final backtest filter), not an exchange fetch pad. Coverage and gap
    checks use this window as the denominator.

    Returns a DataFrame indexed by time, or None if the cache doesn't have
    continuous coverage of the requested range.
    """
    mt = market_type or ""
    ex = exchange_id or ""
    tf_sec = _resolve_tf_seconds(timeframe, tf_seconds)

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT candle_ts, open, high, low, close, volume
                FROM kline_cache
                WHERE market = %s AND symbol = %s AND timeframe = %s
                  AND market_type = %s AND exchange_id = %s
                  AND candle_ts >= %s AND candle_ts <= %s
                ORDER BY candle_ts ASC
                """,
                (market, symbol, timeframe, mt, ex, start_ts, end_ts),
            )
            rows = cur.fetchall()

        if not rows:
            return None

        # Build DataFrame
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["candle_ts"], unit="s")
        df = df.set_index("time")
        candle_ts_list = [int(r["candle_ts"]) for r in rows]
        df = df[["open", "high", "low", "close", "volume"]]
        df = df.sort_index()

        if df.empty:
            return None

        # Continuous coverage: crypto uses a 24/7 uniform grid (near-100% bar
        # count + no adjacent gaps). Other markets only require edge coverage
        # and no absurd internal holes (session calendars vary).
        expected_bars = expected_bar_count(start_ts, end_ts, tf_sec)
        coverage = len(df) / expected_bars
        crypto = _is_crypto_market(market)

        if crypto and coverage < CACHE_COVERAGE_THRESHOLD:
            logger.debug(
                "DB kline cache partial hit for %s %s %s: %d/%d bars (%.1f%%), "
                "below threshold %.1f%% — will fetch from exchange",
                symbol, timeframe, market,
                len(df), expected_bars, coverage * 100,
                CACHE_COVERAGE_THRESHOLD * 100,
            )
            return None

        max_internal = None if crypto else max(tf_sec * 3, 4 * 86400)
        if has_candle_gaps(
            candle_ts_list,
            tf_sec,
            start_ts=start_ts,
            end_ts=end_ts,
            max_internal_gap=max_internal,
        ):
            logger.debug(
                "DB kline cache has gaps for %s %s %s (%d bars in [%s,%s]) "
                "— will fetch from exchange",
                symbol, timeframe, market, len(df), start_ts, end_ts,
            )
            return None

        logger.info(
            "DB kline cache HIT for %s %s %s: %d candles (%.1f%% coverage)",
            symbol, timeframe, market, len(df), coverage * 100,
        )
        return df

    except Exception as exc:
        logger.warning("DB kline cache read failed for %s %s: %s", symbol, timeframe, exc)
        return None


def store_kline(
    market: str,
    symbol: str,
    timeframe: str,
    market_type: str,
    exchange_id: str,
    df: pd.DataFrame,
    *,
    tf_seconds: Optional[int] = None,
    now_ts: Optional[int] = None,
) -> None:
    """Store kline DataFrame into the persistent DB cache.

    Uses ON CONFLICT DO NOTHING so repeated calls for the same *closed* data
    are idempotent. Possibly-unclosed trailing candles are skipped so they are
    not pinned forever by DO NOTHING.
    """
    if df is None or df.empty:
        return

    mt = market_type or ""
    ex = exchange_id or ""
    tf_sec = _resolve_tf_seconds(timeframe, tf_seconds)

    # Extract timestamp as Unix seconds.
    # Normalise to UTC first, then strip timezone before converting to seconds.
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        ts_series = idx.astype("datetime64[s]").astype("int64")
    else:
        if "time" in df.columns:
            ts = pd.to_datetime(df["time"])
            if ts.dt.tz is not None:
                ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
            ts_series = ts.astype("datetime64[s]").astype("int64")
        else:
            logger.warning("Cannot determine timestamp column for kline cache store")
            return

    # Build rows for batch insert
    o = df["open"] if "open" in df.columns else None
    h = df["high"] if "high" in df.columns else None
    l = df["low"] if "low" in df.columns else None
    c = df["close"] if "close" in df.columns else None
    v = df["volume"] if "volume" in df.columns else None

    if o is None or h is None or l is None or c is None:
        logger.warning("Missing OHLC columns in kline DataFrame, skipping cache store")
        return

    # Convert ts_series to a plain list so we can iterate safely.
    ts_list = [int(t) for t in list(ts_series)]
    o_list = list(o)
    h_list = list(h)
    l_list = list(l)
    c_list = list(c)
    v_list = list(v) if v is not None else [0.0] * len(df)

    keep_idx = drop_unclosed_candles(ts_list, tf_sec, now_ts=now_ts)
    skipped = len(ts_list) - len(keep_idx)
    if skipped:
        logger.debug(
            "Skipping %d unclosed candle(s) for %s %s (tf=%ss)",
            skipped, symbol, timeframe, tf_sec,
        )

    rows = []
    for i in keep_idx:
        try:
            rows.append((
                market, symbol, timeframe, mt, ex, ts_list[i],
                float(o_list[i]), float(h_list[i]), float(l_list[i]),
                float(c_list[i]), float(v_list[i]),
            ))
        except Exception:
            continue

    if not rows:
        return

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            # Use the raw psycopg2 cursor: PostgresCursor.execute auto-appends
            # RETURNING id, which breaks multi-row execute_values paging.
            raw_cur = getattr(cur, "_cursor", cur)
            execute_values(
                raw_cur,
                """
                INSERT INTO kline_cache
                    (market, symbol, timeframe, market_type, exchange_id,
                     candle_ts, open, high, low, close, volume)
                VALUES %s
                ON CONFLICT (market, symbol, timeframe, market_type, exchange_id, candle_ts)
                DO NOTHING
                """,
                rows,
                page_size=1000,
            )
            conn.commit()
        logger.info(
            "Stored %d candles to kline_cache for %s %s %s",
            len(rows), symbol, timeframe, market,
        )
    except Exception as exc:
        logger.warning("DB kline cache write failed for %s %s: %s", symbol, timeframe, exc)
