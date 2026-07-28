"""
CZSC Market Opportunity Scanner
================================
Scans multiple symbols × timeframes for active CZSC v3 signals.
Focuses on last-N-bar signal detection to simulate live trading windows.

Usage:
    cd backend_api_python
    python scripts/scan_czsc_opportunities.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import ccxt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Bootstrap: make app modules importable from scripts/
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.czsc_bridge import compute_czsc_features, is_czsc_enabled

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOLS: List[str] = [
    # Mainstream
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'DOGE/USDT',
    # Mid-cap
    'TIA/USDT', 'NEAR/USDT', 'WIF/USDT', 'FET/USDT', 'VET/USDT',
    'ARB/USDT', 'FIL/USDT', 'STRK/USDT', 'SEI/USDT', 'PYTH/USDT',
    'IMX/USDT', 'INJ/USDT', 'OP/USDT', 'JUP/USDT',
    # Other hot
    'PENDLE/USDT', 'ORDI/USDT', 'UNI/USDT', 'AVAX/USDT', 'LINK/USDT',
]

TIMEFRAMES: List[str] = ['1m', '5m', '15m']
KLINE_LIMIT: int = 2000  # bars per fetch
LAST_N_ACTIVE: int = 5   # "currently active" window
LAST_N_RECENT: int = 20  # "recently active" window

# ---------------------------------------------------------------------------
# Exchange connection
# ---------------------------------------------------------------------------

def make_exchange() -> ccxt.Exchange:
    """Create a Gate.io exchange instance (public data, no key required)."""
    exchange = ccxt.gate({
        'enableRateLimit': True,
        'timeout': 30000,
        'options': {'defaultType': 'spot'},
    })
    return exchange


def fetch_klines(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    limit: int = KLINE_LIMIT,
) -> Optional[pd.DataFrame]:
    """Fetch OHLCV klines and return a DataFrame suitable for czsc."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 50:
            return None
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        # Build timezone-naive datetime for czsc compatibility
        dts = pd.to_datetime(df['time'], unit='ms', utc=True)
        if hasattr(dts.dtype, 'tz') and dts.dt.tz is not None:
            dts = dts.dt.tz_convert(None)
        df['dt'] = dts.values  # naive datetime64 column
        df.drop(columns=['time'], inplace=True)
        df['vol'] = df['volume']
        return df
    except Exception as e:
        print(f"  [WARN] fetch failed for {symbol} {timeframe}: {e}")
        return None


# ---------------------------------------------------------------------------
# CZSC v3 signal logic (mirrors test_czsc_strategy_generation.py lines 30–119)
# ---------------------------------------------------------------------------

def compute_signals(df: pd.DataFrame, trend_filter: int = 1) -> Dict[str, Any]:
    """Apply CZSC v3 signal logic and return summary stats."""
    if 'czsc_bi_dir' not in df.columns:
        return _empty_result()

    bi_dir = df['czsc_bi_dir']
    bi_dir_prev = bi_dir.shift(1).fillna(0)
    bs_type = df['czsc_bs_type'].fillna('')
    trend = df['czsc_trend'].fillna(0)

    # bi_flip_up: bi_dir transitions from non-1 to 1
    bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
    # bi_flip_dn: bi_dir transitions from non-(-1) to -1
    bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)

    has_buy_point = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
    has_sell_point = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')

    long_cond = bi_flip_up & (has_buy_point | (trend >= 0))
    short_cond = bi_flip_dn & (has_sell_point | (trend <= 0))

    if trend_filter == 1:
        long_cond = long_cond & (trend >= 0)
        short_cond = short_cond & (trend <= 0)

    # Edge extraction (first occurrence only)
    def edge(s: pd.Series) -> pd.Series:
        s = s.fillna(False).astype(bool)
        prev = s.shift(1).fillna(False).astype(int)
        return s & (prev == 0)

    long_edge = edge(long_cond)
    short_edge = edge(short_cond)

    # Signals
    open_long = long_edge
    open_short = short_edge

    n = len(df)
    # Total signals
    total_open_long = int(open_long.sum())
    total_open_short = int(open_short.sum())

    # Last-N-bar windows
    def sum_last(s: pd.Series, n_bars: int) -> int:
        return int(s.iloc[-n_bars:].sum()) if n_bars <= len(s) else int(s.sum())

    last5_long = sum_last(open_long, LAST_N_ACTIVE)
    last5_short = sum_last(open_short, LAST_N_ACTIVE)
    last20_long = sum_last(open_long, LAST_N_RECENT)
    last20_short = sum_last(open_short, LAST_N_RECENT)

    # Bi flip count and last flip position
    bi_flip_all = bi_flip_up | bi_flip_dn
    bi_flip_count = int(bi_flip_all.sum())
    # Last flip position (distance from end)
    flip_indices = np.where(bi_flip_all.values)[0]
    last_flip_pos = int(n - flip_indices[-1]) if len(flip_indices) > 0 else n

    # Current bi_dir value
    current_bi_dir = int(bi_dir.iloc[-1])

    # Current trend
    current_trend = int(trend.iloc[-1])

    return {
        'total_open_long': total_open_long,
        'total_open_short': total_open_short,
        'total_signals': total_open_long + total_open_short,
        'last5_long': last5_long,
        'last5_short': last5_short,
        'last5_total': last5_long + last5_short,
        'last20_long': last20_long,
        'last20_short': last20_short,
        'last20_total': last20_long + last20_short,
        'bi_flip_count': bi_flip_count,
        'last_flip_pos': last_flip_pos,
        'current_bi_dir': current_bi_dir,
        'current_trend': current_trend,
        'bar_count': n,
    }


def _empty_result() -> Dict[str, Any]:
    return {
        'total_open_long': 0, 'total_open_short': 0, 'total_signals': 0,
        'last5_long': 0, 'last5_short': 0, 'last5_total': 0,
        'last20_long': 0, 'last20_short': 0, 'last20_total': 0,
        'bi_flip_count': 0, 'last_flip_pos': -1,
        'current_bi_dir': 0, 'current_trend': 0, 'bar_count': 0,
        # V4 extras
        's1_breakout_long': 0, 's1_breakout_short': 0,
        's2_top_divergence': 0, 's2_bot_divergence': 0,
        's3_range_long': 0, 's3_range_short': 0,
    }


# ---------------------------------------------------------------------------
# CZSC v4 signal logic (multi-scenario)
# ---------------------------------------------------------------------------

def compute_v4_signals(
    df: pd.DataFrame,
    trend_filter: int = 1,
    vol_confirm: int = 1,
    center_narrow: int = 1,
    divergence_filter: int = 1,
    range_trade: int = 0,
) -> Dict[str, Any]:
    """Apply CZSC v4 multi-scenario signal logic and return summary stats."""
    if 'czsc_bi_dir' not in df.columns:
        return _empty_result()

    bi_dir = df['czsc_bi_dir']
    bi_dir_prev = bi_dir.shift(1).fillna(0)
    bs_type = df['czsc_bs_type'].fillna('')
    trend = df['czsc_trend'].fillna(0)
    zs_level = df['czsc_zs_level'].fillna(0)
    zs_zd = df['czsc_zs_zd']
    zs_zg = df['czsc_zs_zg']
    zs_pos = df['czsc_zs_position'].fillna('')
    bi_length = df['czsc_bi_length'].fillna(0)
    bi_start_p = df['czsc_bi_start_price'].fillna(0)
    bi_end_p = df['czsc_bi_end_price'].fillna(0)
    close = df['close']
    volume = df['volume']

    bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
    bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)

    def edge(s: pd.Series) -> pd.Series:
        s = s.fillna(False).astype(bool)
        prev = s.shift(1).fillna(False).astype(int)
        return s & (prev == 0)

    # ── V3 base ──
    has_buy = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
    has_sell = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')
    v3_long = bi_flip_dn & (has_buy | (trend >= 0))
    v3_short = bi_flip_up & (has_sell | (trend <= 0))

    # ── S1: 收敛中枢放量突破 ──
    has_center = zs_level >= 1
    center_amp = zs_zg - zs_zd
    zs_changed = (zs_zd != zs_zd.shift(1)) | (zs_zg != zs_zg.shift(1))
    amp_narrowing = (center_amp < center_amp.shift(1)) & zs_changed & (center_amp > 0)
    amp_narrowed_recently = amp_narrowing.rolling(20, min_periods=1).max().fillna(0).astype(bool)
    vol_ma = volume.rolling(20, min_periods=5).mean()
    vol_surge = volume > vol_ma * 1.5

    breakout_long = has_center & (zs_pos == 'above') & (bi_dir == 1) & vol_surge
    breakout_short = has_center & (zs_pos == 'below') & (bi_dir == -1) & vol_surge
    if center_narrow:
        breakout_long = breakout_long & amp_narrowed_recently
        breakout_short = breakout_short & amp_narrowed_recently

    s1_long = int(edge(breakout_long).sum())
    s1_short = int(edge(breakout_short).sum())

    # ── S2: 趋势背驰 ──
    bi_pct = abs(bi_end_p - bi_start_p) / bi_start_p.replace(0, float('nan')).fillna(0.001)
    bi_force = bi_pct * bi_length
    bi_force_prev = bi_force.shift(1)
    force_decay = (bi_force < bi_force_prev) & (bi_flip_up | bi_flip_dn)
    top_div = force_decay & bi_flip_up & (trend == 1)
    bot_div = force_decay & bi_flip_dn & (trend == -1)
    # Persist divergence warnings
    top_warn = top_div.copy()
    bot_warn = bot_div.copy()
    for i in range(1, len(df)):
        if not bool(top_warn.iloc[i]):
            top_warn.iloc[i] = top_warn.iloc[i - 1] if i > 0 else False
        if not bool(bot_warn.iloc[i]):
            bot_warn.iloc[i] = bot_warn.iloc[i - 1] if i > 0 else False

    s2_top = int(top_div.sum())
    s2_bot = int(bot_div.sum())

    # ── S3: 中枢震荡 ──
    in_center = has_center & (zs_pos == 'inside')
    near_zd = in_center & (close < zs_zd + (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
    near_zg = in_center & (close > zs_zg - (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
    range_long = near_zd & (trend == 0) if range_trade else pd.Series(False, index=df.index)
    range_short = near_zg & (trend == 0) if range_trade else pd.Series(False, index=df.index)

    s3_long = int(edge(range_long).sum())
    s3_short = int(edge(range_short).sum())

    # ── S4: 量价增强 ──
    close_high_20 = close.rolling(20, min_periods=5).max()
    at_high = close >= close_high_20 * 0.995
    vol_peak_20 = volume.rolling(20, min_periods=5).max()
    vol_weakening = at_high & (volume < vol_peak_20 * 0.6) & (trend == 1)

    # ── Combine ──
    long_cond = v3_long | breakout_long | range_long
    short_cond = v3_short | breakout_short | range_short
    if trend_filter:
        long_cond = long_cond & (trend >= 0)
        short_cond = short_cond & (trend <= 0)
    if divergence_filter:
        long_cond = long_cond & ~top_warn.astype(bool)
        short_cond = short_cond & ~bot_warn.astype(bool)
    if vol_confirm:
        long_cond = long_cond & ~vol_weakening

    open_long = edge(long_cond)
    open_short = edge(short_cond)

    n = len(df)
    total_open_long = int(open_long.sum())
    total_open_short = int(open_short.sum())

    def sum_last(s: pd.Series, n_bars: int) -> int:
        return int(s.iloc[-n_bars:].sum()) if n_bars <= len(s) else int(s.sum())

    last5_long = sum_last(open_long, LAST_N_ACTIVE)
    last5_short = sum_last(open_short, LAST_N_ACTIVE)
    last20_long = sum_last(open_long, LAST_N_RECENT)
    last20_short = sum_last(open_short, LAST_N_RECENT)

    bi_flip_all = bi_flip_up | bi_flip_dn
    bi_flip_count = int(bi_flip_all.sum())
    flip_indices = np.where(bi_flip_all.values)[0]
    last_flip_pos = int(n - flip_indices[-1]) if len(flip_indices) > 0 else n
    current_bi_dir = int(bi_dir.iloc[-1])
    current_trend = int(trend.iloc[-1])

    return {
        'total_open_long': total_open_long,
        'total_open_short': total_open_short,
        'total_signals': total_open_long + total_open_short,
        'last5_long': last5_long,
        'last5_short': last5_short,
        'last5_total': last5_long + last5_short,
        'last20_long': last20_long,
        'last20_short': last20_short,
        'last20_total': last20_long + last20_short,
        'bi_flip_count': bi_flip_count,
        'last_flip_pos': last_flip_pos,
        'current_bi_dir': current_bi_dir,
        'current_trend': current_trend,
        'bar_count': n,
        # V4 scenario breakdown
        's1_breakout_long': s1_long,
        's1_breakout_short': s1_short,
        's2_top_divergence': s2_top,
        's2_bot_divergence': s2_bot,
        's3_range_long': s3_long,
        's3_range_short': s3_short,
    }


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_symbol(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    use_v4: bool = False,
    range_trade: bool = False,
) -> Dict[str, Any]:
    """Fetch data, compute CZSC features and signals for one symbol+timeframe."""
    result = {
        'symbol': symbol,
        'timeframe': timeframe,
        'status': 'ok',
        'version': 'v4' if use_v4 else 'v3',
    }
    df = fetch_klines(exchange, symbol, timeframe, KLINE_LIMIT)
    if df is None:
        result['status'] = 'no_data'
        result.update(_empty_result())
        return result

    result['bar_count'] = len(df)

    # Compute CZSC features
    try:
        df_czsc = compute_czsc_features(df, freq=timeframe, force=True, symbol=symbol)
    except Exception as e:
        print(f"  [ERR] CZSC compute failed for {symbol} {timeframe}: {e}")
        result['status'] = 'czsc_error'
        result.update(_empty_result())
        return result

    if 'czsc_bi_dir' not in df_czsc.columns:
        result['status'] = 'czsc_no_features'
        result.update(_empty_result())
        return result

    # Compute signals
    if use_v4:
        sig = compute_v4_signals(df_czsc, trend_filter=1, vol_confirm=1,
                                  center_narrow=1, divergence_filter=1,
                                  range_trade=1 if range_trade else 0)
    else:
        sig = compute_signals(df_czsc, trend_filter=1)
    result.update(sig)
    return result


def classify_activity(result: Dict[str, Any]) -> str:
    """Classify a result as ACTIVE / RECENT / DORMANT / DEAD."""
    if result['last5_total'] > 0:
        return 'ACTIVE'
    elif result['last20_total'] > 0:
        return 'RECENT'
    elif result['total_signals'] > 0:
        return 'DORMANT'
    else:
        return 'DEAD'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="CZSC Market Opportunity Scanner")
    parser.add_argument("--v4", action="store_true", help="Use V4 multi-scenario signal logic")
    parser.add_argument("--range", action="store_true", help="Enable range trading (S3) in V4 mode")
    args = parser.parse_args()

    use_v4 = args.v4
    range_trade = args.range

    print("=" * 70)
    print(f"CZSC Market Opportunity Scanner ({'V4' if use_v4 else 'V3'})")
    print("=" * 70)

    # Check czsc
    if not is_czsc_enabled():
        print("[FATAL] czsc library is not installed. Cannot run.")
        sys.exit(1)
    print("[OK] czsc library available")

    exchange = make_exchange()
    print(f"[OK] Exchange: gate.io (public data, rate-limited)")
    print(f"     Symbols: {len(SYMBOLS)}")
    print(f"     Timeframes: {TIMEFRAMES}")
    print(f"     Kline limit: {KLINE_LIMIT} bars")
    print(f"     Active window: last {LAST_N_ACTIVE} bars")
    print(f"     Recent window: last {LAST_N_RECENT} bars")
    print()

    all_results: List[Dict[str, Any]] = []
    total_combos = len(SYMBOLS) * len(TIMEFRAMES)
    done = 0

    for tf in TIMEFRAMES:
        print(f"\n{'─'*50}")
        print(f"Timeframe: {tf}")
        print(f"{'─'*50}")
        for symbol in SYMBOLS:
            done += 1
            pct = done * 100 // total_combos
            print(f"  [{done:3d}/{total_combos}] {symbol:<16s} {tf:>3s} ...", end=' ', flush=True)
            t0 = time.time()
            try:
                r = scan_symbol(exchange, symbol, tf, use_v4=use_v4, range_trade=range_trade)
            except Exception as e:
                r = {'symbol': symbol, 'timeframe': tf, 'status': 'error'}
                r.update(_empty_result())
                print(f"ERROR: {e}")
            elapsed = time.time() - t0
            activity = classify_activity(r)
            r['activity'] = activity
            print(
                f"bars={r['bar_count']:>4d}  "
                f"sigs={r['total_signals']:>3d}  "
                f"L5={r['last5_total']:>2d}  "
                f"L20={r['last20_total']:>2d}  "
                f"bi_dir={r['current_bi_dir']:>2d}  "
                f"trend={r['current_trend']:>2d}  "
                f"=> {activity:<8s}  "
                f"({elapsed:.1f}s)"
            )
            if use_v4 and r.get('version') == 'v4':
                s1 = r.get('s1_breakout_long', 0) + r.get('s1_breakout_short', 0)
                s2 = r.get('s2_top_divergence', 0) + r.get('s2_bot_divergence', 0)
                s3 = r.get('s3_range_long', 0) + r.get('s3_range_short', 0)
                if s1 or s2 or s3:
                    print(f"         [V4] S1(Brk)={s1} S2(Div)={s2} S3(Rng)={s3}")
            all_results.append(r)
            # Small delay to be gentle on rate limit
            time.sleep(0.3)

    # -----------------------------------------------------------------------
    # Sort and display
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    # Sort: ACTIVE first, then RECENT, then by last5_total desc, then last20_total desc
    activity_order = {'ACTIVE': 0, 'RECENT': 1, 'DORMANT': 2, 'DEAD': 3}
    all_results.sort(key=lambda r: (
        activity_order.get(r['activity'], 9),
        -r['last5_total'],
        -r['last20_total'],
        -r['total_signals'],
    ))

    # Print table header
    hdr = (
        f"{'#':>3s}  {'Symbol':<16s} {'TF':>3s}  {'Activity':<8s}  "
        f"{'Bars':>5s}  {'TotalSig':>8s}  {'L5Sig':>5s}  {'L20Sig':>6s}  "
        f"{'BiDir':>5s}  {'Trend':>5s}  {'LastFlip':>8s}"
    )
    print(hdr)
    print("-" * len(hdr))

    for i, r in enumerate(all_results, 1):
        status_marker = ''
        if r['activity'] == 'ACTIVE':
            status_marker = ' ***'
        elif r['activity'] == 'RECENT':
            status_marker = ' *'

        print(
            f"{i:>3d}  {r['symbol']:<16s} {r['timeframe']:>3s}  "
            f"{r['activity']:<8s}  "
            f"{r['bar_count']:>5d}  "
            f"{r['total_signals']:>8d}  "
            f"{r['last5_total']:>5d}  "
            f"{r['last20_total']:>6d}  "
            f"{r['current_bi_dir']:>5d}  "
            f"{r['current_trend']:>5d}  "
            f"{r['last_flip_pos']:>8d}"
            f"{status_marker}"
        )

    # -----------------------------------------------------------------------
    # Top 10 recommendations
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("TOP 10 RECOMMENDED COMBINATIONS")
    print("=" * 70)

    # Score = weighted sum: last5 heavily weighted, last20 moderate, total mild
    def score(r: Dict) -> float:
        return (
            r['last5_total'] * 50.0
            + r['last20_total'] * 10.0
            + r['total_signals'] * 0.5
            + (1.0 if r['current_bi_dir'] != 0 else 0.0) * 5.0
        )

    scored = [(score(r), r) for r in all_results]
    scored.sort(key=lambda x: -x[0])
    top10 = scored[:10]

    for rank, (sc, r) in enumerate(top10, 1):
        print(
            f"  #{rank:2d}  {r['symbol']:<16s} {r['timeframe']:>3s}  "
            f"score={sc:>6.1f}  "
            f"activity={r['activity']:<8s}  "
            f"L5={r['last5_total']}  L20={r['last20_total']}  "
            f"total={r['total_signals']}  "
            f"bi_dir={r['current_bi_dir']}  trend={r['current_trend']}"
        )

    # -----------------------------------------------------------------------
    # Activity breakdown
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("ACTIVITY BREAKDOWN")
    print("=" * 70)
    for act in ['ACTIVE', 'RECENT', 'DORMANT', 'DEAD']:
        items = [r for r in all_results if r['activity'] == act]
        print(f"\n  {act} ({len(items)} combinations):")
        if not items:
            print("    (none)")
        for r in items[:15]:
            print(
                f"    {r['symbol']:<16s} {r['timeframe']:>3s}  "
                f"L5={r['last5_total']}  L20={r['last20_total']}  "
                f"total={r['total_signals']}  "
                f"bi_dir={r['current_bi_dir']}  trend={r['current_trend']}"
            )

    # -----------------------------------------------------------------------
    # Analysis of ACTIVE combinations
    # -----------------------------------------------------------------------
    active_items = [r for r in all_results if r['activity'] == 'ACTIVE']
    if active_items:
        print("\n" + "=" * 70)
        print("ACTIVE COMBINATION ANALYSIS")
        print("=" * 70)
        for r in active_items:
            tf_display = r['timeframe']
            bars = r['bar_count']
            # Estimate time coverage
            tf_minutes = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '1H': 60, '4H': 240}
            mins = tf_minutes.get(r['timeframe'], 0)
            coverage_hours = bars * mins / 60 if mins else 0

            print(f"\n  {r['symbol']} @ {tf_display}:")
            print(f"    Coverage: ~{coverage_hours:.1f} hours ({bars} bars)")
            print(f"    Last 5 bars: {r['last5_total']} signals (L:{r['last5_long']} S:{r['last5_short']})")
            print(f"    Last 20 bars: {r['last20_total']} signals (L:{r['last20_long']} S:{r['last20_short']})")
            print(f"    Total signals: {r['total_signals']} (L:{r['total_open_long']} S:{r['total_open_short']})")
            print(f"    Current bi_dir: {r['current_bi_dir']} (1=up, -1=down, 0=none)")
            print(f"    Current trend: {r['current_trend']} (1=up, -1=down, 0=neutral)")
            print(f"    Bi flips: {r['bi_flip_count']}, last flip was {r['last_flip_pos']} bars ago")

            # Signal direction analysis
            if r['last5_long'] > 0 and r['last5_short'] == 0:
                print(f"    >> Bullish signal detected (long only)")
            elif r['last5_short'] > 0 and r['last5_long'] == 0:
                print(f"    >> Bearish signal detected (short only)")
            elif r['last5_long'] > 0 and r['last5_short'] > 0:
                print(f"    >> Mixed signals (both long and short) - volatility regime")

    print("\n" + "=" * 70)
    print("SCAN COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    main()
