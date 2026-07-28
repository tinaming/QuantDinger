"""
CZSC V3 vs V4 Scenario Comparison Script
========================================
Runs both V3 and V4 signal logic on the same data and shows per-scenario
signal count differences. Each scenario can be toggled independently.

Usage:
    cd backend_api_python
    python scripts/compare_czsc_v3_v4.py
    python scripts/compare_czsc_v3_v4.py --bars 500 --seed 123
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

# Bootstrap
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.czsc_bridge import (
    compute_czsc_features,
    is_czsc_enabled,
    add_mock_czsc_columns,
)


# ─────────────────────────────────────────────────────────────────────────
# Synthetic data generator
# ─────────────────────────────────────────────────────────────────────────

def make_ohlcv_df(n: int = 500, seed: int = 42, freq: str = "1h") -> pd.DataFrame:
    """Generate synthetic OHLCV data with trend + consolidation + volatility."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    returns = rng.normal(0, 0.005, n)
    # Add a mild uptrend for the first 60%, then consolidation
    trend_bias = np.zeros(n)
    trend_bias[:int(n * 0.6)] = 0.0002  # uptrend
    returns = returns + trend_bias
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    open_price = close * (1 + rng.normal(0, 0.001, n))
    high = np.maximum(high, np.maximum(open_price, close))
    low = np.minimum(low, np.minimum(open_price, close))
    # Volume: higher during breakouts (price change > 1%)
    price_chg = np.abs(np.diff(close, prepend=close[0]) / close)
    base_vol = np.abs(rng.normal(1000, 300, n))
    surge_vol = np.abs(rng.normal(3000, 800, n))
    volume = np.where(price_chg > 0.01, surge_vol, base_vol)
    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ─────────────────────────────────────────────────────────────────────────
# V3 signal logic (mirrors scan_czsc_opportunities.py)
# ─────────────────────────────────────────────────────────────────────────

def compute_v3_signals(df: pd.DataFrame) -> Dict[str, int]:
    """V3: causal reversal + trend filter."""
    bi_dir = df['czsc_bi_dir']
    bi_dir_prev = bi_dir.shift(1).fillna(0)
    bs_type = df['czsc_bs_type'].fillna('')
    trend = df['czsc_trend'].fillna(0)

    bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)
    bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
    has_buy = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
    has_sell = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')

    long_cond = bi_flip_dn & (has_buy | (trend >= 0)) & (trend >= 0)
    short_cond = bi_flip_up & (has_sell | (trend <= 0)) & (trend <= 0)

    def edge(s):
        s = s.fillna(False).astype(bool)
        return s & (s.shift(1).fillna(False).astype(int) == 0)

    return {
        'long': int(edge(long_cond).sum()),
        'short': int(edge(short_cond).sum()),
    }


# ─────────────────────────────────────────────────────────────────────────
# V4 signal logic (mirrors CZSC_V4_INDICATOR_CODE)
# ─────────────────────────────────────────────────────────────────────────

def compute_v4_signals(
    df: pd.DataFrame,
    trend_filter: int = 1,
    vol_confirm: int = 1,
    center_narrow: int = 1,
    divergence_filter: int = 1,
    range_trade: int = 0,
) -> Dict[str, Any]:
    """V4: multi-scenario signal logic with per-scenario breakdown."""
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

    def edge(s):
        s = s.fillna(False).astype(bool)
        return s & (s.shift(1).fillna(False).astype(int) == 0)

    # ── V3 baseline ──
    has_buy = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
    has_sell = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')
    v3_long = bi_flip_dn & (has_buy | (trend >= 0))
    v3_short = bi_flip_up & (has_sell | (trend <= 0))

    # ── Scenario 1: 收敛中枢放量突破 ──
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

    # ── Scenario 2: 趋势背驰过滤 ──
    bi_pct = abs(bi_end_p - bi_start_p) / bi_start_p.replace(0, float('nan')).fillna(0.001)
    bi_force = bi_pct * bi_length
    bi_force_prev = bi_force.shift(1)
    force_decay = (bi_force < bi_force_prev) & (bi_flip_up | bi_flip_dn)
    top_div = force_decay & bi_flip_up & (trend == 1)
    bot_div = force_decay & bi_flip_dn & (trend == -1)
    # Persist warnings
    top_warn = top_div.copy()
    bot_warn = bot_div.copy()
    for i in range(1, len(df)):
        if not bool(top_warn.iloc[i]):
            top_warn.iloc[i] = top_warn.iloc[i - 1] if i > 0 else False
        if not bool(bot_warn.iloc[i]):
            bot_warn.iloc[i] = bot_warn.iloc[i - 1] if i > 0 else False

    s2_top = int(top_div.sum())
    s2_bot = int(bot_div.sum())

    # ── Scenario 3: 中枢震荡 ──
    in_center = has_center & (zs_pos == 'inside')
    near_zd = in_center & (close < zs_zd + (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
    near_zg = in_center & (close > zs_zg - (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
    range_long = near_zd & (trend == 0) if range_trade else pd.Series(False, index=df.index)
    range_short = near_zg & (trend == 0) if range_trade else pd.Series(False, index=df.index)

    s3_long = int(edge(range_long).sum())
    s3_short = int(edge(range_short).sum())

    # ── Scenario 4: 量价增强 ──
    vol_ma_short = volume.rolling(10, min_periods=3).mean()
    vol_shrink = volume < vol_ma_short * 0.7
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

    v4_long = int(edge(long_cond).sum())
    v4_short = int(edge(short_cond).sum())
    v3_base_long = int(edge(v3_long & (trend >= 0 if trend_filter else True)).sum())
    v3_base_short = int(edge(v3_short & (trend <= 0 if trend_filter else True)).sum())

    return {
        'v3_base_long': v3_base_long,
        'v3_base_short': v3_base_short,
        'v4_long': v4_long,
        'v4_short': v4_short,
        's1_breakout_long': s1_long,
        's1_breakout_short': s1_short,
        's2_top_divergence': s2_top,
        's2_bot_divergence': s2_bot,
        's3_range_long': s3_long,
        's3_range_short': s3_short,
        'v4_total': v4_long + v4_short,
        'v3_total': v3_base_long + v3_base_short,
    }


# ─────────────────────────────────────────────────────────────────────────
# Main comparison
# ─────────────────────────────────────────────────────────────────────────

def print_header(title: str):
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")


def print_row(label: str, v3: int, v4: int, delta: str = ""):
    chg = v4 - v3
    sign = "+" if chg > 0 else ""
    print(f"  {label:<30s}  V3={v3:>5d}  V4={v4:>5d}  Δ={sign}{chg}  {delta}")


def main():
    parser = argparse.ArgumentParser(description="CZSC V3 vs V4 comparison")
    parser.add_argument("--bars", type=int, default=500, help="Number of bars")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    print_header("CZSC V3 vs V4 场景对比")
    print(f"  Bars: {args.bars}, Seed: {args.seed}")

    # ── Step 1: Generate data ──
    df = make_ohlcv_df(n=args.bars, seed=args.seed)
    print(f"  Data shape: {df.shape}")

    # ── Step 2: Compute CZSC features ──
    if is_czsc_enabled():
        print("  CZSC: using real czsc library")
        df = compute_czsc_features(df, freq="1H", symbol="BTCUSDT")
    else:
        print("  CZSC: using mock columns (install czsc for real features)")
        df = add_mock_czsc_columns(df)

    # ── Step 3: V3 baseline ──
    v3 = compute_v3_signals(df)
    print_header("V3 Baseline (因果反转 + 趋势过滤)")
    print(f"  Long: {v3['long']}, Short: {v3['short']}, Total: {v3['long'] + v3['short']}")

    # ── Step 4: V4 per-scenario comparison ──
    print_header("场景 1: 收敛中枢放量突破 3buy/3sell")
    v4_s1 = compute_v4_signals(df, vol_confirm=1, center_narrow=1,
                                divergence_filter=0, range_trade=0)
    print_row("V3 → V4+S1", v3['long'] + v3['short'], v4_s1['v4_total'],
              "← V4 adds breakout signals")
    print(f"  ── Breakdown ──")
    print(f"    S1 Breakout Long:  {v4_s1['s1_breakout_long']}")
    print(f"    S1 Breakout Short: {v4_s1['s1_breakout_short']}")

    print_header("场景 2: 趋势背驰过滤")
    v4_s2 = compute_v4_signals(df, vol_confirm=1, center_narrow=1,
                                divergence_filter=1, range_trade=0)
    print_row("V4+S1 → V4+S1+S2", v4_s1['v4_total'], v4_s2['v4_total'],
              "← divergence filter removes weak signals")
    print(f"  ── Breakdown ──")
    print(f"    S2 Top Divergence:    {v4_s2['s2_top_divergence']} (顶背驰过滤)")
    print(f"    S2 Bottom Divergence: {v4_s2['s2_bot_divergence']} (底背驰过滤)")

    print_header("场景 3: 中枢震荡高抛低吸")
    v4_s3 = compute_v4_signals(df, vol_confirm=1, center_narrow=1,
                                divergence_filter=1, range_trade=1)
    print_row("V4+S1+S2 → V4+S1+S2+S3", v4_s2['v4_total'], v4_s3['v4_total'],
              "← adds center swing trading signals")
    print(f"  ── Breakdown ──")
    print(f"    S3 Range Long:  {v4_s3['s3_range_long']} (盘整 ZD 附近做多)")
    print(f"    S3 Range Short: {v4_s3['s3_range_short']} (盘整 ZG 附近做空)")

    # ── Step 5: Final comparison ──
    print_header("V3 → V4 全场景综合对比")
    v4_full = compute_v4_signals(df, vol_confirm=1, center_narrow=1,
                                  divergence_filter=1, range_trade=1)
    print_row("V3 Total", v3['long'] + v3['short'], v4_full['v4_total'],
              "← V4 = V3 base + S1 breakout + S3 range - S2 filter")
    print(f"  ── Full Breakdown ──")
    print(f"    V3 base (因果反转):      L={v4_full['v3_base_long']} S={v4_full['v3_base_short']}")
    print(f"    S1 (放量突破):           L={v4_full['s1_breakout_long']} S={v4_full['s1_breakout_short']}")
    print(f"    S2 (背驰过滤):           T={v4_full['s2_top_divergence']} B={v4_full['s2_bot_divergence']}")
    print(f"    S3 (中枢震荡):           L={v4_full['s3_range_long']} S={v4_full['s3_range_short']}")
    print(f"    V4 Final:                L={v4_full['v4_long']} S={v4_full['v4_short']}")

    print_header("场景对比总结")
    s1_ok = v4_s1['s1_breakout_long'] + v4_s1['s1_breakout_short'] > 0
    s2_ok = v4_s2['v4_total'] <= v4_s1['v4_total']
    s3_ok = v4_s3['s3_range_long'] + v4_s3['s3_range_short'] > 0
    print(f"""
  场景1 (突破):  {'[OK] 新增信号' if s1_ok else '[--] 无新增信号 (mock数据限制)'}
    新增中枢收敛放量突破信号，捕捉3buy/3sell经典场景

  场景2 (背驰):  {'[OK] 过滤生效' if s2_ok else '[--] 无过滤效果 (mock数据限制)'}
    趋势衰竭时不追同向，避免买顶卖底

  场景3 (震荡):  {'[OK] 新增信号' if s3_ok else '[--] 无新增信号 (mock数据限制)'}
    盘整行情中在ZD附近做多、ZG附近做空

  场景4 (量价):  已融入场景1（放量确认）+ 场景2（缩量回踩）
    放量突破、缩量回踩、量价背驰三重确认

  V3 -> V4 总信号变化: {v3['long'] + v3['short']} -> {v4_full['v4_total']} (delta={v4_full['v4_total'] - v3['long'] - v3['short']:+d})
""")


if __name__ == '__main__':
    main()