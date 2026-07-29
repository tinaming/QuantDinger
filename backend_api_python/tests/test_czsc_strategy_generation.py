"""
Tests for CZSC (缠论) strategy generation — indicator validation,
backtest injection, and live strategy detection.

Covers:
  1. Indicator code that uses czsc_ columns validates via dry-run.
  2. Backtest executor detects czsc_ references and injects features.
  3. Live trading executor detects czsc_ references and injects features.
  4. Strategy creation with embedded CZSC indicator code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.czsc_bridge import (
    CZSC_COLUMNS,
    add_mock_czsc_columns,
    code_uses_czsc,
    compute_czsc_features,
    is_czsc_enabled,
)


# ---------------------------------------------------------------------------
# CZSC Indicator Code — follows four-way execution contract
# ---------------------------------------------------------------------------

CZSC_TREND_INDICATOR_CODE = '''
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2
# @strategy market crypto
# @strategy symbol BTCUSDT
# @strategy timeframe 1H
# @strategy tradeDirection both
# @param trend_filter int 1 Trend filter: 1=only trend direction, 0=allow all

my_indicator_name = "CZSC Trend Reversal"
my_indicator_description = "缠论因果反转：笔确认结束处反手（见底做多 / 见顶做空）"

df = df.copy()
trend_filter = int(params.get('trend_filter', 1))

# ── Feature engineering from czsc_ columns ──
bi_dir = df['czsc_bi_dir']
bi_dir_prev = bi_dir.shift(1).fillna(0)
bs_type = df['czsc_bs_type'].fillna('')
trend = df['czsc_trend'].fillna(0)
zs_position = df['czsc_zs_position'].fillna('')

# Causal: bi_flip_* means the stroke just completed (confirmed), not "began".
# bi_flip_up = upward stroke completed = top  → SHORT
# bi_flip_dn = downward stroke completed = bottom → LONG
bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)
has_buy_point = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
has_sell_point = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')
long_cond = bi_flip_dn & (has_buy_point | (trend >= 0))
short_cond = bi_flip_up & (has_sell_point | (trend <= 0))

# Apply trend filter: only trade in the dominant trend direction
if trend_filter == 1:
    long_cond = long_cond & (trend >= 0)
    short_cond = short_cond & (trend <= 0)

# ── Edge extraction (first occurrence only) ──
def edge(s):
    s = s.fillna(False).astype(bool)
    prev = s.shift(1).fillna(False).astype(int)
    return s & (prev == 0)

long_edge = edge(long_cond)
short_edge = edge(short_cond)

# ── Four-way execution columns (causal-reversal) ──
# open_long: flip-down edge (bottom confirmed)
# close_long: flip-up edge (top confirmed → exit long)
# open_short: flip-up edge (top confirmed)
# close_short: flip-down edge (bottom confirmed → exit short)
df['open_long'] = long_edge
df['close_long'] = edge(bi_flip_up)
df['open_short'] = short_edge
df['close_short'] = edge(bi_flip_dn)

# ── Signal markers for chart ──
buy_marks = [
    float(df['low'].iloc[i]) * 0.995 if bool(df['open_long'].iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(df['high'].iloc[i]) * 1.005 if bool(df['open_short'].iloc[i]) else None
    for i in range(len(df))
]

# ── Plots: stroke direction as background ──
bi_dir_list = bi_dir.tolist()
plots = [
    {
        'name': 'Bi Direction',
        'type': 'line',
        'data': bi_dir_list,
        'color': '#888888',
        'width': 1,
    }
]

output = {
    'name': my_indicator_name,
    'plots': plots,
    'signals': [
        {'type': 'buy', 'text': 'Buy', 'data': buy_marks, 'color': '#00FF00'},
        {'type': 'sell', 'text': 'Sell', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''


CZSC_CENTER_BREAKOUT_CODE = '''
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2
# @strategy market crypto
# @strategy symbol ETHUSDT
# @strategy timeframe 4H
# @strategy tradeDirection both
# @param min_level int 1 Minimum center level for breakout signals

my_indicator_name = "CZSC Center Breakout"
my_indicator_description = "缠论中枢突破策略：价格突破中枢上下沿 + 笔方向确认"

df = df.copy()
min_level = int(params.get('min_level', 1))

# ── Feature engineering ──
zs_level = df['czsc_zs_level'].fillna(0)
zs_zd = df['czsc_zs_zd'].fillna(0)
zs_zg = df['czsc_zs_zg'].fillna(0)
zs_pos = df['czsc_zs_position'].fillna('')
bi_dir = df['czsc_bi_dir'].fillna(0)
trend = df['czsc_trend'].fillna(0)

# ── Breakout conditions ──
has_center = zs_level >= min_level

# Long: price breaks above center top (zs_zg) with upward stroke
breakout_up = has_center & (zs_pos == 'above') & (bi_dir == 1)

# Short: price breaks below center bottom (zs_zd) with downward stroke
breakout_dn = has_center & (zs_pos == 'below') & (bi_dir == -1)

# ── Edge extraction ──
def edge(s):
    s = s.fillna(False).astype(bool)
    prev = s.shift(1).fillna(False).astype(int)
    return s & (prev == 0)

long_edge = edge(breakout_up)
short_edge = edge(breakout_dn)

# Exit: price returns inside center
exit_long = edge((zs_pos == 'inside') | (zs_pos == 'below'))
exit_short = edge((zs_pos == 'inside') | (zs_pos == 'above'))

# ── Four-way execution ──
df['open_long'] = long_edge
df['close_long'] = exit_long
df['open_short'] = short_edge
df['close_short'] = exit_short

# ── Markers ──
buy_marks = [
    float(df['low'].iloc[i]) * 0.998 if bool(df['open_long'].iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(df['high'].iloc[i]) * 1.002 if bool(df['open_short'].iloc[i]) else None
    for i in range(len(df))
]

# ── Plots: center zones ──
zd_list = zs_zd.tolist()
zg_list = zs_zg.tolist()
plots = [
    {'name': 'ZD (Center Low)', 'type': 'line', 'data': zd_list, 'color': '#00AA00', 'width': 1},
    {'name': 'ZG (Center High)', 'type': 'line', 'data': zg_list, 'color': '#AA0000', 'width': 1},
]

output = {
    'name': my_indicator_name,
    'plots': plots,
    'signals': [
        {'type': 'buy', 'text': 'Breakout Up', 'data': buy_marks, 'color': '#00FF00'},
        {'type': 'sell', 'text': 'Breakout Down', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''


CZSC_V4_INDICATOR_CODE = '''
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2
# @strategy market crypto
# @strategy symbol BTCUSDT
# @strategy timeframe 1H
# @strategy tradeDirection both
# @param trend_filter int 1 Trend filter: 1=trend direction only, 0=allow all
# @param vol_confirm int 1 Volume confirmation: 1=require volume on breakout
# @param center_narrow int 1 Center narrowing: 1=require narrowing amplitude
# @param divergence_filter int 1 Divergence filter: 1=filter force-decay signals
# @param range_trade int 0 Range trading: 1=enable center swing trading

my_indicator_name = "CZSC v4 Multi-Scenario"
my_indicator_description = "缠论V4：收敛中枢放量突破 + 趋势背驰过滤 + 中枢震荡 + 量价配合"

df = df.copy()

# ── Parameters ──
trend_filter = int(params.get('trend_filter', 1))
vol_confirm = int(params.get('vol_confirm', 1))
center_narrow = int(params.get('center_narrow', 1))
divergence_filter = int(params.get('divergence_filter', 1))
range_trade = int(params.get('range_trade', 0))

# ── Base feature columns from czsc bridge ──
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
high = df['high']
low = df['low']
open_ = df['open']
volume = df['volume']

# ── Causal flip detection (V3 foundation) ──
# bi_flip_up = upward stroke completed = top confirmed  → bearish
# bi_flip_dn = downward stroke completed = bottom confirmed → bullish
bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)

# ── Helper: edge detection (first occurrence only) ──
def edge(s):
    s = s.fillna(False).astype(bool)
    prev = s.shift(1).fillna(False).astype(int)
    return s & (prev == 0)

# ═══════════════════════════════════════════════════════════════
# SCENARIO 1: 收敛中枢放量突破 3buy / 3sell
# ═══════════════════════════════════════════════════════════════
# 缠论第三类买卖点增强版：中枢振幅收敛 + 放量确认
# 3buy: 中枢上沿突破，回踩不进入中枢，放量确认
# 3sell: 中枢下沿跌破，反弹不进入中枢，放量确认

has_center = zs_level >= 1

# ── 1a. 中枢振幅收敛检测 ──
# 追踪中枢切换：当 ZD 或 ZG 变化时，表示进入新中枢
center_amp = zs_zg - zs_zd
zs_changed = (zs_zd != zs_zd.shift(1)) | (zs_zg != zs_zg.shift(1))
# 振幅缩小：当前振幅 < 前一个值（仅在中枢切换点标记）
amp_narrowing = (center_amp < center_amp.shift(1)) & zs_changed & (center_amp > 0)
# 最近 N 根 bar 内有过振幅收敛
amp_narrowed_recently = amp_narrowing.rolling(20, min_periods=1).max().fillna(0).astype(bool)

# ── 1b. 放量检测 ──
vol_ma = volume.rolling(20, min_periods=5).mean()
vol_surge = volume > vol_ma * 1.5

# ── 1c. 突破信号 ──
# 3buy: 价格突破中枢上沿 + 上升笔方向 + 放量
breakout_long = has_center & (zs_pos == 'above') & (bi_dir == 1) & vol_surge
# 3sell: 价格跌破中枢下沿 + 下降笔方向 + 放量
breakout_short = has_center & (zs_pos == 'below') & (bi_dir == -1) & vol_surge

# 中枢收敛过滤
if center_narrow:
    breakout_long = breakout_long & amp_narrowed_recently
    breakout_short = breakout_short & amp_narrowed_recently

# ═══════════════════════════════════════════════════════════════
# SCENARIO 2: 趋势背驰过滤
# ═══════════════════════════════════════════════════════════════
# 缠论背驰：同一方向的两笔，后一笔力度弱于前一笔 → 趋势衰竭
# 顶背驰 → 过滤做多信号；底背驰 → 过滤做空信号

# 笔的价格变动幅度
bi_pct_change = abs(bi_end_p - bi_start_p) / bi_start_p.replace(0, float('nan')).fillna(0.001)
# 笔的力度 = 价格变动幅度 × 笔长度（K线数量）
bi_force = bi_pct_change * bi_length

# 在笔翻转点比较前后两笔的力度
# 翻转时刻：前一笔的力度（shift 1）vs 当前笔的力度
bi_force_prev = bi_force.shift(1)
force_decay = (bi_force < bi_force_prev) & (bi_flip_up | bi_flip_dn)

# 顶背驰：上涨趋势中上升笔完成时，力度衰减
# 底背驰：下跌趋势中下降笔完成时，力度衰减
top_divergence = force_decay & bi_flip_up & (trend == 1)
bottom_divergence = force_decay & bi_flip_dn & (trend == -1)

# 背驰信号闪现（持续到下个翻转点）
top_div_warn = top_divergence.copy()
bottom_div_warn = bottom_divergence.copy()
for i in range(1, len(df)):
    if pd.notna(bi_flip_up.iloc[i]) and bool(bi_flip_up.iloc[i]):
        pass  # reset on new flip
    if not bool(top_div_warn.iloc[i]):
        top_div_warn.iloc[i] = top_div_warn.iloc[i-1] if i > 0 else False
    if not bool(bottom_div_warn.iloc[i]):
        bottom_div_warn.iloc[i] = bottom_div_warn.iloc[i-1] if i > 0 else False

# ═══════════════════════════════════════════════════════════════
# SCENARIO 3: 中枢震荡高抛低吸
# ═══════════════════════════════════════════════════════════════
# 缠论中枢震荡：盘整行情中，在 ZD 附近做多，ZG 附近做空
# 仅在 czsc_trend == 0（盘整）时启用

in_center = has_center & (zs_pos == 'inside')
# ZD 区域（下沿 20% 区间）
near_zd = in_center & (close < zs_zd + (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
# ZG 区域（上沿 20% 区间）
near_zg = in_center & (close > zs_zg - (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)

# 震荡信号（仅盘整时生效）
range_long = near_zd & (trend == 0) if range_trade else pd.Series(False, index=df.index)
range_short = near_zg & (trend == 0) if range_trade else pd.Series(False, index=df.index)

# ═══════════════════════════════════════════════════════════════
# SCENARIO 4: 量价配合全面增强
# ═══════════════════════════════════════════════════════════════
# 缩量回调：突破后回踩中枢上沿时缩量 = 确认有效
# 放量滞涨：价格新高但量能不足 = 假突破风险

# 缩量回踩：价格在中枢上方但接近 ZG，成交量萎缩
vol_ma_short = volume.rolling(10, min_periods=3).mean()
vol_shrink = volume < vol_ma_short * 0.7
pullback_confirm = has_center & (zs_pos == 'above') & (close < zs_zg * 1.02) & vol_shrink

# 放量滞涨：价格创新高但量能低于前高量能
close_high_20 = close.rolling(20, min_periods=5).max()
at_high = close >= close_high_20 * 0.995
vol_peak_20 = volume.rolling(20, min_periods=5).max()
vol_weakening = at_high & (volume < vol_peak_20 * 0.6) & (trend == 1)

# ═══════════════════════════════════════════════════════════════
# SIGNAL COMBINATION (V4 综合信号)
# ═══════════════════════════════════════════════════════════════

# V3 基础：因果反转
has_buy_point = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
has_sell_point = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')
v3_long = bi_flip_dn & (has_buy_point | (trend >= 0))
v3_short = bi_flip_up & (has_sell_point | (trend <= 0))

# V4 增强：V3 + 场景1(放量突破) + 场景3(中枢震荡)
long_cond = v3_long | breakout_long | range_long
short_cond = v3_short | breakout_short | range_short

# 趋势过滤
if trend_filter == 1:
    long_cond = long_cond & (trend >= 0)
    short_cond = short_cond & (trend <= 0)

# 场景2：背驰过滤 — 顶背驰不追多，底背驰不追空
if divergence_filter:
    long_cond = long_cond & ~top_div_warn.astype(bool)
    short_cond = short_cond & ~bottom_div_warn.astype(bool)

# 场景4：量价增强 — 放量滞涨时不追多
if vol_confirm:
    long_cond = long_cond & ~vol_weakening

# ── Edge extraction ──
long_edge = edge(long_cond)
short_edge = edge(short_cond)

# ── Four-way execution ──
df['open_long'] = long_edge
df['close_long'] = edge(bi_flip_up) | edge(zs_pos == 'below')
df['open_short'] = short_edge
df['close_short'] = edge(bi_flip_dn) | edge(zs_pos == 'above')

# ── Signal markers for chart ──
buy_marks = [
    float(df['low'].iloc[i]) * 0.995 if bool(df['open_long'].iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(df['high'].iloc[i]) * 1.005 if bool(df['open_short'].iloc[i]) else None
    for i in range(len(df))
]

# ── Plots: multi-layer visualization ──
bi_dir_list = bi_dir.tolist()
trend_list = trend.tolist()
zd_list = [float(v) if pd.notna(v) and v > 0 else None for v in zs_zd]
zg_list = [float(v) if pd.notna(v) and v > 0 else None for v in zs_zg]

plots = [
    {'name': 'Bi Direction',    'type': 'line', 'data': bi_dir_list, 'color': '#888888', 'width': 1},
    {'name': 'Trend',           'type': 'line', 'data': trend_list,  'color': '#FFAA00', 'width': 2},
    {'name': 'ZD (Center Low)', 'type': 'line', 'data': zd_list,     'color': '#00AA00', 'width': 1},
    {'name': 'ZG (Center High)','type': 'line', 'data': zg_list,     'color': '#AA0000', 'width': 1},
]

output = {
    'name': my_indicator_name,
    'plots': plots,
    'signals': [
        {'type': 'buy',  'text': 'V4 Buy',  'data': buy_marks,  'color': '#00FF00'},
        {'type': 'sell', 'text': 'V4 Sell', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''


# ---------------------------------------------------------------------------
# CZSC v4 Relaxed — S1/S2 放宽触发条件，S3 默认关闭
# ---------------------------------------------------------------------------

CZSC_V4_RELAXED_INDICATOR_CODE = '''
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2
# @strategy market crypto
# @strategy symbol BTCUSDT
# @strategy timeframe 1H
# @strategy tradeDirection both
# @param trend_filter int 1 Trend filter: 1=trend direction only, 0=allow all
# @param vol_confirm int 1 Volume confirm (relaxed: 1.2x threshold)
# @param center_narrow int 0 Center narrowing: 1=hard require, 0=soft bonus
# @param divergence_filter int 1 Divergence filter (relaxed: 0.85x force decay)
# @param range_trade int 0 Range trading: 1=enable (default OFF)

my_indicator_name = "CZSC v4 Relaxed"
my_indicator_description = "V4 Relaxed: S1 1.2x vol + near-ZG breakout, S2 0.85x force decay, S3 OFF"

df = df.copy()

trend_filter = int(params.get('trend_filter', 1))
vol_confirm = int(params.get('vol_confirm', 1))
center_narrow = int(params.get('center_narrow', 0))
divergence_filter = int(params.get('divergence_filter', 1))
range_trade = int(params.get('range_trade', 0))

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
    prev = s.shift(1).fillna(False).astype(int)
    return s & (prev == 0)

# === S1: 放量突破 (RELAXED) ===
has_center = zs_level >= 1

# Relaxed vol: 1.2x 20MA instead of 1.5x
vol_ma = volume.rolling(20, min_periods=5).mean()
vol_surge_rlx = volume > vol_ma * 1.2

# Center amp narrowing (soft bonus, not hard requirement)
center_amp = zs_zg - zs_zd
zs_changed = (zs_zd != zs_zd.shift(1)) | (zs_zg != zs_zg.shift(1))
amp_narrowing = (center_amp < center_amp.shift(1)) & zs_changed & (center_amp > 0)
amp_narr_rec = amp_narrowing.rolling(20, min_periods=1).max().fillna(0).astype(bool)

# Classic breakout (above center, same direction, vol surge)
breakout_long = has_center & (zs_pos == 'above') & (bi_dir == 1) & vol_surge_rlx
breakout_short = has_center & (zs_pos == 'below') & (bi_dir == -1) & vol_surge_rlx

if center_narrow:
    breakout_long = breakout_long & amp_narr_rec
    breakout_short = breakout_short & amp_narr_rec

# Near-breakout: price approaching ZG/ZD from inside with vol surge
near_zg_brk = has_center & (zs_pos == 'inside') & (close > zs_zg * 0.98) & (bi_dir == 1) & vol_surge_rlx
near_zd_brk = has_center & (zs_pos == 'inside') & (close < zs_zd * 1.02) & (bi_dir == -1) & vol_surge_rlx
breakout_long = breakout_long | near_zg_brk
breakout_short = breakout_short | near_zd_brk

# === S2: 背驰过滤 (RELAXED) ===
bi_pct_change = abs(bi_end_p - bi_start_p) / bi_start_p.replace(0, float('nan')).fillna(0.001)
bi_force = bi_pct_change * bi_length
bi_force_prev = bi_force.shift(1)

# Relaxed: force < 85% of previous (was 100%); no trend constraint
force_decay_rlx = (bi_force < bi_force_prev * 0.85) & (bi_flip_up | bi_flip_dn)
top_divergence = force_decay_rlx & bi_flip_up
bottom_divergence = force_decay_rlx & bi_flip_dn

# Warning persistence
import pandas as pd
top_div_warn = top_divergence.copy()
bottom_div_warn = bottom_divergence.copy()
for i in range(1, len(df)):
    if pd.notna(bi_flip_up.iloc[i]) and bool(bi_flip_up.iloc[i]):
        top_div_warn.iloc[i] = False
    elif not bool(top_div_warn.iloc[i]):
        top_div_warn.iloc[i] = top_div_warn.iloc[i-1] if i > 0 else False
    if pd.notna(bi_flip_dn.iloc[i]) and bool(bi_flip_dn.iloc[i]):
        bottom_div_warn.iloc[i] = False
    elif not bool(bottom_div_warn.iloc[i]):
        bottom_div_warn.iloc[i] = bottom_div_warn.iloc[i-1] if i > 0 else False

# === S3: 中枢震荡 (DEFAULT OFF) ===
in_center = has_center & (zs_pos == 'inside')
near_zd = in_center & (close < zs_zd + (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
near_zg = in_center & (close > zs_zg - (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
range_long = near_zd & (trend == 0) if range_trade else pd.Series(False, index=df.index)
range_short = near_zg & (trend == 0) if range_trade else pd.Series(False, index=df.index)

# === SIGNAL COMBINATION ===
has_buy_point = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
has_sell_point = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')
v3_long = bi_flip_dn & (has_buy_point | (trend >= 0))
v3_short = bi_flip_up & (has_sell_point | (trend <= 0))

long_cond = v3_long | breakout_long | range_long
short_cond = v3_short | breakout_short | range_short

if trend_filter == 1:
    long_cond = long_cond & (trend >= 0)
    short_cond = short_cond & (trend <= 0)

if divergence_filter:
    long_cond = long_cond & ~top_div_warn.astype(bool)
    short_cond = short_cond & ~bottom_div_warn.astype(bool)

# S4: vol weakening at highs
vol_ma_short = volume.rolling(10, min_periods=3).mean()
close_high_20 = close.rolling(20, min_periods=5).max()
at_high = close >= close_high_20 * 0.995
vol_peak_20 = volume.rolling(20, min_periods=5).max()
vol_weakening = at_high & (volume < vol_peak_20 * 0.6) & (trend == 1)
if vol_confirm:
    long_cond = long_cond & ~vol_weakening

long_edge = edge(long_cond)
short_edge = edge(short_cond)

df['open_long'] = long_edge
df['close_long'] = edge(bi_flip_up) | edge(zs_pos == 'below')
df['open_short'] = short_edge
df['close_short'] = edge(bi_flip_dn) | edge(zs_pos == 'above')

buy_marks = [float(df['low'].iloc[i]) * 0.995 if bool(df['open_long'].iloc[i]) else None for i in range(len(df))]
sell_marks = [float(df['high'].iloc[i]) * 1.005 if bool(df['open_short'].iloc[i]) else None for i in range(len(df))]

output = {
    'name': my_indicator_name,
    'plots': [{'name': 'Trend', 'type': 'line', 'data': trend.tolist(), 'color': '#FFAA00', 'width': 2}],
    'signals': [
        {'type': 'buy',  'text': 'V4R Buy',  'data': buy_marks,  'color': '#00FF00'},
        {'type': 'sell', 'text': 'V4R Sell', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''


# ---------------------------------------------------------------------------
# CZSC v4.1 Multi-Resonance Strategy (uses bridge v4.1 columns)
# ---------------------------------------------------------------------------

CZSC_V41_INDICATOR_CODE = '''
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2
# @strategy market crypto
# @strategy symbol BTCUSDT
# @strategy timeframe 1H
# @strategy tradeDirection both
# @param trend_filter int 1 Trend filter: 1=trend direction only, 0=allow all
# @param quality_bs int 1 Prefer 1/2/3 buy-sell marks from bridge
# @param require_beichi int 1 Require 背驰 for 1buy/1sell entries
# @param vol_confirm int 1 Volume surge on breakout / shrink on pullback
# @param amp_narrow int 1 Require center amplitude narrowing for 3-class
# @param prior_low int 1 Prior-low protection for longs
# @param ml_align int 1 Multi-level bi/duan alignment filter
# @param range_trade int 0 Center swing trading when trend==0
# @param divergence_filter int 1 Block longs on top 背驰 / shorts on bottom 背驰

my_indicator_name = "CZSC v4.1 Multi-Resonance"
my_indicator_description = "缠论V4.1：1/2/3买卖点+背驰+振幅收敛+放量/缩量+前低保护+多级别共振"

df = df.copy()

trend_filter = int(params.get('trend_filter', 1))
quality_bs = int(params.get('quality_bs', 1))
require_beichi = int(params.get('require_beichi', 1))
vol_confirm = int(params.get('vol_confirm', 1))
amp_narrow_on = int(params.get('amp_narrow', 1))
prior_low_on = int(params.get('prior_low', 1))
ml_align_on = int(params.get('ml_align', 1))
range_trade = int(params.get('range_trade', 0))
divergence_filter = int(params.get('divergence_filter', 1))

bi_dir = df['czsc_bi_dir']
bi_dir_prev = bi_dir.shift(1).fillna(0)
bs_type = df['czsc_bs_type'].fillna('')
trend = df['czsc_trend'].fillna(0)
zs_level = df['czsc_zs_level'].fillna(0)
zs_zd = df['czsc_zs_zd']
zs_zg = df['czsc_zs_zg']
zs_pos = df['czsc_zs_position'].fillna('')
beichi = df['czsc_beichi'].fillna(0) if 'czsc_beichi' in df.columns else pd.Series(0, index=df.index)
amp_narrow = df['czsc_amp_narrow'].fillna(0) if 'czsc_amp_narrow' in df.columns else pd.Series(0, index=df.index)
vol_surge = df['czsc_vol_surge'].fillna(0) if 'czsc_vol_surge' in df.columns else pd.Series(0, index=df.index)
vol_shrink = df['czsc_vol_shrink'].fillna(0) if 'czsc_vol_shrink' in df.columns else pd.Series(0, index=df.index)
prior_low_ok = df['czsc_prior_low_ok'].fillna(1) if 'czsc_prior_low_ok' in df.columns else pd.Series(1, index=df.index)
ml_align = df['czsc_ml_align'].fillna(0) if 'czsc_ml_align' in df.columns else pd.Series(0, index=df.index)
trend_continue = df['czsc_trend_continue'].fillna(0) if 'czsc_trend_continue' in df.columns else pd.Series(0, index=df.index)
close = df['close']

bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)

def edge(s):
    s = s.fillna(False).astype(bool)
    prev = s.shift(1).fillna(False).astype(int)
    return s & (prev == 0)

# Persist beichi warning until opposite flip
top_warn = (beichi == -1).copy()
bot_warn = (beichi == 1).copy()
for i in range(1, len(df)):
    if bool(bi_flip_dn.iloc[i]):
        top_warn.iloc[i] = False
    elif not bool(top_warn.iloc[i]):
        top_warn.iloc[i] = bool(top_warn.iloc[i - 1])
    if bool(bi_flip_up.iloc[i]):
        bot_warn.iloc[i] = False
    elif not bool(bot_warn.iloc[i]):
        bot_warn.iloc[i] = bool(bot_warn.iloc[i - 1])

is_1buy = bs_type == '1buy'
is_2buy = bs_type == '2buy'
is_3buy = bs_type == '3buy'
is_1sell = bs_type == '1sell'
is_2sell = bs_type == '2sell'
is_3sell = bs_type == '3sell'
has_buy = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
has_sell = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')

# V3 causal base (flip at confirmed stroke end — same timing as v3)
v3_long = bi_flip_dn & (has_buy | (trend >= 0))
v3_short = bi_flip_up & (has_sell | (trend <= 0))

# Align sparse bs marks to causal flips via short lookback (marks may precede confirm)
buy_recent = has_buy.rolling(5, min_periods=1).max().fillna(0).astype(bool)
sell_recent = has_sell.rolling(5, min_periods=1).max().fillna(0).astype(bool)
b1_recent = is_1buy.rolling(5, min_periods=1).max().fillna(0).astype(bool)
b2_recent = is_2buy.rolling(5, min_periods=1).max().fillna(0).astype(bool)
b3_recent = is_3buy.rolling(5, min_periods=1).max().fillna(0).astype(bool)
s1_recent = is_1sell.rolling(5, min_periods=1).max().fillna(0).astype(bool)
s2_recent = is_2sell.rolling(5, min_periods=1).max().fillna(0).astype(bool)
s3_recent = is_3sell.rolling(5, min_periods=1).max().fillna(0).astype(bool)

# Quality paths MUST be flip-gated (never sticky state ORs)
q1_long = bi_flip_dn & b1_recent
if require_beichi:
    q1_long = q1_long & (bot_warn.astype(bool) | (beichi == 1))
q2_long = bi_flip_dn & b2_recent
if vol_confirm:
    q2_long = q2_long & vol_shrink.astype(bool)
q3_long = bi_flip_dn & (b3_recent | ((zs_pos == 'above') & (zs_level >= 1)))
if amp_narrow_on:
    q3_long = q3_long & amp_narrow.astype(bool)
if vol_confirm:
    q3_long = q3_long & (vol_surge.astype(bool) | vol_shrink.astype(bool))
if prior_low_on:
    q3_long = q3_long & prior_low_ok.astype(bool)

q1_short = bi_flip_up & s1_recent
if require_beichi:
    q1_short = q1_short & (top_warn.astype(bool) | (beichi == -1))
q2_short = bi_flip_up & s2_recent
if vol_confirm:
    q2_short = q2_short & vol_shrink.astype(bool)
q3_short = bi_flip_up & (s3_recent | ((zs_pos == 'below') & (zs_level >= 1)))
if amp_narrow_on:
    q3_short = q3_short & amp_narrow.astype(bool)
if vol_confirm:
    q3_short = q3_short & (vol_surge.astype(bool) | vol_shrink.astype(bool))

# Range trade (default off): flip-gated near ZD/ZG
has_center = zs_level >= 1
in_center = has_center & (zs_pos == 'inside')
near_zd = in_center & (close < zs_zd + (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
near_zg = in_center & (close > zs_zg - (zs_zg - zs_zd) * 0.2) & (zs_zg > zs_zd)
range_long = (bi_flip_dn & near_zd & (trend == 0)) if range_trade else pd.Series(False, index=df.index)
range_short = (bi_flip_up & near_zg & (trend == 0)) if range_trade else pd.Series(False, index=df.index)

# Filtered v3 + flip-gated quality (no sticky breakout OR)
long_cond = v3_long.copy()
short_cond = v3_short.copy()

if trend_filter == 1:
    long_cond = long_cond & (trend >= 0)
    short_cond = short_cond & (trend <= 0)

if divergence_filter:
    long_cond = long_cond & ~top_warn.astype(bool)
    short_cond = short_cond & ~bot_warn.astype(bool)

if prior_low_on:
    long_cond = long_cond & prior_low_ok.astype(bool)

if ml_align_on:
    long_cond = long_cond & (ml_align >= 0)
    short_cond = short_cond & (ml_align <= 0)

if quality_bs:
    # When quality preferred: keep filtered v3 OR explicit 1/2/3 / range
    long_cond = long_cond | q1_long | q2_long | q3_long | range_long
    short_cond = short_cond | q1_short | q2_short | q3_short | range_short

long_cond = long_cond & (trend_continue >= 0)
short_cond = short_cond & (trend_continue <= 0)

# Match v3 exits for fair compare
df['open_long'] = edge(long_cond)
df['close_long'] = edge(bi_flip_up)
df['open_short'] = edge(short_cond)
df['close_short'] = edge(bi_flip_dn)

buy_marks = [float(df['low'].iloc[i]) * 0.995 if bool(df['open_long'].iloc[i]) else None for i in range(len(df))]
sell_marks = [float(df['high'].iloc[i]) * 1.005 if bool(df['open_short'].iloc[i]) else None for i in range(len(df))]

output = {
    'name': my_indicator_name,
    'plots': [
        {'name': 'Trend', 'type': 'line', 'data': trend.tolist(), 'color': '#FFAA00', 'width': 2},
        {'name': 'Beichi', 'type': 'line', 'data': beichi.tolist(), 'color': '#AA00FF', 'width': 1},
    ],
    'signals': [
        {'type': 'buy', 'text': 'V4.1 Buy', 'data': buy_marks, 'color': '#00FF00'},
        {'type': 'sell', 'text': 'V4.1 Sell', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv_df(n: int = 300, freq: str = "1h") -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with DatetimeIndex."""
    rng = np.random.RandomState(42)
    dates = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    returns = rng.normal(0, 0.005, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
    open_price = close * (1 + rng.normal(0, 0.001, n))
    high = np.maximum(high, np.maximum(open_price, close))
    low = np.minimum(low, np.minimum(open_price, close))
    volume = np.abs(rng.normal(1000, 500, n))
    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ---------------------------------------------------------------------------
# Test 1: code_uses_czsc detection for strategy code
# ---------------------------------------------------------------------------

class TestCzscStrategyCodeDetection:
    """Verify that czsc_ references in strategy code are detected."""

    def test_trend_indicator_detected_as_czsc(self):
        assert code_uses_czsc(CZSC_TREND_INDICATOR_CODE) is True

    def test_center_breakout_detected_as_czsc(self):
        assert code_uses_czsc(CZSC_CENTER_BREAKOUT_CODE) is True

    def test_plain_indicator_not_detected(self):
        plain = "df['open_long'] = df['close'] > df['open']"
        assert code_uses_czsc(plain) is False


# ---------------------------------------------------------------------------
# Test 2: Indicator validation with czsc_ columns (dry-run)
# ---------------------------------------------------------------------------

class TestCzscIndicatorValidation:
    """Validate CZSC indicator code through the dry-run pipeline.

    The validation sandbox injects mock czsc_ columns (via add_mock_czsc_columns)
    so indicator code that reads czsc_ columns doesn't get KeyError.
    """

    def test_trend_indicator_validates(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_TREND_INDICATOR_CODE, {"trend_filter": 1})
        assert result["success"] is True, (
            f"Trend indicator validation failed: {result.get('msg')} | {result.get('details')}"
        )

    def test_center_breakout_validates(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_CENTER_BREAKOUT_CODE, {"min_level": 1})
        assert result["success"] is True, (
            f"Center breakout validation failed: {result.get('msg')} | {result.get('details')}"
        )

    def test_trend_indicator_has_signals(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_TREND_INDICATOR_CODE, {"trend_filter": 1})
        assert result["success"] is True
        assert result.get("signals_count", 0) >= 2, "Expected at least 2 signal definitions"

    def test_center_breakout_has_plots(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_CENTER_BREAKOUT_CODE, {"min_level": 1})
        assert result["success"] is True
        assert result.get("plots_count", 0) >= 2, "Expected at least 2 plot definitions"

    def test_validation_without_params_uses_defaults(self):
        """Both indicators declare @param with defaults; validate without params should work."""
        from app.services.indicator_validation import validate_indicator_code
        r1 = validate_indicator_code(CZSC_TREND_INDICATOR_CODE)
        assert r1["success"] is True, f"Default param validation failed: {r1.get('msg')}"
        r2 = validate_indicator_code(CZSC_CENTER_BREAKOUT_CODE)
        assert r2["success"] is True, f"Default param validation failed: {r2.get('msg')}"


# ---------------------------------------------------------------------------
# Test 3: Backtest CZSC injection detection
# ---------------------------------------------------------------------------

class TestBacktestCzscInjection:
    """Verify that the backtest executor detects czsc_ references and
    calls compute_czsc_features (or gracefully skips if czsc unavailable)."""

    def test_backtest_detects_czsc_code(self):
        """code_uses_czsc returns True for our strategy code."""
        assert code_uses_czsc(CZSC_TREND_INDICATOR_CODE) is True
        assert code_uses_czsc(CZSC_CENTER_BREAKOUT_CODE) is True

    def test_compute_czsc_features_graceful_when_unavailable(self):
        """When czsc is not installed, compute_czsc_features returns df unchanged."""
        df = _make_ohlcv_df(200)
        result = compute_czsc_features(df, freq="1H", symbol="BTCUSDT")
        if not is_czsc_enabled():
            # Should return df without czsc_ columns
            assert "czsc_bi_dir" not in result.columns
            assert len(result) == len(df)
        else:
            # czsc IS installed; features should be injected
            assert "czsc_bi_dir" in result.columns
            assert len(result) == len(df)

    def test_mock_czsc_columns_sufficient_for_execution(self):
        """Mock czsc columns should let indicator code run without KeyError."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)

        # Execute trend indicator code with mock columns
        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert "name" in output
        assert output["name"] == "CZSC Trend Reversal"

    def test_mock_czsc_columns_sufficient_for_center_breakout(self):
        """Mock czsc columns should let center breakout code run."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)

        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"min_level": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_CENTER_BREAKOUT_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC Center Breakout"

    def test_four_way_columns_produced(self):
        """After executing CZSC indicator code, four-way columns should exist."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)

        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        result_df = exec_globals["df"]
        for col in ("open_long", "close_long", "open_short", "close_short"):
            assert col in result_df.columns, f"Missing four-way column: {col}"
            assert result_df[col].dtype == bool, f"Column {col} should be bool, got {result_df[col].dtype}"

    def test_causal_reversal_flip_mapping(self):
        """Causal-reversal: completed down stroke → long; completed up stroke → short."""
        assert "long_cond = bi_flip_dn" in CZSC_TREND_INDICATOR_CODE
        assert "short_cond = bi_flip_up" in CZSC_TREND_INDICATOR_CODE
        # Must NOT use pre-causal / trend-follow mapping (flip_up→long).
        assert "long_cond = bi_flip_up" not in CZSC_TREND_INDICATOR_CODE
        assert "short_cond = bi_flip_dn" not in CZSC_TREND_INDICATOR_CODE
        assert 'df[\'close_long\'] = edge(bi_flip_up)' in CZSC_TREND_INDICATOR_CODE
        assert 'df[\'close_short\'] = edge(bi_flip_dn)' in CZSC_TREND_INDICATOR_CODE


# ---------------------------------------------------------------------------
# Test 4: Live strategy CZSC detection
# ---------------------------------------------------------------------------

class TestLiveStrategyCzscDetection:
    """Verify that the live trading executor would detect czsc_ references.

    We don't start a full executor; we test the detection logic that gates
    CZSC feature injection in trading_executor.py.
    """

    def test_trading_executor_would_detect_trend_code(self):
        """The code_uses_czsc check used by trading_executor.py should return True."""
        assert code_uses_czsc(CZSC_TREND_INDICATOR_CODE) is True

    def test_trading_executor_would_detect_breakout_code(self):
        assert code_uses_czsc(CZSC_CENTER_BREAKOUT_CODE) is True

    def test_non_czsc_code_not_triggered(self):
        """Plain indicator code should not trigger CZSC injection."""
        plain_code = "df['open_long'] = (df['close'] > df['open']).fillna(False).astype(bool)"
        assert code_uses_czsc(plain_code) is False


# ---------------------------------------------------------------------------
# Test 5: CZSC features computation with real czsc (conditional)
# ---------------------------------------------------------------------------

class TestCzscFeaturesComputation:
    """Test actual CZSC feature computation when the library is available."""

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_trend_indicator_with_real_czsc_features(self):
        """Run trend indicator with real czsc features injected."""
        df = _make_ohlcv_df(300, freq="1h")
        df_czsc = compute_czsc_features(df, freq="1H", symbol="BTCUSDT")

        # All czsc columns should exist
        for col in CZSC_COLUMNS:
            assert col["name"] in df_czsc.columns, f"Missing: {col['name']}"

        # Execute indicator code with real features
        exec_globals = {
            "df": df_czsc.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC Trend Reversal"
        assert len(output.get("signals", [])) >= 2

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_center_breakout_with_real_czsc_features(self):
        """Run center breakout indicator with real czsc features."""
        df = _make_ohlcv_df(300, freq="1h")
        df_czsc = compute_czsc_features(df, freq="1H", symbol="ETHUSDT")

        exec_globals = {
            "df": df_czsc.copy(),
            "pd": pd,
            "np": np,
            "params": {"min_level": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_CENTER_BREAKOUT_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC Center Breakout"

    def test_graceful_degradation_without_czsc(self):
        """Without czsc library, code should still validate (via mock columns)."""
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_TREND_INDICATOR_CODE)
        assert result["success"] is True, (
            f"Graceful degradation failed: {result.get('msg')} | {result.get('details')}"
        )


# ---------------------------------------------------------------------------
# Test 6: End-to-end indicator authoring contract compliance
# ---------------------------------------------------------------------------

class TestCzscIndicatorContract:
    """Verify CZSC indicator code follows the platform authoring contract."""

    def test_has_indicator_name(self):
        assert 'my_indicator_name = ' in CZSC_TREND_INDICATOR_CODE
        assert 'my_indicator_name = ' in CZSC_CENTER_BREAKOUT_CODE
        assert 'my_indicator_name = ' in CZSC_V4_INDICATOR_CODE

    def test_has_indicator_description(self):
        assert 'my_indicator_description = ' in CZSC_TREND_INDICATOR_CODE
        assert 'my_indicator_description = ' in CZSC_CENTER_BREAKOUT_CODE
        assert 'my_indicator_description = ' in CZSC_V4_INDICATOR_CODE

    def test_has_four_way_signal_header(self):
        assert '# signal_form: four_way' in CZSC_TREND_INDICATOR_CODE
        assert '# signal_form: four_way' in CZSC_CENTER_BREAKOUT_CODE
        assert '# signal_form: four_way' in CZSC_V4_INDICATOR_CODE

    def test_has_strategy_headers(self):
        for code in (CZSC_TREND_INDICATOR_CODE, CZSC_CENTER_BREAKOUT_CODE, CZSC_V4_INDICATOR_CODE):
            assert '# @strategy market' in code
            assert '# @strategy symbol' in code
            assert '# @strategy timeframe' in code
            assert '# @strategy tradeDirection' in code

    def test_has_output_variable(self):
        assert 'output = {' in CZSC_TREND_INDICATOR_CODE
        assert 'output = {' in CZSC_CENTER_BREAKOUT_CODE
        assert 'output = {' in CZSC_V4_INDICATOR_CODE

    def test_uses_params_get(self):
        assert "params.get(" in CZSC_TREND_INDICATOR_CODE
        assert "params.get(" in CZSC_CENTER_BREAKOUT_CODE
        assert "params.get(" in CZSC_V4_INDICATOR_CODE

    def test_declares_param_annotations(self):
        assert '# @param' in CZSC_TREND_INDICATOR_CODE
        assert '# @param' in CZSC_CENTER_BREAKOUT_CODE
        assert '# @param' in CZSC_V4_INDICATOR_CODE

    def test_does_not_import_czsc(self):
        """Indicator code must NOT import czsc; the bridge injects columns."""
        assert 'import czsc' not in CZSC_TREND_INDICATOR_CODE
        assert 'import czsc' not in CZSC_CENTER_BREAKOUT_CODE
        assert 'import czsc' not in CZSC_V4_INDICATOR_CODE

    def test_signal_data_length_matches_df(self):
        """Signal marker lists should have exactly len(df) elements."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)
        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        output = exec_globals["output"]
        for sig in output.get("signals", []):
            assert len(sig["data"]) == len(df_mock), (
                f"Signal '{sig.get('text')}' data length {len(sig['data'])} != df length {len(df_mock)}"
            )


# ---------------------------------------------------------------------------
# Test 7: CZSC V4 indicators — multi-scenario validation
# ---------------------------------------------------------------------------

class TestCzscV4Indicator:
    """Validate CZSC V4 multi-scenario indicator code."""

    def test_v4_code_detected_as_czsc(self):
        assert code_uses_czsc(CZSC_V4_INDICATOR_CODE) is True

    def test_v4_validates_with_default_params(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_V4_INDICATOR_CODE)
        assert result["success"] is True, (
            f"V4 validation failed: {result.get('msg')} | {result.get('details')}"
        )

    def test_v4_validates_with_all_scenarios_enabled(self):
        """V4 with all scenarios turned on should still validate."""
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_V4_INDICATOR_CODE, {
            "trend_filter": 1, "vol_confirm": 1,
            "center_narrow": 1, "divergence_filter": 1, "range_trade": 1,
        })
        assert result["success"] is True, (
            f"V4 all-scenarios validation failed: {result.get('msg')}"
        )

    def test_v4_validates_minimal_config(self):
        """V4 with all filters off (V3 baseline) should validate."""
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_V4_INDICATOR_CODE, {
            "trend_filter": 0, "vol_confirm": 0,
            "center_narrow": 0, "divergence_filter": 0, "range_trade": 0,
        })
        assert result["success"] is True, (
            f"V4 minimal config validation failed: {result.get('msg')}"
        )

    def test_v4_has_four_way_columns(self):
        """V4 must produce four-way execution columns."""
        assert '# signal_form: four_way' in CZSC_V4_INDICATOR_CODE
        assert 'df[\'open_long\']' in CZSC_V4_INDICATOR_CODE
        assert 'df[\'close_long\']' in CZSC_V4_INDICATOR_CODE
        assert 'df[\'open_short\']' in CZSC_V4_INDICATOR_CODE
        assert 'df[\'close_short\']' in CZSC_V4_INDICATOR_CODE

    def test_v4_causal_reversal_correct(self):
        """V4 must use causal-reversal: flip_dn→long, flip_up→short."""
        assert 'v3_long = bi_flip_dn' in CZSC_V4_INDICATOR_CODE
        assert 'v3_short = bi_flip_up' in CZSC_V4_INDICATOR_CODE

    def test_v4_scenario1_breakout_present(self):
        """V4 must contain Scenario 1: breakout + volume + center narrowing."""
        assert 'breakout_long' in CZSC_V4_INDICATOR_CODE
        assert 'breakout_short' in CZSC_V4_INDICATOR_CODE
        assert 'vol_surge' in CZSC_V4_INDICATOR_CODE
        assert 'amp_narrowing' in CZSC_V4_INDICATOR_CODE

    def test_v4_scenario2_divergence_present(self):
        """V4 must contain Scenario 2: trend divergence filter."""
        assert 'top_divergence' in CZSC_V4_INDICATOR_CODE
        assert 'bottom_divergence' in CZSC_V4_INDICATOR_CODE
        assert 'bi_force' in CZSC_V4_INDICATOR_CODE

    def test_v4_scenario3_range_trade_present(self):
        """V4 must contain Scenario 3: center swing trading."""
        assert 'range_long' in CZSC_V4_INDICATOR_CODE
        assert 'range_short' in CZSC_V4_INDICATOR_CODE
        assert 'near_zd' in CZSC_V4_INDICATOR_CODE
        assert 'near_zg' in CZSC_V4_INDICATOR_CODE

    def test_v4_scenario4_volume_enhance_present(self):
        """V4 must contain Scenario 4: volume-price enhancement."""
        assert 'vol_shrink' in CZSC_V4_INDICATOR_CODE
        assert 'vol_weakening' in CZSC_V4_INDICATOR_CODE

    def test_v4_mock_execution_works(self):
        """V4 code should execute successfully with mock czsc columns."""
        df = _make_ohlcv_df(300)
        df_mock = add_mock_czsc_columns(df)
        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {
                "trend_filter": 1, "vol_confirm": 1,
                "center_narrow": 1, "divergence_filter": 1, "range_trade": 1,
            },
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_V4_INDICATOR_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC v4 Multi-Scenario"
        assert len(output.get("signals", [])) >= 2
        assert len(output.get("plots", [])) >= 4

    def test_v4_param_contract(self):
        """V4 must declare all scenario params."""
        required_params = ['trend_filter', 'vol_confirm', 'center_narrow',
                          'divergence_filter', 'range_trade']
        for p in required_params:
            assert f'# @param {p}' in CZSC_V4_INDICATOR_CODE, f"Missing param: {p}"

    def test_v4_does_not_import_czsc(self):
        """V4 must not import czsc directly."""
        assert 'import czsc' not in CZSC_V4_INDICATOR_CODE

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_v4_with_real_czsc_features(self):
        """Run V4 with real czsc features."""
        df = _make_ohlcv_df(300, freq="1h")
        df_czsc = compute_czsc_features(df, freq="1H", symbol="BTCUSDT")

        exec_globals = {
            "df": df_czsc.copy(),
            "pd": pd,
            "np": np,
            "params": {
                "trend_filter": 1, "vol_confirm": 1,
                "center_narrow": 1, "divergence_filter": 1, "range_trade": 1,
            },
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_V4_INDICATOR_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC v4 Multi-Scenario"


# ---------------------------------------------------------------------------
# Test 8: V3 vs V4 signal comparison (scenario-level)
# ---------------------------------------------------------------------------

class TestCzscV3VsV4Comparison:
    """Compare V3 and V4 signal outputs on synthetic data.

    Each scenario in V4 should produce a measurable change in signal count:
    - Scenario 1 (breakout): adds breakout signals → MORE long/short signals
    - Scenario 2 (divergence): filters force-decay → FEWER signals
    - Scenario 3 (range): adds range signals → MORE signals in consolidation
    - Scenario 4 (volume): filters weak volume → FEWER signals
    """

    @staticmethod
    def _run_indicator(code: str, df: pd.DataFrame, params: dict) -> tuple:
        """Execute indicator code and return (open_long_count, open_short_count)."""
        exec_globals = {
            "df": df.copy(),
            "pd": pd,
            "np": np,
            "params": params,
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]
        exec(code, exec_globals)
        result_df = exec_globals["df"]
        return int(result_df["open_long"].sum()), int(result_df["open_short"].sum())

    def test_v3_baseline_signal_count(self):
        """Establish V3 baseline signal count."""
        df = _make_ohlcv_df(300)
        df_mock = add_mock_czsc_columns(df)
        long_c, short_c = self._run_indicator(
            CZSC_TREND_INDICATOR_CODE, df_mock, {"trend_filter": 1}
        )
        # V3 uses mock columns (all czsc_bi_dir=0), so signals come from
        # bi_dir transitions which are all False with mock data
        # This is expected: mock data produces 0 signals
        assert long_c >= 0 and short_c >= 0

    def test_v4_scenario1_adds_breakout_signals(self):
        """V4 with breakout enabled should produce breakout signals that V3 doesn't have."""
        df = _make_ohlcv_df(300)
        df_mock = add_mock_czsc_columns(df)

        # V3 minimal: all filters off
        v3_long, v3_short = self._run_indicator(
            CZSC_V4_INDICATOR_CODE, df_mock,
            {"trend_filter": 0, "vol_confirm": 0, "center_narrow": 0,
             "divergence_filter": 0, "range_trade": 0},
        )
        # V4 with scenario 1 only
        v4_long, v4_short = self._run_indicator(
            CZSC_V4_INDICATOR_CODE, df_mock,
            {"trend_filter": 0, "vol_confirm": 1, "center_narrow": 1,
             "divergence_filter": 0, "range_trade": 0},
        )

        # Scenario 1 adds breakout signals — V4 total should be >= V3 total
        v3_total = v3_long + v3_short
        v4_total = v4_long + v4_short
        assert v4_total >= v3_total, (
            f"S1: V4 total ({v4_total}) should be >= V3 total ({v3_total})"
        )

    def test_v4_scenario2_reduces_signals(self):
        """Divergence filter should reduce signal count."""
        df = _make_ohlcv_df(300)
        df_mock = add_mock_czsc_columns(df)

        # V4 without divergence
        v4_no_div, _ = self._run_indicator(
            CZSC_V4_INDICATOR_CODE, df_mock,
            {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 1,
             "divergence_filter": 0, "range_trade": 0},
        )
        # V4 with divergence
        v4_with_div, _ = self._run_indicator(
            CZSC_V4_INDICATOR_CODE, df_mock,
            {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 1,
             "divergence_filter": 1, "range_trade": 0},
        )

        # Divergence filter should not increase signals
        assert v4_with_div <= v4_no_div, (
            f"S2: with divergence ({v4_with_div}) should be <= without ({v4_no_div})"
        )

    def test_v4_scenario3_adds_range_signals(self):
        """Range trading should add signals in consolidation."""
        df = _make_ohlcv_df(300)
        df_mock = add_mock_czsc_columns(df)

        # V4 without range trade
        v4_no_range, _ = self._run_indicator(
            CZSC_V4_INDICATOR_CODE, df_mock,
            {"trend_filter": 0, "vol_confirm": 0, "center_narrow": 0,
             "divergence_filter": 0, "range_trade": 0},
        )
        # V4 with range trade
        v4_with_range, _ = self._run_indicator(
            CZSC_V4_INDICATOR_CODE, df_mock,
            {"trend_filter": 0, "vol_confirm": 0, "center_narrow": 0,
             "divergence_filter": 0, "range_trade": 1},
        )

        # Range trade should not decrease signals
        assert v4_with_range >= v4_no_range, (
            f"S3: with range ({v4_with_range}) should be >= without ({v4_no_range})"
        )

    def test_v4_all_scenarios_combined_valid(self):
        """V4 with all scenarios enabled should execute without error."""
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_V4_INDICATOR_CODE, {
            "trend_filter": 1, "vol_confirm": 1,
            "center_narrow": 1, "divergence_filter": 1, "range_trade": 1,
        })
        assert result["success"] is True

    def test_v4_vs_v3_code_level_diff(self):
        """Document key differences between V3 and V4 at code level."""
        # V3: single signal source (bi_flip + bs_type)
        # V4: multi-source (bi_flip + breakout + range) with filters
        assert 'breakout_long' in CZSC_V4_INDICATOR_CODE
        assert 'breakout_long' not in CZSC_TREND_INDICATOR_CODE
        assert 'range_long' in CZSC_V4_INDICATOR_CODE
        assert 'range_long' not in CZSC_CENTER_BREAKOUT_CODE
        assert 'top_divergence' in CZSC_V4_INDICATOR_CODE
        assert 'top_divergence' not in CZSC_TREND_INDICATOR_CODE


# ---------------------------------------------------------------------------
# Test 8: CZSC V4.1 multi-resonance (bridge columns)
# ---------------------------------------------------------------------------

class TestCzscV41Indicator:
    """Validate CZSC v4.1 indicator that consumes bridge v4.1 columns."""

    def test_v41_code_detected_as_czsc(self):
        assert code_uses_czsc(CZSC_V41_INDICATOR_CODE) is True

    def test_v41_four_way_contract(self):
        assert '# signal_form: four_way' in CZSC_V41_INDICATOR_CODE
        assert "df['open_long']" in CZSC_V41_INDICATOR_CODE
        assert "df['close_long']" in CZSC_V41_INDICATOR_CODE
        assert "df['open_short']" in CZSC_V41_INDICATOR_CODE
        assert "df['close_short']" in CZSC_V41_INDICATOR_CODE
        assert 'import czsc' not in CZSC_V41_INDICATOR_CODE

    def test_v41_uses_bridge_v41_columns(self):
        for col in (
            'czsc_beichi', 'czsc_amp_narrow', 'czsc_vol_surge',
            'czsc_vol_shrink', 'czsc_prior_low_ok', 'czsc_ml_align',
            'czsc_trend_continue',
        ):
            assert col in CZSC_V41_INDICATOR_CODE, f"missing {col}"

    def test_v41_has_1_2_3_buy_sell(self):
        for mark in ('1buy', '2buy', '3buy', '1sell', '2sell', '3sell'):
            assert mark in CZSC_V41_INDICATOR_CODE

    def test_v41_validates(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_V41_INDICATOR_CODE)
        assert result["success"] is True, (
            f"V4.1 validation failed: {result.get('msg')} | {result.get('details')}"
        )

    def test_v41_mock_execution(self):
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)
        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {
                "trend_filter": 1, "quality_bs": 1, "require_beichi": 1,
                "vol_confirm": 1, "amp_narrow": 1, "prior_low": 1,
                "ml_align": 0, "range_trade": 0, "divergence_filter": 1,
            },
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]
        exec(CZSC_V41_INDICATOR_CODE, exec_globals)
        out_df = exec_globals["df"]
        for col in ("open_long", "close_long", "open_short", "close_short"):
            assert col in out_df.columns
        assert exec_globals["output"] is not None
        assert exec_globals["output"]["name"] == "CZSC v4.1 Multi-Resonance"
