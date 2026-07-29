"""Unit tests for persistent kline cache helpers and store/get semantics."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from app.services.kline_cache_db import (
    CACHE_COVERAGE_THRESHOLD,
    drop_unclosed_candles,
    expected_bar_count,
    get_cached_kline,
    has_candle_gaps,
    store_kline,
)


def test_coverage_threshold_near_complete():
    assert CACHE_COVERAGE_THRESHOLD >= 0.999


def test_has_candle_gaps_detects_hole():
    tf = 3600
    base = 1_700_000_000
    continuous = [base, base + tf, base + 2 * tf]
    assert not has_candle_gaps(continuous, tf, start_ts=base, end_ts=base + 2 * tf)

    with_hole = [base, base + tf, base + 3 * tf]  # missing base+2tf
    assert has_candle_gaps(with_hole, tf, start_ts=base, end_ts=base + 3 * tf)


def test_has_candle_gaps_edge_miss():
    tf = 3600
    base = 1_700_000_000
    # Starts one bar late relative to requested start
    late = [base + 2 * tf, base + 3 * tf]
    assert has_candle_gaps(late, tf, start_ts=base, end_ts=base + 3 * tf)


def test_drop_unclosed_candles_skips_forming_bar():
    tf = 3600
    now = 1_700_003_600  # exactly one bar after base
    base = now - tf  # open == now - tf → still treated as unclosed (>=)
    older = now - 2 * tf
    keep = drop_unclosed_candles([older, base, now], tf, now_ts=now)
    assert keep == [0]  # only fully closed older bar


def test_expected_bar_count():
    assert expected_bar_count(0, 3600, 3600) == 2
    assert expected_bar_count(0, 7200, 3600) == 3
    assert expected_bar_count(0, 0, 3600) == 1


def _fake_df(times, closes=None):
    closes = closes or [100.0 + i for i in range(len(times))]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1.0] * len(times),
        },
        index=pd.to_datetime(times, utc=True),
    )


def test_store_kline_skips_unclosed(monkeypatch):
    """Unclosed trailing bar must not be written (avoids DO NOTHING pin)."""
    tf = 3600
    now = int(datetime(2025, 7, 1, 12, 30, tzinfo=timezone.utc).timestamp())
    t0 = now - 2 * tf
    t1 = now - tf  # forming / just-boundary — skipped
    df = _fake_df(
        [datetime.fromtimestamp(t0, tz=timezone.utc),
         datetime.fromtimestamp(t1, tz=timezone.utc)],
    )

    captured = {}

    def fake_execute_values(cur, sql, rows, page_size=1000):
        captured["rows"] = list(rows)

    raw = MagicMock()
    wrapper = MagicMock()
    wrapper._cursor = raw
    conn = MagicMock()
    conn.cursor.return_value = wrapper
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch("app.services.kline_cache_db.get_db_connection", return_value=conn), \
         patch("app.services.kline_cache_db.execute_values", side_effect=fake_execute_values):
        store_kline(
            "Crypto", "BTC/USDT", "1H", "", "", df,
            tf_seconds=tf, now_ts=now,
        )

    assert "rows" in captured
    assert len(captured["rows"]) == 1
    assert captured["rows"][0][5] == t0


def test_store_kline_uses_raw_cursor():
    """execute_values must receive the raw psycopg2 cursor, not PostgresCursor."""
    tf = 3600
    now = int(datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc).timestamp())
    t0 = now - 3 * tf
    df = _fake_df([datetime.fromtimestamp(t0, tz=timezone.utc)])

    seen = {}

    def fake_execute_values(cur, sql, rows, page_size=1000):
        seen["cur"] = cur

    raw = object()
    wrapper = MagicMock()
    wrapper._cursor = raw
    conn = MagicMock()
    conn.cursor.return_value = wrapper
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch("app.services.kline_cache_db.get_db_connection", return_value=conn), \
         patch("app.services.kline_cache_db.execute_values", side_effect=fake_execute_values):
        store_kline(
            "Crypto", "BTC/USDT", "1H", "", "", df,
            tf_seconds=tf, now_ts=now,
        )

    assert seen.get("cur") is raw


def test_get_cached_kline_gap_is_miss():
    tf = 3600
    base = int(datetime(2025, 7, 1, tzinfo=timezone.utc).timestamp())
    # Hole in the middle: 0h, 1h, 3h (missing 2h)
    rows = [
        {"candle_ts": base, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"candle_ts": base + tf, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"candle_ts": base + 3 * tf, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ]
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch("app.services.kline_cache_db.get_db_connection", return_value=conn):
        hit = get_cached_kline(
            "Crypto", "BTC/USDT", "1H", "", "",
            base, base + 3 * tf, tf,
        )
    assert hit is None


def test_get_cached_kline_continuous_is_hit():
    tf = 3600
    base = int(datetime(2025, 7, 1, tzinfo=timezone.utc).timestamp())
    end = base + 2 * tf
    rows = [
        {"candle_ts": base + i * tf, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        for i in range(3)
    ]
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch("app.services.kline_cache_db.get_db_connection", return_value=conn):
        hit = get_cached_kline(
            "Crypto", "BTC/USDT", "1H", "", "",
            base, end, tf,
        )
    assert hit is not None
    assert len(hit) == 3


def test_hit_window_filter_aligns_with_request():
    """Simulate backtest hit-path filter: padded cache → trim to [start,end]."""
    idx = pd.to_datetime(
        [
            "2025-07-01 00:00:00",
            "2025-07-01 01:00:00",
            "2025-07-01 02:00:00",
            "2025-07-01 03:00:00",
        ],
    )
    db_cached = pd.DataFrame(
        {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        index=idx,
    )
    start_date = datetime(2025, 7, 1, 1, 0, 0)
    end_date = datetime(2025, 7, 1, 2, 0, 0)
    rs = pd.Timestamp(start_date)
    re = pd.Timestamp(end_date)
    df_hit = db_cached[(db_cached.index >= rs) & (db_cached.index <= re)].copy()
    assert list(df_hit.index) == list(idx[1:3])
