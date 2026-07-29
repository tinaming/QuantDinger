"""
ChanLun (缠论) strategy template library for ChanQuant.

Provides pre-built IndicatorStrategy scripts that leverage pre-computed
czsc_* columns (分型、笔、段、中枢、买卖点). Each template is a complete
Python source string ready for the indicator IDE sandbox.

Usage:
    from app.services.chanlun_templates import list_templates, get_template

    templates = list_templates()       # [{id, name, description}]
    t = get_template('fx_breakout')    # {id, name, description, code} | None
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, dict] = {}


def _register(tpl: dict) -> None:
    _TEMPLATES[tpl["id"]] = tpl


# ---------------------------------------------------------------------------
# Template 1: 分型突破策略 (Fractal Breakout)
# ---------------------------------------------------------------------------

_FX_BREAKOUT_CODE = '''\
# signal_form: four_way
# exit_owner: engine
# flip_mode: R1
# @param confirm_bars int 3 分型确认所需后续K线数
# @strategy stopLossPct 0.03
# @strategy takeProfitPct 0.06
# @strategy tradeDirection both

my_indicator_name = "分型突破策略"
my_indicator_description = "底分型确认+价格突破前高做多；顶分型确认做空"

df = df.copy()

confirm_bars = int(params.get('confirm_bars', 3))

# ---------- 底分型确认（czsc_fx_mark == -1） ----------
bottom_fx = (df['czsc_fx_mark'] == -1).astype(bool)
# 底分型后连续 confirm_bars 根K线收盘价均高于分型价格 → 确认
bottom_price = df['czsc_fx_price'].where(bottom_fx)
bottom_price_filled = bottom_price.ffill()

# 底分型确认：当前收盘价高于最近底分型价格，且笔方向向上
bottom_confirmed = (
    (df['close'] > bottom_price_filled) &
    (df['czsc_bi_dir'] == 1)
)

# ---------- 顶分型确认（czsc_fx_mark == 1） ----------
top_fx = (df['czsc_fx_mark'] == 1).astype(bool)
top_price = df['czsc_fx_price'].where(top_fx)
top_price_filled = top_price.ffill()

top_confirmed = (
    (df['close'] < top_price_filled) &
    (df['czsc_bi_dir'] == -1)
)

# ---------- 四向执行信号（edge trigger） ----------
def edge(s):
    return s & ~s.shift(1).fillna(False)

df['open_long'] = edge(bottom_confirmed).astype(bool)
df['close_long'] = edge(top_confirmed).astype(bool)
df['open_short'] = edge(top_confirmed).astype(bool)
df['close_short'] = edge(bottom_confirmed).astype(bool)

# ---------- 图表输出 ----------
output = {
    'name': my_indicator_name,
    'plots': [
        {'name': '底分型价', 'data': bottom_price_filled.tolist(), 'color': '#26a69a', 'overlay': True, 'type': 'line'},
        {'name': '顶分型价', 'data': top_price_filled.tolist(), 'color': '#ef5350', 'overlay': True, 'type': 'line'},
    ],
    'signals': [
        {
            'type': 'buy',
            'text': '底分型突破',
            'color': '#26a69a',
            'data': [
                df['low'].iloc[i] * 0.995 if bool(df['open_long'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
        {
            'type': 'sell',
            'text': '顶分型突破',
            'color': '#ef5350',
            'data': [
                df['high'].iloc[i] * 1.005 if bool(df['open_short'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
    ],
}
'''

_register({
    "id": "fx_breakout",
    "name": "分型突破策略",
    "description": "底分型确认 + 价格突破前高 → 做多；顶分型确认 → 做空。适合趋势行情中的分型反转入场。",
    "code": _FX_BREAKOUT_CODE,
})


# ---------------------------------------------------------------------------
# Template 2: 中枢震荡策略 (Center Oscillation)
# ---------------------------------------------------------------------------

_ZS_OSCILLATION_CODE = '''\
# signal_form: four_way
# exit_owner: indicator
# flip_mode: R1
# @param zs_min_level int 1 中枢最低级别
# @strategy stopLossPct 0.02
# @strategy tradeDirection both

my_indicator_name = "中枢震荡策略"
my_indicator_description = "价格触及中枢下沿做多、触及上沿做空，中枢内高抛低吸"

df = df.copy()

zs_min_level = int(params.get('zs_min_level', 1))

# ---------- 有效中枢筛选 ----------
has_zs = (df['czsc_zs_level'] >= zs_min_level).astype(bool)
zs_zd = df['czsc_zs_zd'].where(has_zs).ffill()
zs_zg = df['czsc_zs_zg'].where(has_zs).ffill()
zs_mid = (zs_zd + zs_zg) / 2

# ---------- 触及中枢边界 ----------
touch_lower = (df['low'] <= zs_zd * 1.005) & has_zs   # 接近或跌破下沿
touch_upper = (df['high'] >= zs_zg * 0.995) & has_zs   # 接近或突破上沿

# 中枢内反弹 / 回落
inside_zs = (df['czsc_zs_position'] == 'inside').astype(bool)
bounce_from_lower = touch_lower & (df['close'] > zs_zd)   # 下探后收回
reject_from_upper = touch_upper & (df['close'] < zs_zg)   # 上冲后回落

# ---------- 四向执行信号 ----------
def edge(s):
    return s & ~s.shift(1).fillna(False)

df['open_long'] = edge(bounce_from_lower).astype(bool)
df['close_long'] = edge(reject_from_upper).astype(bool)
df['open_short'] = edge(reject_from_upper).astype(bool)
df['close_short'] = edge(bounce_from_lower).astype(bool)

# ---------- 图表输出 ----------
output = {
    'name': my_indicator_name,
    'plots': [
        {'name': '中枢上沿ZG', 'data': zs_zg.tolist(), 'color': '#ef5350', 'overlay': True, 'type': 'line'},
        {'name': '中枢下沿ZD', 'data': zs_zd.tolist(), 'color': '#26a69a', 'overlay': True, 'type': 'line'},
        {'name': '中枢中线', 'data': zs_mid.tolist(), 'color': '#ff9800', 'overlay': True, 'type': 'line'},
    ],
    'signals': [
        {
            'type': 'buy',
            'text': '触下沿做多',
            'color': '#26a69a',
            'data': [
                df['low'].iloc[i] * 0.995 if bool(df['open_long'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
        {
            'type': 'sell',
            'text': '触上沿做空',
            'color': '#ef5350',
            'data': [
                df['high'].iloc[i] * 1.005 if bool(df['open_short'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
    ],
    'layers': [],
}
'''

_register({
    "id": "zs_oscillation",
    "name": "中枢震荡策略",
    "description": "价格触及中枢下沿做多、触及上沿做空。适合震荡行情中的中枢区间高抛低吸。",
    "code": _ZS_OSCILLATION_CODE,
})


# ---------------------------------------------------------------------------
# Template 3: 买卖点趋势跟踪 (Buy/Sell Point Trend Following)
# ---------------------------------------------------------------------------

_BSP_TREND_CODE = '''\
# signal_form: four_way
# exit_owner: engine
# flip_mode: R1
# @param use_trend_filter bool true 仅在趋势方向开仓
# @strategy stopLossPct 0.04
# @strategy takeProfitPct 0.08
# @strategy tradeDirection both

my_indicator_name = "买卖点趋势跟踪"
my_indicator_description = "缠论第一/二/三类买点做多，对应卖点做空，可选趋势过滤"

df = df.copy()

use_trend_filter = str(params.get('use_trend_filter', 'true')).lower() in ('true', '1', 'yes')

# ---------- 买卖点识别 ----------
bs_type = df['czsc_bs_type'].astype(str).str.strip()

# 买点：1buy / 2buy / 3buy
is_buy_point = bs_type.isin(['1buy', '2buy', '3buy'])
# 卖点：1sell / 2sell / 3sell
is_sell_point = bs_type.isin(['1sell', '2sell', '3sell'])

# ---------- 趋势过滤 ----------
if use_trend_filter:
    trend = df['czsc_trend']
    # 买点仅在上涨趋势或盘整中出现；卖点仅在下跌趋势或盘整中出现
    buy_with_trend = is_buy_point & (trend >= 0)
    sell_with_trend = is_sell_point & (trend <= 0)
else:
    buy_with_trend = is_buy_point
    sell_with_trend = is_sell_point

# ---------- 四向执行信号（edge trigger） ----------
def edge(s):
    return s & ~s.shift(1).fillna(False)

df['open_long'] = edge(buy_with_trend).astype(bool)
df['close_long'] = edge(sell_with_trend).astype(bool)
df['open_short'] = edge(sell_with_trend).astype(bool)
df['close_short'] = edge(buy_with_trend).astype(bool)

# ---------- 图表输出 ----------
output = {
    'name': my_indicator_name,
    'plots': [
        {
            'name': '趋势',
            'data': df['czsc_trend'].tolist(),
            'color': '#2196f3',
            'overlay': False,
            'type': 'line',
        },
    ],
    'signals': [
        {
            'type': 'buy',
            'text': '买点',
            'color': '#26a69a',
            'data': [
                df['low'].iloc[i] * 0.995 if bool(df['open_long'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
        {
            'type': 'sell',
            'text': '卖点',
            'color': '#ef5350',
            'data': [
                df['high'].iloc[i] * 1.005 if bool(df['open_short'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
    ],
}
'''

_register({
    "id": "bsp_trend",
    "name": "买卖点趋势跟踪",
    "description": "缠论第一/二/三类买点做多，对应卖点做空。可选趋势过滤，仅在趋势方向开仓。",
    "code": _BSP_TREND_CODE,
})


# ---------------------------------------------------------------------------
# Template 4: 多级别共振策略 (Multi-Level Resonance)
# ---------------------------------------------------------------------------

_MULTI_LEVEL_RESONANCE_CODE = '''\
# signal_form: four_way
# exit_owner: engine
# flip_mode: R1
# @param big_trend_threshold int 1 大级别趋势阈值（czsc_trend绝对值>=此值视为有方向）
# @strategy stopLossPct 0.03
# @strategy takeProfitPct 0.06
# @strategy tradeDirection both

my_indicator_name = "多级别共振策略"
my_indicator_description = "大级别趋势向上+小级别买点做多；大级别下跌+小级别卖点做空"

df = df.copy()

big_trend_threshold = int(params.get('big_trend_threshold', 1))

# ---------- 大级别趋势判断（使用段方向 + 趋势分类） ----------
# czsc_trend: 1=上涨趋势, -1=下跌趋势, 0=盘整
# czsc_duan_dir: 1=上升段, -1=下降段
big_trend = df['czsc_trend']
big_duan = df['czsc_duan_dir']

big_bullish = (big_trend >= big_trend_threshold) | (big_duan == 1)
big_bearish = (big_trend <= -big_trend_threshold) | (big_duan == -1)

# ---------- 小级别入场信号（笔端点 + 买卖点） ----------
# 笔方向翻转：下降笔→上升笔 = 潜在底部
bi_dir = df['czsc_bi_dir']
bi_flip_up = (bi_dir == 1) & (bi_dir.shift(1).fillna(0) == -1)
bi_flip_down = (bi_dir == -1) & (bi_dir.shift(1).fillna(0) == 1)

# 买卖点信号
bs_type = df['czsc_bs_type'].astype(str).str.strip()
has_buy_point = bs_type.isin(['1buy', '2buy', '3buy'])
has_sell_point = bs_type.isin(['1sell', '2sell', '3sell'])

# 小级别买点 = 笔方向翻上 或 买卖点
small_buy = bi_flip_up | has_buy_point
# 小级别卖点 = 笔方向翻下 或 卖点
small_sell = bi_flip_down | has_sell_point

# ---------- 共振条件 ----------
long_entry = big_bullish & small_buy
short_entry = big_bearish & small_sell

# ---------- 四向执行信号（edge trigger） ----------
def edge(s):
    return s & ~s.shift(1).fillna(False)

df['open_long'] = edge(long_entry).astype(bool)
df['close_long'] = edge(big_bearish | small_sell).astype(bool)
df['open_short'] = edge(short_entry).astype(bool)
df['close_short'] = edge(big_bullish | small_buy).astype(bool)

# ---------- 图表输出 ----------
output = {
    'name': my_indicator_name,
    'plots': [
        {'name': '大级别趋势', 'data': big_trend.tolist(), 'color': '#2196f3', 'overlay': False, 'type': 'line'},
        {'name': '段方向', 'data': big_duan.tolist(), 'color': '#ff9800', 'overlay': False, 'type': 'line'},
    ],
    'signals': [
        {
            'type': 'buy',
            'text': '多级别共振做多',
            'color': '#26a69a',
            'data': [
                df['low'].iloc[i] * 0.995 if bool(df['open_long'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
        {
            'type': 'sell',
            'text': '多级别共振做空',
            'color': '#ef5350',
            'data': [
                df['high'].iloc[i] * 1.005 if bool(df['open_short'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
    ],
}
'''

_register({
    "id": "multi_level_resonance",
    "name": "多级别共振策略",
    "description": "大级别趋势向上 + 小级别买点做多；大级别下跌 + 小级别卖点做空。多时间框架共振确认。",
    "code": _MULTI_LEVEL_RESONANCE_CODE,
})


# ---------------------------------------------------------------------------
# Template 5: 真三买回踩确认 MVP (Leave-ZG pullback confirm)
# ---------------------------------------------------------------------------
# 窄场景：上涨语境 + 中枢离开后回踩不进中枢 + 可选收敛/放量。
# 经典三买 ≠ czsc_bs_type=='3buy'，也 ≠ 简单 zs_pos=='above' 第一次离开。
# 收敛/放量/前低在指标内自算，不依赖 bridge 扩列。

_TRUE_3BUY_MVP_CODE = '''\
# --- ChanQuant execution contract (v1) ---
# signal_form: four_way
# exit_owner: engine
# flip_mode: R1
# signal_mode: confirmed          # 入场仅认已收盘 K（与回测/实盘对齐）
# exit_signal_mode: confirmed
# 经典三买 ≠ czsc_bs_type=='3buy'，≠ 首次 zs_pos=='above'
# 本模板：有效中枢 → 离开 ZG → 回踩低点仍 ≥ ZG（不进中枢）→ 下降笔确认结束 = 真三买
# 退出负责人=engine：固定止损止盈由 @strategy；close_* 仅结构失效（跌回中枢），禁止指标内窄 TP/SL
# @param trend_min int 0 上涨语境：czsc_trend >= 此值才允许三买（更严可设 1）
# @param zs_min_level int 1 中枢最低级别
# @param pullback_buffer float 0.02 回踩靠近 ZG 的缓冲（相对 ZG，0.02=2%）
# @param require_amp_narrow int 0 可选：1=要求近期中枢振幅收敛
# @param require_vol_surge int 0 可选：1=要求回踩确认棒放量
# @param vol_ma int 20 放量均量周期
# @param vol_mult float 1.5 放量倍数（volume > MA * mult）
# @param amp_window int 20 振幅收敛回看窗口
# @strategy entryPct 1
# @strategy stopLossPct 0.03
# @strategy takeProfitPct 0.06
# @strategy trailingEnabled false
# @strategy tradeDirection both

my_indicator_name = "真三买回踩确认 MVP"
my_indicator_description = (
    "窄场景真三买：上涨语境+有效中枢+离开ZG后回踩不进中枢确认；"
    "可选振幅收敛/放量；exit_owner=engine（结构失效才 close_long）"
)

df = df.copy()

trend_min = int(params.get('trend_min', 0))
zs_min_level = int(params.get('zs_min_level', 1))
pullback_buffer = float(params.get('pullback_buffer', 0.02))
require_amp_narrow = int(params.get('require_amp_narrow', 0))
require_vol_surge = int(params.get('require_vol_surge', 0))
vol_ma_n = int(params.get('vol_ma', 20))
vol_mult = float(params.get('vol_mult', 1.5))
amp_window = int(params.get('amp_window', 20))

trend = df['czsc_trend'].fillna(0)
zs_level = df['czsc_zs_level'].fillna(0)
zs_zd = df['czsc_zs_zd']
zs_zg = df['czsc_zs_zg']
zs_pos = df['czsc_zs_position'].fillna('')
bi_dir = df['czsc_bi_dir'].fillna(0)
bi_dir_prev = bi_dir.shift(1).fillna(0)
close = df['close']
high = df['high']
low = df['low']
volume = df['volume']

# ---------- 有效中枢 ----------
has_zs = (
    (zs_level >= zs_min_level)
    & zs_zd.notna()
    & zs_zg.notna()
    & (zs_zg > zs_zd)
)

# ---------- 离开 / 回踩（真三买，非首次站上） ----------
above_now = has_zs & (zs_pos == 'above') & (close > zs_zg)
above_prev = above_now.shift(1).fillna(False).astype(bool)
leave_above = above_now & (above_prev == False)
# 跌回中枢 = 位置/收盘重新落入中枢（不用 low 影线杀状态；确认棒仍要求 hold_above）
reenter_from_above = has_zs & (
    (zs_pos == 'inside') | (zs_pos == 'below') | (close < zs_zg)
)

# 因果状态：离开 ZG 后、尚未跌回中枢 → left_active
_left_flags = []
_active = False
for i in range(len(df)):
    if bool(leave_above.iloc[i]):
        _active = True
    if bool(reenter_from_above.iloc[i]):
        _active = False
    _left_flags.append(_active)
left_active = pd.Series(_left_flags, index=df.index, dtype=bool)

# 下降笔确认结束 = 回踩底（与平台因果笔语义一致）
bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)
# 回踩靠近 ZG，且低点不进中枢（low >= ZG）
near_zg = low <= (zs_zg * (1.0 + pullback_buffer))
hold_above = low >= zs_zg

up_ctx = trend >= trend_min
# 离开当根不算三买；须在 left_active 内出现回踩确认
raw_3buy = (
    up_ctx
    & has_zs
    & above_now
    & left_active
    & (leave_above == False)
    & bi_flip_dn
    & near_zg
    & hold_above
)

# ---------- 镜像：真三卖（下跌语境 + 离开 ZD 后反弹不进中枢） ----------
below_now = has_zs & (zs_pos == 'below') & (close < zs_zd)
below_prev = below_now.shift(1).fillna(False).astype(bool)
leave_below = below_now & (below_prev == False)
# 反弹回中枢 = 位置/收盘；不用 high 影线杀状态；确认棒仍要求 hold_below
reenter_from_below = has_zs & (
    (zs_pos == 'inside') | (zs_pos == 'above') | (close > zs_zd)
)

_left_dn_flags = []
_active_dn = False
for i in range(len(df)):
    if bool(leave_below.iloc[i]):
        _active_dn = True
    if bool(reenter_from_below.iloc[i]):
        _active_dn = False
    _left_dn_flags.append(_active_dn)
left_below_active = pd.Series(_left_dn_flags, index=df.index, dtype=bool)

bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
near_zd = high >= (zs_zd * (1.0 - pullback_buffer))
hold_below = high <= zs_zd
dn_ctx = trend <= -trend_min if trend_min > 0 else trend <= 0

raw_3sell = (
    dn_ctx
    & has_zs
    & below_now
    & left_below_active
    & (leave_below == False)
    & bi_flip_up
    & near_zd
    & hold_below
)

# ---------- 可选：振幅收敛（指标内自算，不读 bridge 扩列） ----------
center_amp = (zs_zg - zs_zd).where(has_zs)
zs_changed = (zs_zd != zs_zd.shift(1)) | (zs_zg != zs_zg.shift(1))
amp_narrowing = (center_amp < center_amp.shift(1)) & zs_changed & (center_amp > 0)
amp_narrowed_recently = (
    amp_narrowing.rolling(amp_window, min_periods=1).max().fillna(0).astype(bool)
)
if require_amp_narrow:
    raw_3buy = raw_3buy & amp_narrowed_recently
    raw_3sell = raw_3sell & amp_narrowed_recently

# ---------- 可选：放量（volume 相对均量） ----------
vol_ma = volume.rolling(vol_ma_n, min_periods=max(3, vol_ma_n // 4)).mean()
vol_surge = volume > (vol_ma * vol_mult)
if require_vol_surge:
    raw_3buy = raw_3buy & vol_surge
    raw_3sell = raw_3sell & vol_surge

# ---------- 前低参考（仅作图；止损交给 engine stopLossPct，避免双重退出） ----------
# 离开后至当前的回踩最低价 — 建议把引擎止损设在该前低 / ZG 下方
_leave_grp = (left_active == False).cumsum()
prior_low_since_leave = low.groupby(_leave_grp).cummin().where(left_active)
_leave_dn_grp = (left_below_active == False).cumsum()
prior_high_since_leave = high.groupby(_leave_dn_grp).cummax().where(left_below_active)

# ---------- 结构离场：三买失效=跌回中枢；三卖失效=反弹回中枢 ----------
# exit_owner=engine：此处只表达结构失效，不用指标内价格 TP/SL
struct_fail_long = left_active.shift(1).fillna(False).astype(bool) & reenter_from_above
struct_fail_short = left_below_active.shift(1).fillna(False).astype(bool) & reenter_from_below

def edge(s):
    s = s.fillna(False).astype(bool)
    prev = s.shift(1).fillna(False).astype(bool)
    return s & (prev == False)

df['open_long'] = edge(raw_3buy).astype(bool)
df['close_long'] = edge(struct_fail_long | raw_3sell).astype(bool)
df['open_short'] = edge(raw_3sell).astype(bool)
df['close_short'] = edge(struct_fail_short | raw_3buy).astype(bool)

# ---------- 图表 ----------
zg_plot = zs_zg.where(has_zs)
zd_plot = zs_zd.where(has_zs)
output = {
    'name': my_indicator_name,
    'plots': [
        {'name': 'ZG', 'data': zg_plot.tolist(), 'color': '#ef5350', 'overlay': True, 'type': 'line'},
        {'name': 'ZD', 'data': zd_plot.tolist(), 'color': '#26a69a', 'overlay': True, 'type': 'line'},
        {
            'name': '离开后前低',
            'data': prior_low_since_leave.tolist(),
            'color': '#ff9800',
            'overlay': True,
            'type': 'line',
        },
    ],
    'signals': [
        {
            'type': 'buy',
            'text': '真三买',
            'color': '#26a69a',
            'data': [
                df['low'].iloc[i] * 0.995 if bool(df['open_long'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
        {
            'type': 'sell',
            'text': '真三卖',
            'color': '#ef5350',
            'data': [
                df['high'].iloc[i] * 1.005 if bool(df['open_short'].iloc[i]) else None
                for i in range(len(df))
            ],
        },
    ],
}
'''

_register({
    "id": "true_3buy_mvp",
    "name": "真三买回踩确认 MVP",
    "description": (
        "窄场景真三买：上涨语境 + 有效中枢 + 离开 ZG 后回踩不进中枢确认；"
        "可选振幅收敛/放量（指标内自算）。"
        "four_way + exit_owner=engine；≠ bs_type 3buy，≠ 首次站上 above。"
    ),
    "code": _TRUE_3BUY_MVP_CODE,
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_templates() -> list[dict]:
    """Return metadata for all registered ChanLun strategy templates.

    Returns:
        List of dicts, each with keys: id, name, description.
    """
    return [
        {"id": t["id"], "name": t["name"], "description": t["description"]}
        for t in _TEMPLATES.values()
    ]


def get_template(template_id: str) -> Optional[dict]:
    """Return full template by id, or None if not found.

    Returns:
        Dict with keys: id, name, description, code.  None if not found.
    """
    tpl = _TEMPLATES.get(template_id)
    if tpl is None:
        return None
    return {
        "id": tpl["id"],
        "name": tpl["name"],
        "description": tpl["description"],
        "code": tpl["code"],
    }
