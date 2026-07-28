"""
CZSC (缠论) Pre-computation Bridge for ChanQuant.

czsc uses Rust (PyO3) for core algorithms, so it cannot run inside the
safe_exec sandbox. This module pre-computes Chan Theory features on the
backend side and injects them as DataFrame columns (czsc_ prefix) that
indicator scripts can read like any other column.

Usage:
    from app.services.czsc_bridge import compute_czsc_features, is_czsc_enabled

    if is_czsc_enabled():
        df = compute_czsc_features(df, freq='1H')

If czsc is not installed, all functions gracefully return the original
DataFrame unchanged.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Graceful czsc import
# ---------------------------------------------------------------------------
_CZSC_AVAILABLE = False
_CZSC_IMPORT_ERROR: Optional[str] = None

try:
    from czsc import CZSC as _CZSC
    from czsc import Freq as _Freq
    from czsc import format_standard_kline as _format_standard_kline

    _CZSC_AVAILABLE = True
except ImportError as e:
    _CZSC_IMPORT_ERROR = str(e)
    logger.debug(f"czsc not available: {e}")
except Exception as e:
    _CZSC_IMPORT_ERROR = str(e)
    logger.warning(f"czsc import failed: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_czsc_enabled() -> bool:
    """Return True if czsc library is installed and importable."""
    return _CZSC_AVAILABLE


def get_czsc_import_error() -> Optional[str]:
    """Return the import error string if czsc failed to import, else None."""
    return _CZSC_IMPORT_ERROR


# ---------------------------------------------------------------------------
# Timeframe mapping: ChanQuant -> czsc Freq
# ---------------------------------------------------------------------------
# ChanQuant timeframes: '1m', '5m', '15m', '30m', '1H', '4H', '1D', '1W'
# czsc Freq enum (1.0.x): F1, F5, F15, F30, F60, F240 (or D), D, W

_TIMEFRAME_TO_FREQ: Dict[str, str] = {
    '10s': '1分钟',  # czsc has no native 10s; map to 1分钟 for structural analysis
    '1m': '1分钟',
    '5m': '5分钟',
    '15m': '15分钟',
    '30m': '30分钟',
    '1H': '60分钟',
    '1h': '60分钟',
    '2H': '120分钟',
    '2h': '120分钟',
    '4H': '240分钟',   # czsc 1.0 has F240 (240分钟 = 4H)
    '4h': '240分钟',
    '1D': '日线',
    '1d': '日线',
    '1W': '周线',
    '1w': '周线',
    '1M': '月线',
    '1mo': '月线',
}


def _map_timeframe_to_freq(timeframe: str) -> Optional[Any]:
    """Map ChanQuant timeframe string to czsc Freq enum."""
    if not _CZSC_AVAILABLE:
        return None
    freq_str = _TIMEFRAME_TO_FREQ.get(timeframe)
    if freq_str is None:
        logger.warning(f"czsc_bridge: unsupported timeframe '{timeframe}', skipping czsc features")
        return None
    try:
        return _Freq(freq_str)
    except Exception:
        # Fallback: try common enum aliases
        try:
            return getattr(_Freq, freq_str.replace('分钟', '').replace('日线', 'D').replace('周线', 'W'))
        except Exception:
            logger.warning(f"czsc_bridge: cannot map timeframe '{timeframe}' to czsc Freq")
            return None


# ---------------------------------------------------------------------------
# Column documentation (for AI prompt injection)
# ---------------------------------------------------------------------------

CZSC_COLUMNS: List[Dict[str, str]] = [
    {
        'name': 'czsc_fx_mark',
        'dtype': 'int',
        'desc': 'Fractal (分型) mark: 1=top fractal (顶分型), -1=bottom fractal (底分型), 0=none',
    },
    {
        'name': 'czsc_fx_price',
        'dtype': 'float',
        'desc': 'Fractal price: high for top fractal, low for bottom fractal; NaN if no fractal',
    },
    {
        'name': 'czsc_bi_dir',
        'dtype': 'int',
        'desc': 'Current stroke (笔) direction: 1=upward stroke (上升笔), -1=downward stroke (下降笔), 0=none',
    },
    {
        'name': 'czsc_bi_start_price',
        'dtype': 'float',
        'desc': 'Starting price of the current stroke',
    },
    {
        'name': 'czsc_bi_end_price',
        'dtype': 'float',
        'desc': 'Ending price of the current stroke (latest bar within this stroke)',
    },
    {
        'name': 'czsc_bi_length',
        'dtype': 'int',
        'desc': 'Number of K-lines contained in the current stroke so far',
    },
    {
        'name': 'czsc_duan_dir',
        'dtype': 'int',
        'desc': 'Current segment (段) direction: 1=upward segment (上升段), -1=downward segment (下降段), 0=none. '
                'A segment consists of 3+ consecutive strokes with progressively higher/lower extremes.',
    },
    {
        'name': 'czsc_duan_start_price',
        'dtype': 'float',
        'desc': 'Starting price of the current segment',
    },
    {
        'name': 'czsc_duan_end_price',
        'dtype': 'float',
        'desc': 'Ending price of the current segment (latest bar within this segment)',
    },
    {
        'name': 'czsc_zs_level',
        'dtype': 'int',
        'desc': 'Center (中枢) level: 0=no center, higher value = larger center',
    },
    {
        'name': 'czsc_zs_zd',
        'dtype': 'float',
        'desc': 'Center lowest point ZD (中枢低点)',
    },
    {
        'name': 'czsc_zs_zg',
        'dtype': 'float',
        'desc': 'Center highest point ZG (中枢高点)',
    },
    {
        'name': 'czsc_zs_position',
        'dtype': 'str',
        'desc': "Price position relative to center: 'above'=价格在上方, 'below'=价格在下方, 'inside'=在中枢内, ''=no center",
    },
    {
        'name': 'czsc_bs_type',
        'dtype': 'str',
        'desc': "Buy/Sell point type (买卖点): '1buy'=第一类买点, '2buy'=第二类买点, '3buy'=第三类买点, "
                "'1sell'=第一类卖点, '2sell'=第二类卖点, '3sell'=第三类卖点, ''=none",
    },
    {
        'name': 'czsc_trend',
        'dtype': 'int',
        'desc': 'Trend classification: 1=uptrend (上涨趋势, at least 2 upward centers), '
                '-1=downtrend (下跌趋势), 0=consolidation (盘整, 0-1 center)',
    },
    # ── v4.1 auxiliary columns ──
    {
        'name': 'czsc_bi_force',
        'dtype': 'float',
        'desc': 'Stroke force (笔力度): |end-start|/start × bar_count; used for 背驰 comparison',
    },
    {
        'name': 'czsc_beichi',
        'dtype': 'int',
        'desc': 'Divergence (背驰): 1=bottom divergence (底背驰), -1=top divergence (顶背驰), 0=none',
    },
    {
        'name': 'czsc_zs_event',
        'dtype': 'str',
        'desc': "Center event: 'expand'=中枢扩张, 'narrow'=中枢收敛, 'new'=中枢新生, ''=none",
    },
    {
        'name': 'czsc_trend_continue',
        'dtype': 'int',
        'desc': 'Trend continuation via centers: 1=ZG progressively higher, -1=ZD progressively lower, 0=none',
    },
    {
        'name': 'czsc_amp_narrow',
        'dtype': 'int',
        'desc': 'Amplitude narrowing flag (振幅收敛): 1 when consecutive center amplitude shrinks, else 0',
    },
    {
        'name': 'czsc_vol_surge',
        'dtype': 'int',
        'desc': 'Volume surge (放量): 1 when volume > 20-bar MA × 1.5, else 0',
    },
    {
        'name': 'czsc_vol_shrink',
        'dtype': 'int',
        'desc': 'Volume shrink (缩量): 1 when volume < 10-bar MA × 0.7, else 0',
    },
    {
        'name': 'czsc_prior_low_ok',
        'dtype': 'int',
        'desc': 'Prior-low protection (前低保护): 1 when close >= recent significant low, else 0',
    },
    {
        'name': 'czsc_ml_align',
        'dtype': 'int',
        'desc': 'Multi-level proxy alignment: 1 if bi_dir and duan_dir same sign, -1 if opposite, 0 if either unset',
    },
]


def get_czsc_column_docs() -> str:
    """Return formatted documentation string for all czsc_ columns.

    Used by the AI generation system prompt to teach LLMs about available
    Chan Theory features. Now includes signal function reference from czsc 1.0.
    """
    lines = [
        "# CZSC (缠论/Chan Theory) Columns",
        "",
        "When the user asks for 缠论/chanlun/Chan Theory signals, or your strategy "
        "references any `czsc_` column, the following pre-computed columns are "
        "automatically injected into `df`. Use them directly — do NOT try to import czsc.",
        "",
    ]
    for col in CZSC_COLUMNS:
        lines.append(f"- `df['{col['name']}]` ({col['dtype']}): {col['desc']}")
    lines.append("")
    lines.append(
        "Typical patterns: "
        "detect 笔方向翻转 `(df['czsc_bi_dir'] != df['czsc_bi_dir'].shift(1))` as entry signals; "
        "use `czsc_bs_type != ''` for buy/sell point triggers; "
        "combine `czsc_trend` with `czsc_zs_position` for trend-following filters."
    )

    # Append signal function reference if available
    try:
        from app.services.czsc_signals import get_signal_docs_for_prompt
        signal_docs = get_signal_docs_for_prompt(
            namespace_filter=['cxt', 'tas', 'jcc', 'vol', 'pressure', 'bar'],
            max_per_namespace=8,
        )
        if signal_docs:
            lines.append("")
            lines.append(signal_docs)
    except Exception:
        pass

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Code detection: does the indicator script reference czsc_ columns?
# ---------------------------------------------------------------------------

_CZSC_COL_PATTERN = re.compile(r'\bczsc_')


def code_uses_czsc(code: str) -> bool:
    """Quick check whether indicator code references any czsc_ column."""
    if not code:
        return False
    return bool(_CZSC_COL_PATTERN.search(code))


# ---------------------------------------------------------------------------
# In-process LRU cache for CZSC computation results
# ---------------------------------------------------------------------------
_CZSC_CACHE: dict = {}
_CZSC_CACHE_TIMESTAMPS: dict = {}
_CZSC_CACHE_MAX_SIZE = 256
_cache_lock = threading.Lock()

# TTL by K-line period category (seconds)
_CACHE_TTL_MINUTE = 60      # 1m / 5m / 15m
_CACHE_TTL_HOUR = 300       # 30m / 1H / 2H / 4H
_CACHE_TTL_DAY = 3600       # 1D / 1W / 1M

_MINUTE_FREQS = frozenset({'1m', '5m', '15m'})
_HOUR_FREQS = frozenset({'30m', '1H', '1h', '2H', '2h', '4H', '4h'})


def _cache_ttl_for_freq(freq: str) -> int:
    """Return cache TTL in seconds based on K-line frequency."""
    if freq in _MINUTE_FREQS:
        return _CACHE_TTL_MINUTE
    if freq in _HOUR_FREQS:
        return _CACHE_TTL_HOUR
    return _CACHE_TTL_DAY


def _build_cache_key(df: pd.DataFrame, freq: str, symbol: str) -> Optional[tuple]:
    """Build a hashable cache key from DataFrame metadata.

    Returns None if a key cannot be reliably constructed.
    """
    bar_count = len(df)
    last_ts: Any = None
    try:
        if isinstance(df.index, pd.DatetimeIndex) and len(df) > 0:
            last_ts = df.index[-1].isoformat()
        elif 'dt' in df.columns and len(df) > 0:
            last_ts = str(df['dt'].iloc[-1])
        elif 'time' in df.columns and len(df) > 0:
            last_ts = str(df['time'].iloc[-1])
        elif 'datetime' in df.columns and len(df) > 0:
            last_ts = str(df['datetime'].iloc[-1])
    except Exception:
        last_ts = None

    if last_ts is None:
        return None
    return (symbol, freq, bar_count, last_ts)


def _cache_get(key: tuple, ttl: int) -> Optional[pd.DataFrame]:
    """Return cached DataFrame copy if present and not expired, else None."""
    with _cache_lock:
        now = time.monotonic()
        ts = _CZSC_CACHE_TIMESTAMPS.get(key)
        if ts is None:
            return None
        if now - ts > ttl:
            # Expired
            _CZSC_CACHE.pop(key, None)
            _CZSC_CACHE_TIMESTAMPS.pop(key, None)
            return None
        cached = _CZSC_CACHE.get(key)
        if cached is None:
            return None
        return cached.copy()


def _cache_put(key: tuple, df: pd.DataFrame) -> None:
    """Store DataFrame in cache, evicting oldest entries if at capacity."""
    with _cache_lock:
        if len(_CZSC_CACHE) >= _CZSC_CACHE_MAX_SIZE:
            # Evict the oldest entry by timestamp
            oldest_key = min(_CZSC_CACHE_TIMESTAMPS, key=_CZSC_CACHE_TIMESTAMPS.get)
            _CZSC_CACHE.pop(oldest_key, None)
            _CZSC_CACHE_TIMESTAMPS.pop(oldest_key, None)
        _CZSC_CACHE[key] = df
        _CZSC_CACHE_TIMESTAMPS[key] = time.monotonic()


# ---------------------------------------------------------------------------
# Core: compute czsc features and inject as DataFrame columns
# ---------------------------------------------------------------------------

def compute_czsc_features(
    df: pd.DataFrame,
    freq: str = '1H',
    *,
    force: bool = False,
    symbol: str = 'SYMBOL',
    causal: bool = True,
) -> pd.DataFrame:
    """Pre-compute Chan Theory features and inject them as czsc_ columns.

    Args:
        df: Standard OHLCV DataFrame with columns open/high/low/close/volume.
            May have DatetimeIndex or integer index.
        freq: ChanQuant timeframe string (e.g. '1H', '15m', '1D').
        force: If True, compute features even if code doesn't reference czsc_.
        symbol: Symbol name for czsc analysis (default 'SYMBOL').
        causal: If True (default), only use confirmed strokes (exclude the
            last in-progress stroke) and compute trend per-bar causally.
            This eliminates lookahead bias in backtests. Set False for
            real-time direction in live trading (includes in-progress stroke).

    Returns:
        A copy of df with czsc_ columns added. If czsc is unavailable or
        computation fails, returns df unchanged (no error).
    """
    if not _CZSC_AVAILABLE:
        return df

    if df is None or len(df) < 10:
        # Need enough bars for meaningful Chan analysis (at least a few strokes)
        return df

    # --- Cache lookup ---
    cache_key = _build_cache_key(df, freq, symbol)
    if cache_key is not None:
        # Include causal flag in key so causal/non-causal results don't conflict
        cache_key = cache_key + (causal,)
        ttl = _cache_ttl_for_freq(freq)
        cached = _cache_get(cache_key, ttl)
        if cached is not None:
            logger.debug(f"czsc_bridge: cache hit for {symbol} {freq} ({len(df)} bars, causal={causal})")
            return cached

    try:
        result = _compute_features_inner(df, freq, symbol, causal=causal)
    except Exception as e:
        logger.warning(f"czsc_bridge: feature computation failed: {e}", exc_info=True)
        return df

    # --- Cache store (only if computation produced new czsc_ columns) ---
    if cache_key is not None and any(c.startswith('czsc_') for c in result.columns):
        _cache_put(cache_key, result)

    return result


def _compute_features_inner(df: pd.DataFrame, freq: str, symbol: str = 'SYMBOL', *, causal: bool = True) -> pd.DataFrame:
    """Inner implementation: convert to RawBar, run CZSC, map back to df.

    When causal=True (default), only confirmed strokes are used and trend
    is computed per-bar, eliminating lookahead bias.
    """
    czsc_freq = _map_timeframe_to_freq(freq)
    if czsc_freq is None:
        return df

    result = df.copy()
    n = len(result)

    # Initialize output arrays
    fx_mark = np.zeros(n, dtype=np.int8)
    fx_price = np.full(n, np.nan, dtype=np.float64)
    bi_dir = np.zeros(n, dtype=np.int8)
    bi_start_price = np.full(n, np.nan, dtype=np.float64)
    bi_end_price = np.full(n, np.nan, dtype=np.float64)
    bi_length = np.zeros(n, dtype=np.int32)
    zs_level = np.zeros(n, dtype=np.int32)
    zs_zd = np.full(n, np.nan, dtype=np.float64)
    zs_zg = np.full(n, np.nan, dtype=np.float64)
    zs_position = np.array([''] * n, dtype=object)
    bs_type = np.array([''] * n, dtype=object)
    trend_arr = np.zeros(n, dtype=np.int8)

    # ---- Step 1: Build a simple df for czsc format_standard_kline ----
    # czsc expects columns: dt (datetime), open, high, low, close, vol, amount
    # We prepare a normalized DataFrame with integer-row index for mapping.
    czsc_df = _prepare_czsc_df(df, symbol)

    # ---- Step 2: Convert to RawBar and run CZSC ----
    try:
        bars = _format_standard_kline(czsc_df, freq=czsc_freq)
    except Exception as e:
        logger.warning(f"czsc_bridge: format_standard_kline failed: {e}")
        return df

    if not bars or len(bars) < 5:
        return df

    try:
        czsc_obj = _CZSC(bars)
    except Exception as e:
        logger.warning(f"czsc_bridge: CZSC analysis failed: {e}")
        return df

    # ---- Causal stroke filtering ----
    # The last stroke in bi_list is always "in progress" and can repaint as
    # new bars arrive. For backtest correctness, we only use confirmed strokes.
    # A stroke is "confirmed" at end_idx + CONFIRMATION_DELAY (2 bars for the
    # 3-bar fractal confirmation pattern: the fractal at bar N needs bars N+1
    # and N+2 to verify the 3-bar top/bottom pattern).
    _CONFIRMATION_DELAY = 2
    _all_bi = getattr(czsc_obj, 'bi_list', []) or []
    if causal and len(_all_bi) > 1:
        _confirmed_bi = _all_bi[:-1]
    else:
        _confirmed_bi = _all_bi

    # Build stroke info list with confirmation index for causal mapping
    _stroke_infos = []
    for _bi in _confirmed_bi:
        _s, _e = _bi_bar_range(_bi, czsc_df)
        _d = _get_bi_direction_int(_bi)
        _sp = float(getattr(_bi.fx_a, 'fx', 0)) if hasattr(_bi, 'fx_a') and _bi.fx_a else 0.0
        _ep = float(getattr(_bi.fx_b, 'fx', 0)) if hasattr(_bi, 'fx_b') and _bi.fx_b else 0.0
        _stroke_infos.append((_s, _e, _d, _sp, _ep))

    # Temporarily set czsc_obj.bi_list to confirmed strokes so that all
    # downstream helpers (_map_centers, _detect_buy_sell_points, _detect_duan)
    # automatically use confirmed strokes only.
    _orig_bi_list = czsc_obj.bi_list
    try:
        czsc_obj.bi_list = _confirmed_bi
    except Exception:
        pass

    # ---- Step 3: Map fractals (分型) to df index ----
    _map_fractals(czsc_obj, czsc_df, fx_mark, fx_price, n)

    # ---- Step 4: Map strokes (笔) to df index ----
    if causal:
        # Causal mapping: at each bar j, bi_dir[j] = direction of the most
        # recent stroke whose end fractal was confirmed by bar j.
        # This eliminates repainting/lookahead bias.
        _ptr = 0
        for _j in range(n):
            while (_ptr < len(_stroke_infos)
                   and _stroke_infos[_ptr][1] + _CONFIRMATION_DELAY <= _j):
                _ptr += 1
            if _ptr > 0:
                _si = _stroke_infos[_ptr - 1]
                bi_dir[_j] = _si[2]
                bi_start_price[_j] = _si[3]
                bi_end_price[_j] = _si[4]
                bi_length[_j] = max(1, _j - _si[0] + 1)
            # else: no stroke confirmed yet, bi_dir stays 0
    else:
        # Non-causal: original mapping (includes in-progress last stroke)
        _map_strokes(czsc_obj, czsc_df, bi_dir, bi_start_price, bi_end_price, bi_length, n)
        _last_dir = 0
        for _i in range(n):
            if bi_dir[_i] != 0:
                _last_dir = bi_dir[_i]
            elif _last_dir != 0:
                bi_dir[_i] = _last_dir

    # ---- Step 5: Map centers (中枢) to df index ----
    # Uses confirmed strokes only (via czsc_obj.bi_list replacement above).
    _map_centers(czsc_obj, czsc_df, zs_level, zs_zd, zs_zg, zs_position, n)

    # ---- Step 6: Detect buy/sell points (买卖点) — v4.1 with 1/2/3 + 背驰 ----
    # Uses confirmed strokes only (via czsc_obj.bi_list replacement above).
    beichi_arr = np.zeros(n, dtype=np.int8)
    bi_force_arr = np.full(n, np.nan, dtype=np.float64)
    _detect_buy_sell_points_v41(
        czsc_obj, czsc_df, bs_type, beichi_arr, bi_force_arr, n,
    )

    # ---- Step 7: Classify trend ----
    if causal:
        _classify_trend_causal(_stroke_infos, _CONFIRMATION_DELAY, trend_arr, n)
    else:
        _classify_trend(czsc_obj, trend_arr, n)

    # ---- Step 8: Map duan (段 / segments) ----
    # Uses confirmed strokes only (via czsc_obj.bi_list replacement above).
    duan_dir_arr, duan_start_price, duan_end_price = _detect_duan(czsc_obj, czsc_df, n)

    # ---- Step 8b: v4.1 aux features (zs events, volume, prior-low, ml align) ----
    zs_event, trend_continue, amp_narrow, vol_surge, vol_shrink, prior_low_ok, ml_align = (
        _compute_v41_aux_features(
            czsc_df, zs_zd, zs_zg, zs_level, bi_dir, duan_dir_arr, n,
        )
    )

    # Restore original bi_list on czsc_obj
    try:
        czsc_obj.bi_list = _orig_bi_list
    except Exception:
        pass

    # ---- Step 9: Assign columns to result df ----
    result['czsc_fx_mark'] = fx_mark
    result['czsc_fx_price'] = fx_price
    result['czsc_bi_dir'] = bi_dir
    result['czsc_bi_start_price'] = bi_start_price
    result['czsc_bi_end_price'] = bi_end_price
    result['czsc_bi_length'] = bi_length
    result['czsc_zs_level'] = zs_level
    result['czsc_zs_zd'] = zs_zd
    result['czsc_zs_zg'] = zs_zg
    result['czsc_zs_position'] = zs_position
    result['czsc_bs_type'] = bs_type
    result['czsc_trend'] = trend_arr
    result['czsc_duan_dir'] = duan_dir_arr
    result['czsc_duan_start_price'] = duan_start_price
    result['czsc_duan_end_price'] = duan_end_price
    # v4.1
    result['czsc_bi_force'] = bi_force_arr
    result['czsc_beichi'] = beichi_arr
    result['czsc_zs_event'] = zs_event
    result['czsc_trend_continue'] = trend_continue
    result['czsc_amp_narrow'] = amp_narrow
    result['czsc_vol_surge'] = vol_surge
    result['czsc_vol_shrink'] = vol_shrink
    result['czsc_prior_low_ok'] = prior_low_ok
    result['czsc_ml_align'] = ml_align

    n_strokes = len(getattr(czsc_obj, 'bi_list', []) or [])
    n_fractals = len(getattr(czsc_obj, 'fx_list', []) or [])
    logger.info(
        f"czsc_bridge: injected {len(CZSC_COLUMNS)} columns "
        f"({n_strokes} strokes, {n_fractals} fractals) "
        f"for {n} bars"
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prepare_czsc_df(df: pd.DataFrame, symbol: str = 'SYMBOL') -> pd.DataFrame:
    """Normalize df columns for czsc format_standard_kline.

    czsc expects: dt (datetime), open, high, low, close, vol (or volume), amount.
    """
    out = df.copy()

    # Ensure datetime column 'dt'
    if isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index()
        # The first column after reset is typically the datetime index
        time_col = out.columns[0]
        if time_col != 'dt':
            out.rename(columns={time_col: 'dt'}, inplace=True)
    elif 'time' in out.columns:
        out.rename(columns={'time': 'dt'}, inplace=True)
        out['dt'] = pd.to_datetime(out['dt'])
    elif 'dt' not in out.columns:
        # Fallback: generate sequential timestamps
        out['dt'] = pd.date_range('2024-01-01', periods=len(out), freq='1h')

    # Ensure required columns exist
    for col in ('open', 'high', 'low', 'close'):
        if col not in out.columns:
            raise ValueError(f"czsc_bridge: missing required column '{col}'")

    # vol / volume -> czsc uses 'vol'
    if 'vol' not in out.columns:
        if 'volume' in out.columns:
            out['vol'] = out['volume']
        else:
            out['vol'] = 0.0

    # amount column (optional, default 0)
    if 'amount' not in out.columns:
        out['amount'] = 0.0

    # Ensure dt is datetime type
    if not pd.api.types.is_datetime64_any_dtype(out['dt']):
        out['dt'] = pd.to_datetime(out['dt'])

    # Remove timezone info (czsc expects timezone-naive datetimes)
    if hasattr(out['dt'].dtype, 'tz') and out['dt'].dt.tz is not None:
        out['dt'] = out['dt'].dt.tz_localize(None)

    # Ensure 'symbol' column (required by czsc format_standard_kline)
    if 'symbol' not in out.columns:
        out['symbol'] = symbol

    return out[['symbol', 'dt', 'open', 'high', 'low', 'close', 'vol', 'amount']].copy()


def _bar_dt_to_index(bar_dt: Any, czsc_df: pd.DataFrame) -> int:
    """Map a czsc bar's dt to the closest integer index in czsc_df.

    Returns the integer positional index (iloc-based), or -1 if not found.
    """
    try:
        if hasattr(bar_dt, 'timestamp'):
            # czsc bar dt is a datetime object
            dt = pd.Timestamp(bar_dt)
        else:
            dt = pd.Timestamp(bar_dt)

        # Try exact match first
        mask = czsc_df['dt'] == dt
        if mask.any():
            return int(mask.idxmax()) if not isinstance(czsc_df.index, pd.RangeIndex) else int(np.argmax(mask.values))

        # Fallback: find closest
        diffs = (czsc_df['dt'] - dt).abs()
        return int(diffs.idxmin()) if not isinstance(czsc_df.index, pd.RangeIndex) else int(np.argmin(diffs.values))
    except Exception:
        return -1


def _bi_bar_range(bi: Any, czsc_df: pd.DataFrame) -> Tuple[int, int]:
    """Return (start_idx, end_idx) integer range for a stroke in the df."""
    start_dt = None
    end_dt = None
    try:
        # bi.fx_a and bi.fx_b are the start/end fractals
        if hasattr(bi, 'fx_a') and bi.fx_a is not None:
            start_dt = bi.fx_a.dt
        if hasattr(bi, 'fx_b') and bi.fx_b is not None:
            end_dt = bi.fx_b.dt
    except Exception:
        pass

    start_idx = _bar_dt_to_index(start_dt, czsc_df) if start_dt else -1
    end_idx = _bar_dt_to_index(end_dt, czsc_df) if end_dt else -1

    # Clamp to valid range
    n = len(czsc_df)
    if start_idx < 0:
        start_idx = 0
    if end_idx < 0:
        end_idx = n - 1
    start_idx = min(start_idx, n - 1)
    end_idx = min(end_idx, n - 1)
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx

    return start_idx, end_idx


def _map_fractals(czsc_obj: Any, czsc_df: pd.DataFrame,
                  fx_mark: np.ndarray, fx_price: np.ndarray, n: int) -> None:
    """Map CZSC fractals to per-bar arrays."""
    try:
        fx_list = getattr(czsc_obj, 'fx_list', []) or []
    except Exception:
        return

    for fx in fx_list:
        idx = _bar_dt_to_index(fx.dt, czsc_df)
        if 0 <= idx < n:
            mark_val = getattr(fx, 'mark', None)
            # czsc 1.0.x: mark is a Chinese string "顶分型" (top) / "底分型" (bottom),
            # older versions may use Mark enum D/G, or integer values.
            if mark_val is not None:
                mark_str = str(mark_val).lower()
                if ('顶分型' in mark_str or 'd' in mark_str
                        or 'top' in mark_str or mark_str == '1'):
                    fx_mark[idx] = 1
                    fx_price[idx] = float(getattr(fx, 'fx', 0) or getattr(fx, 'high', 0))
                elif ('底分型' in mark_str or 'g' in mark_str
                      or 'bottom' in mark_str or 'bot' in mark_str or mark_str == '-1'):
                    fx_mark[idx] = -1
                    fx_price[idx] = float(getattr(fx, 'fx', 0) or getattr(fx, 'low', 0))


def _map_strokes(czsc_obj: Any, czsc_df: pd.DataFrame,
                 bi_dir: np.ndarray, bi_start_price: np.ndarray,
                 bi_end_price: np.ndarray, bi_length: np.ndarray,
                 n: int) -> None:
    """Map CZSC strokes (笔) to per-bar arrays."""
    try:
        bi_list = getattr(czsc_obj, 'bi_list', []) or []
    except Exception:
        return

    for i, bi in enumerate(bi_list):
        start_idx, end_idx = _bi_bar_range(bi, czsc_df)
        direction_val = getattr(bi, 'direction', None)

        # Determine direction: Up=1, Down=-1
        # czsc 1.0.x: direction is Chinese string "向上" (up) / "向下" (down)
        # Older versions may use "Up"/"Down", integer 1/-1, or "上升"/"下降".
        dir_int = 0
        if direction_val is not None:
            dir_str = str(direction_val)
            if '向上' in dir_str or 'up' in dir_str.lower() or dir_str == '1' or '上升' in dir_str:
                dir_int = 1
            elif '向下' in dir_str or 'down' in dir_str.lower() or dir_str == '-1' or '下降' in dir_str:
                dir_int = -1

        start_p = float(getattr(bi.fx_a, 'fx', 0)) if hasattr(bi, 'fx_a') and bi.fx_a else 0.0
        end_p = float(getattr(bi.fx_b, 'fx', 0)) if hasattr(bi, 'fx_b') and bi.fx_b else 0.0
        bar_count = end_idx - start_idx + 1

        for j in range(start_idx, min(end_idx + 1, n)):
            bi_dir[j] = dir_int
            bi_start_price[j] = start_p
            bi_end_price[j] = end_p
            bi_length[j] = j - start_idx + 1


def _map_centers(czsc_obj: Any, czsc_df: pd.DataFrame,
                 zs_level: np.ndarray, zs_zd: np.ndarray,
                 zs_zg: np.ndarray, zs_position: np.ndarray,
                 n: int) -> None:
    """Map CZSC centers (中枢) to per-bar arrays.

    If the CZSC library exposes ``zs_list`` (czsc >= 0.9), we use it directly.
    Otherwise (czsc 1.0.x), we reconstruct centers locally from ``bi_list``
    using the standard 3-stroke overlap method.
    """
    # --- Try library-provided zs_list first ---
    try:
        zs_list = getattr(czsc_obj, 'zs_list', []) or []
    except Exception:
        zs_list = []

    if zs_list:
        for level_idx, zs in enumerate(zs_list):
            start_idx, end_idx = _get_zs_bar_range(zs, czsc_df, n)
            zd = float(getattr(zs, 'zd', 0) or 0)
            zg = float(getattr(zs, 'zg', 0) or 0)
            bis = getattr(zs, 'bis', []) or []
            level = max(1, len(bis) // 3)
            for j in range(start_idx, min(end_idx + 1, n)):
                zs_level[j] = max(zs_level[j], level)
                zs_zd[j] = zd
                zs_zg[j] = zg
    else:
        # --- Fallback: compute centers from bi_list (czsc 1.0.x) ---
        # A center (中枢) is formed by 3 consecutive strokes with overlapping
        # price ranges.  ZD = highest low, ZG = lowest high.  Valid when ZD < ZG.
        # The center is active from its first stroke's start bar until the next
        # center begins (or data ends).
        try:
            bi_list = getattr(czsc_obj, 'bi_list', []) or []
        except Exception:
            bi_list = []

        if len(bi_list) >= 3:
            centers = []  # list of (start_idx, end_idx_or_None, zd, zg)
            for i in range(len(bi_list) - 2):
                triplet = bi_list[i:i + 3]
                ranges = []
                triplet_indices = []
                for bi in triplet:
                    s_idx, e_idx = _bi_bar_range(bi, czsc_df)
                    high = max(
                        float(getattr(bi.fx_a, 'fx', 0) or 0) if hasattr(bi, 'fx_a') and bi.fx_a else 0,
                        float(getattr(bi.fx_b, 'fx', 0) or 0) if hasattr(bi, 'fx_b') and bi.fx_b else 0,
                    )
                    low = min(
                        float(getattr(bi.fx_a, 'fx', 0) or 0) if hasattr(bi, 'fx_a') and bi.fx_a else 0,
                        float(getattr(bi.fx_b, 'fx', 0) or 0) if hasattr(bi, 'fx_b') and bi.fx_b else 0,
                    )
                    if high > 0 and low > 0:
                        ranges.append((low, high))
                        triplet_indices.append((s_idx, e_idx))

                if len(ranges) >= 2:
                    zd = max(r[0] for r in ranges)  # highest low
                    zg = min(r[1] for r in ranges)  # lowest high
                    if zd < zg:
                        c_start = triplet_indices[0][0]
                        c_end = triplet_indices[-1][1]
                        centers.append([c_start, c_end, zd, zg])

            # Merge overlapping / adjacent centers and assign to bars
            # Each bar gets the most recently started center
            for ci, (c_start, c_end, zd, zg) in enumerate(centers):
                # This center is active from c_start until the next center starts
                next_start = centers[ci + 1][0] if ci + 1 < len(centers) else n
                active_end = min(next_start, n)
                level = max(1, ci + 1)
                for j in range(c_start, active_end):
                    if 0 <= j < n:
                        zs_level[j] = max(zs_level[j], level)
                        zs_zd[j] = zd
                        zs_zg[j] = zg

    # --- Compute position for all bars that have a center ---
    close_col = czsc_df['close'].values if 'close' in czsc_df.columns else None
    if close_col is not None:
        for j in range(n):
            if not np.isnan(zs_zg[j]) and not np.isnan(zs_zd[j]):
                c = float(close_col[j]) if j < len(close_col) else 0.0
                if c > zs_zg[j]:
                    zs_position[j] = 'above'
                elif c < zs_zd[j]:
                    zs_position[j] = 'below'
                else:
                    zs_position[j] = 'inside'


def _get_zs_bar_range(zs: Any, czsc_df: pd.DataFrame, n: int) -> Tuple[int, int]:
    """Get the bar range for a center (中枢)."""
    start_idx = 0
    end_idx = n - 1

    # Try to get range from component strokes
    bis = getattr(zs, 'bis', []) or []
    if bis:
        first_bi = bis[0]
        last_bi = bis[-1]
        s, _ = _bi_bar_range(first_bi, czsc_df)
        _, e = _bi_bar_range(last_bi, czsc_df)
        start_idx = s
        end_idx = e
    else:
        # Fallback: use center's own dt attributes
        start_dt = getattr(zs, 'sdt', None) or getattr(zs, 'start_dt', None)
        end_dt = getattr(zs, 'edt', None) or getattr(zs, 'end_dt', None)
        if start_dt:
            start_idx = _bar_dt_to_index(start_dt, czsc_df)
        if end_dt:
            end_idx = _bar_dt_to_index(end_dt, czsc_df)

    start_idx = max(0, min(start_idx, n - 1))
    end_idx = max(0, min(end_idx, n - 1))
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx
    return start_idx, end_idx


def _macd_hist_from_close(close: np.ndarray) -> np.ndarray:
    """MACD histogram (DIF-DEA) for stroke-force / 背驰 comparison."""
    s = pd.Series(close.astype(float))
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    return (dif - dea).to_numpy(dtype=np.float64)


def _bi_price_range(bi: Any) -> Tuple[float, float]:
    """Return (low, high) of a stroke from its fractals."""
    fa = getattr(bi, 'fx_a', None)
    fb = getattr(bi, 'fx_b', None)
    pa = float(getattr(fa, 'fx', 0) or 0) if fa else 0.0
    pb = float(getattr(fb, 'fx', 0) or 0) if fb else 0.0
    if pa <= 0 or pb <= 0:
        return 0.0, 0.0
    return min(pa, pb), max(pa, pb)


def _build_centers_from_bi(bi_list: list, czsc_df: pd.DataFrame) -> list:
    """Build non-overlapping center records: (start_idx, end_idx, zd, zg)."""
    centers: list = []
    if len(bi_list) < 3:
        return centers
    i = 0
    while i <= len(bi_list) - 3:
        triplet = bi_list[i:i + 3]
        ranges = []
        idxs = []
        for bi in triplet:
            lo, hi = _bi_price_range(bi)
            s_idx, e_idx = _bi_bar_range(bi, czsc_df)
            if hi > 0 and lo > 0:
                ranges.append((lo, hi))
                idxs.append((s_idx, e_idx))
        if len(ranges) >= 2:
            zd = max(r[0] for r in ranges)
            zg = min(r[1] for r in ranges)
            if zd < zg:
                centers.append((idxs[0][0], idxs[-1][1], zd, zg))
                i += 3
                continue
        i += 1
    return centers


def _active_center_at(centers: list, bar_idx: int) -> Optional[Tuple[float, float]]:
    """Most recent center whose span covers (or precedes) bar_idx → (zd, zg)."""
    active = None
    for c_start, c_end, zd, zg in centers:
        if c_start <= bar_idx:
            active = (zd, zg)
        if c_start > bar_idx:
            break
    return active


def _detect_buy_sell_points(czsc_obj: Any, czsc_df: pd.DataFrame,
                            bs_type: np.ndarray, n: int) -> None:
    """Legacy simplified 1buy/1sell/3buy/3sell (kept for compatibility).

    Prefer ``_detect_buy_sell_points_v41`` which adds 2buy/2sell + 背驰.
    """
    beichi = np.zeros(n, dtype=np.int8)
    force = np.full(n, np.nan, dtype=np.float64)
    _detect_buy_sell_points_v41(czsc_obj, czsc_df, bs_type, beichi, force, n)


def _detect_buy_sell_points_v41(
    czsc_obj: Any,
    czsc_df: pd.DataFrame,
    bs_type: np.ndarray,
    beichi_arr: np.ndarray,
    bi_force_arr: np.ndarray,
    n: int,
) -> None:
    """v4.1 buy/sell detection with 1/2/3 classes + MACD/force 背驰.

    - 1buy: down stroke ends below ZD **and** bottom divergence (force/MACD)
    - 2buy: first pullback after 1buy that holds above the 1buy low
    - 3buy: pullback after leaving center that stays above ZG
    - Mirror for sell points. Marks are written at stroke end bars only.
    """
    try:
        bi_list = getattr(czsc_obj, 'bi_list', []) or []
    except Exception:
        return
    if len(bi_list) < 3:
        return

    close = czsc_df['close'].to_numpy(dtype=np.float64) if 'close' in czsc_df.columns else None
    macd_hist = _macd_hist_from_close(close) if close is not None and len(close) == n else None

    # Per-stroke metrics
    strokes = []  # dicts
    for bi in bi_list:
        s_idx, e_idx = _bi_bar_range(bi, czsc_df)
        direction = _get_bi_direction_int(bi)
        lo, hi = _bi_price_range(bi)
        if hi <= 0 or lo <= 0 or direction == 0:
            continue
        start_p = lo if direction == 1 else hi
        end_p = hi if direction == 1 else lo
        bar_len = max(1, e_idx - s_idx + 1)
        base = start_p if start_p > 0 else 1.0
        price_force = abs(end_p - start_p) / base * bar_len
        macd_force = 0.0
        if macd_hist is not None:
            a = max(0, s_idx)
            b = min(n, e_idx + 1)
            if b > a:
                segment = macd_hist[a:b]
                # Same-direction area magnitude
                if direction == 1:
                    macd_force = float(np.nansum(np.clip(segment, 0, None)))
                else:
                    macd_force = float(np.nansum(np.clip(-segment, 0, None)))
        force = price_force + macd_force
        strokes.append({
            's': s_idx, 'e': e_idx, 'dir': direction,
            'lo': lo, 'hi': hi, 'end_p': end_p, 'force': force,
        })
        # Map force onto bars of this stroke (overwrite; last stroke wins)
        for j in range(max(0, s_idx), min(e_idx + 1, n)):
            bi_force_arr[j] = force

    centers = _build_centers_from_bi(bi_list, czsc_df)

    last_1buy_low: Optional[float] = None
    last_1buy_idx: int = -1
    last_1sell_high: Optional[float] = None
    last_1sell_idx: int = -1
    saw_leave_above = False  # left center upward (for 3buy)
    saw_leave_below = False
    last_up_force: Optional[float] = None
    last_dn_force: Optional[float] = None

    for i, st in enumerate(strokes):
        e = st['e']
        if e < 0 or e >= n:
            continue
        zd_zg = _active_center_at(centers, e)
        zd = zd_zg[0] if zd_zg else None
        zg = zd_zg[1] if zd_zg else None

        # ── Divergence vs previous same-direction stroke ──
        beichi = 0
        if st['dir'] == -1 and last_dn_force is not None and st['force'] < last_dn_force * 0.95:
            beichi = 1  # 底背驰
        elif st['dir'] == 1 and last_up_force is not None and st['force'] < last_up_force * 0.95:
            beichi = -1  # 顶背驰
        if beichi != 0:
            beichi_arr[e] = beichi

        # Track leave-center for 3-class
        if zd is not None and zg is not None:
            if st['dir'] == 1 and st['end_p'] > zg:
                saw_leave_above = True
                saw_leave_below = False
            elif st['dir'] == -1 and st['end_p'] < zd:
                saw_leave_below = True
                saw_leave_above = False

        mark = ''

        # ── 1buy / 1sell (require 背驰 when prior same-dir force exists) ──
        if zd is not None and zg is not None:
            if st['dir'] == -1 and st['end_p'] < zd:
                has_prior = last_dn_force is not None
                if (not has_prior) or beichi == 1:
                    mark = '1buy'
                    last_1buy_low = st['lo']
                    last_1buy_idx = e
            elif st['dir'] == 1 and st['end_p'] > zg:
                has_prior = last_up_force is not None
                if (not has_prior) or beichi == -1:
                    mark = '1sell'
                    last_1sell_high = st['hi']
                    last_1sell_idx = e

        # ── 2buy / 2sell ──
        if not mark and last_1buy_low is not None and e > last_1buy_idx:
            # First down stroke after 1buy that holds above 1buy low
            if st['dir'] == -1 and st['lo'] > last_1buy_low:
                # Prefer after an intervening up stroke
                if i >= 1 and strokes[i - 1]['dir'] == 1:
                    mark = '2buy'
                    last_1buy_low = None  # consume
        if not mark and last_1sell_high is not None and e > last_1sell_idx:
            if st['dir'] == 1 and st['hi'] < last_1sell_high:
                if i >= 1 and strokes[i - 1]['dir'] == -1:
                    mark = '2sell'
                    last_1sell_high = None

        # ── 3buy / 3sell (pullback holds outside center) ──
        if not mark and zd is not None and zg is not None:
            if saw_leave_above and st['dir'] == -1 and st['end_p'] > zg:
                mark = '3buy'
            elif saw_leave_below and st['dir'] == 1 and st['end_p'] < zd:
                mark = '3sell'

        if mark:
            bs_type[e] = mark

        if st['dir'] == 1:
            last_up_force = st['force']
        elif st['dir'] == -1:
            last_dn_force = st['force']


def _compute_v41_aux_features(
    czsc_df: pd.DataFrame,
    zs_zd: np.ndarray,
    zs_zg: np.ndarray,
    zs_level: np.ndarray,
    bi_dir: np.ndarray,
    duan_dir: np.ndarray,
    n: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute v4.1 auxiliary columns (events, volume filters, ml align).

    Returns:
        zs_event, trend_continue, amp_narrow, vol_surge, vol_shrink, prior_low_ok, ml_align
    """
    zs_event = np.array([''] * n, dtype=object)
    trend_continue = np.zeros(n, dtype=np.int8)
    amp_narrow = np.zeros(n, dtype=np.int8)
    vol_surge = np.zeros(n, dtype=np.int8)
    vol_shrink = np.zeros(n, dtype=np.int8)
    prior_low_ok = np.ones(n, dtype=np.int8)
    ml_align = np.zeros(n, dtype=np.int8)

    close = czsc_df['close'].to_numpy(dtype=np.float64) if 'close' in czsc_df.columns else np.full(n, np.nan)
    low = czsc_df['low'].to_numpy(dtype=np.float64) if 'low' in czsc_df.columns else close
    vol_col = 'vol' if 'vol' in czsc_df.columns else ('volume' if 'volume' in czsc_df.columns else None)
    volume = czsc_df[vol_col].to_numpy(dtype=np.float64) if vol_col else np.zeros(n)

    # Volume MA filters
    vol_s = pd.Series(volume)
    vol_ma20 = vol_s.rolling(20, min_periods=5).mean().to_numpy()
    vol_ma10 = vol_s.rolling(10, min_periods=3).mean().to_numpy()
    with np.errstate(invalid='ignore'):
        vol_surge[:] = ((volume > vol_ma20 * 1.5) & np.isfinite(vol_ma20)).astype(np.int8)
        vol_shrink[:] = ((volume < vol_ma10 * 0.7) & np.isfinite(vol_ma10) & (vol_ma10 > 0)).astype(np.int8)

    # Prior-low protection: close >= rolling min low of prior 40 bars (excl current)
    low_s = pd.Series(low)
    prior_min = low_s.shift(1).rolling(40, min_periods=5).min().to_numpy()
    with np.errstate(invalid='ignore'):
        prior_low_ok[:] = np.where(
            np.isfinite(prior_min),
            (close >= prior_min * 0.998).astype(np.int8),
            1,
        )

    # Center amplitude / events / trend continuation across center changes
    amp = zs_zg - zs_zd
    last_zd: Optional[float] = None
    last_zg: Optional[float] = None
    last_amp: Optional[float] = None
    zg_rising = 0
    zd_falling = 0
    for j in range(n):
        zd_j = zs_zd[j]
        zg_j = zs_zg[j]
        lvl = zs_level[j]
        if not (np.isfinite(zd_j) and np.isfinite(zg_j) and zg_j > zd_j and lvl >= 1):
            continue
        amp_j = float(amp[j])
        changed = (
            last_zd is None
            or abs(zd_j - last_zd) > 1e-12
            or abs(zg_j - last_zg) > 1e-12
        )
        if changed:
            if last_zd is None:
                zs_event[j] = 'new'
            else:
                # Expansion: new center overlaps and extends prior range
                overlap = min(zg_j, last_zg) - max(zd_j, last_zd)
                if overlap > 0 and (zg_j - zd_j) > (last_zg - last_zd) * 1.05:
                    zs_event[j] = 'expand'
                elif last_amp is not None and amp_j < last_amp * 0.95:
                    zs_event[j] = 'narrow'
                    amp_narrow[j] = 1
                else:
                    zs_event[j] = 'new'
                # Progressive ZG higher / ZD lower between successive centers
                if zg_j > last_zg * 1.001:
                    zg_rising += 1
                    zd_falling = 0
                elif zd_j < last_zd * 0.999:
                    zd_falling += 1
                    zg_rising = 0
                else:
                    zg_rising = 0
                    zd_falling = 0
            last_zd, last_zg, last_amp = float(zd_j), float(zg_j), amp_j

        if zg_rising >= 1:
            trend_continue[j] = 1
        elif zd_falling >= 1:
            trend_continue[j] = -1

    # Persist amp_narrow / trend_continue briefly after center change
    for j in range(1, n):
        if amp_narrow[j] == 0 and zs_event[j] == '':
            # carry last narrow flag for 20 bars via rolling max below
            pass
    # Rolling persistence of amp_narrow
    amp_s = pd.Series(amp_narrow.astype(np.int8))
    amp_narrow[:] = amp_s.rolling(20, min_periods=1).max().fillna(0).astype(np.int8).to_numpy()

    # Multi-level proxy: bi vs duan alignment
    for j in range(n):
        b = int(bi_dir[j])
        d = int(duan_dir[j])
        if b == 0 or d == 0:
            ml_align[j] = 0
        elif b == d:
            ml_align[j] = 1
        else:
            ml_align[j] = -1

    return zs_event, trend_continue, amp_narrow, vol_surge, vol_shrink, prior_low_ok, ml_align


def _classify_trend(czsc_obj: Any, trend_arr: np.ndarray, n: int) -> None:
    """Classify trend based on stroke sequence.

    Simplified trend detection for czsc 1.0.x (no zs_list):
    - Look at last 5-7 strokes
    - If majority are upward strokes: uptrend (1)
    - If majority are downward strokes: downtrend (-1)
    - Otherwise: consolidation (0)
    """
    try:
        bi_list = getattr(czsc_obj, 'bi_list', []) or []
    except Exception:
        return

    if len(bi_list) < 5:
        # Not enough strokes for trend classification
        return

    # Look at last 5-7 strokes
    recent_strokes = bi_list[-7:] if len(bi_list) >= 7 else bi_list[-5:]
    
    up_count = 0
    down_count = 0
    
    for bi in recent_strokes:
        direction = str(getattr(bi, 'direction', ''))
        if '向上' in direction or 'up' in direction.lower() or direction == '1' or '上升' in direction:
            up_count += 1
        elif '向下' in direction or 'down' in direction.lower() or direction == '-1' or '下降' in direction:
            down_count += 1
    
    # Classify trend
    total = up_count + down_count
    if total == 0:
        return
    
    up_ratio = up_count / total
    down_ratio = down_count / total
    
    if up_ratio >= 0.7:  # 70%+ upward strokes
        trend_val = 1
    elif down_ratio >= 0.7:  # 70%+ downward strokes
        trend_val = -1
    else:
        trend_val = 0

    # Apply trend to all bars (it's a global classification)
    # WARNING: This introduces lookahead bias. Use _classify_trend_causal instead.
    trend_arr[:] = trend_val


def _classify_trend_causal(
    stroke_infos: list,
    confirmation_delay: int,
    trend_arr: np.ndarray,
    n: int,
) -> None:
    """Classify trend causally: at each bar, only use strokes confirmed by that bar.

    This eliminates the lookahead bias of the original _classify_trend which
    applied a global trend (computed from the final strokes) to all historical bars.

    At bar j, only strokes with end_idx + confirmation_delay <= j are "known".
    Among those, the last 5-7 are used for trend classification.

    Args:
        stroke_infos: list of (start_idx, end_idx, dir, start_p, end_p) tuples
        confirmation_delay: bars needed after stroke end to confirm
        trend_arr: output int8 array
        n: number of bars
    """
    if len(stroke_infos) < 5:
        return

    _ptr = 0
    for j in range(n):
        # Advance pointer to include all strokes confirmed by bar j
        while (_ptr < len(stroke_infos)
               and stroke_infos[_ptr][1] + confirmation_delay <= j):
            _ptr += 1
        # Need at least 5 confirmed strokes for trend classification
        if _ptr >= 5:
            _recent = stroke_infos[max(0, _ptr - 7):_ptr]
            _up = sum(1 for s in _recent if s[2] == 1)
            _down = sum(1 for s in _recent if s[2] == -1)
            _total = _up + _down
            if _total > 0:
                _up_r = _up / _total
                _down_r = _down / _total
                if _up_r >= 0.7:
                    trend_arr[j] = 1
                elif _down_r >= 0.7:
                    trend_arr[j] = -1
                else:
                    trend_arr[j] = 0


def _get_bi_direction_int(bi: Any) -> int:
    """Return direction of a stroke as int: 1=up, -1=down, 0=unknown."""
    direction = str(getattr(bi, 'direction', ''))
    if '向上' in direction or 'up' in direction.lower() or direction == '1' or '上升' in direction:
        return 1
    if '向下' in direction or 'down' in direction.lower() or direction == '-1' or '下降' in direction:
        return -1
    return 0


def _detect_duan(
    czsc_obj: Any,
    czsc_df: pd.DataFrame,
    n: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Detect segments (段) from stroke sequence.

    A segment is formed when 3+ consecutive strokes have progressively
    higher highs (upward segment) or lower lows (downward segment).
    This is a simplified heuristic since czsc 1.0 does not expose a
    native duan/segment API on the CZSC object.

    Returns:
        Tuple of (duan_dir, duan_start_price, duan_end_price) arrays.
    """
    duan_dir = np.zeros(n, dtype=np.int8)
    duan_start_price = np.full(n, np.nan, dtype=np.float64)
    duan_end_price = np.full(n, np.nan, dtype=np.float64)

    try:
        bi_list = getattr(czsc_obj, 'bi_list', []) or []
    except Exception:
        return duan_dir, duan_start_price, duan_end_price

    if len(bi_list) < 3:
        return duan_dir, duan_start_price, duan_end_price

    # Walk through strokes and detect segment transitions
    # A segment changes direction when a stroke breaks the previous
    # segment's extreme in the opposite direction.
    seg_start_idx = 0
    seg_dir = _get_bi_direction_int(bi_list[0])
    seg_extreme = 0.0

    # Initialize with first stroke
    first_start, first_end = _bi_bar_range(bi_list[0], czsc_df)
    fx_a = getattr(bi_list[0], 'fx_a', None)
    seg_start_p = float(getattr(fx_a, 'fx', 0)) if fx_a else 0.0
    seg_extreme = seg_start_p

    for i, bi in enumerate(bi_list):
        bi_dir = _get_bi_direction_int(bi)
        start_idx, end_idx = _bi_bar_range(bi, czsc_df)
        fx_b = getattr(bi, 'fx_b', None)
        bi_end_p = float(getattr(fx_b, 'fx', 0)) if fx_b else 0.0

        # Check if segment direction flips
        if bi_dir != 0 and bi_dir != seg_dir:
            # Potential segment break: check if extreme is broken
            break_seg = False
            if seg_dir == 1 and bi_end_p < seg_start_p:
                break_seg = True  # Down stroke broke below segment start
            elif seg_dir == -1 and bi_end_p > seg_start_p:
                break_seg = True  # Up stroke broke above segment start

            if break_seg and i >= 2:
                # Finalize previous segment
                for j in range(max(0, seg_start_idx), min(end_idx, n)):
                    duan_dir[j] = seg_dir
                    duan_start_price[j] = seg_start_p
                    duan_end_price[j] = seg_extreme

                # Start new segment
                seg_dir = bi_dir
                seg_start_idx = start_idx
                seg_start_p = float(getattr(getattr(bi, 'fx_a', None), 'fx', 0)) or bi_end_p
                seg_extreme = bi_end_p
                continue

        # Update segment extreme
        if seg_dir == 1 and bi_end_p > seg_extreme:
            seg_extreme = bi_end_p
        elif seg_dir == -1 and bi_end_p < seg_extreme:
            seg_extreme = bi_end_p

    # Finalize last segment
    if seg_dir != 0:
        last_end_idx = n - 1
        try:
            _, last_end_idx = _bi_bar_range(bi_list[-1], czsc_df)
        except Exception:
            pass
        for j in range(max(0, seg_start_idx), min(last_end_idx + 1, n)):
            duan_dir[j] = seg_dir
            duan_start_price[j] = seg_start_p
            duan_end_price[j] = seg_extreme

    return duan_dir, duan_start_price, duan_end_price


# ---------------------------------------------------------------------------
# Mock columns for validation / dry-run
# ---------------------------------------------------------------------------

def add_mock_czsc_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add placeholder czsc_ columns to a mock DataFrame.

    Used during indicator code validation to prevent KeyError when
    indicator code references czsc_ columns during dry-run.
    """
    result = df.copy()
    n = len(result)
    result['czsc_fx_mark'] = np.zeros(n, dtype=np.int8)
    result['czsc_fx_price'] = np.full(n, np.nan, dtype=np.float64)
    result['czsc_bi_dir'] = np.zeros(n, dtype=np.int8)
    result['czsc_bi_start_price'] = np.full(n, 10000.0, dtype=np.float64)
    result['czsc_bi_end_price'] = np.full(n, 10000.0, dtype=np.float64)
    result['czsc_bi_length'] = np.ones(n, dtype=np.int32)
    result['czsc_duan_dir'] = np.zeros(n, dtype=np.int8)
    result['czsc_duan_start_price'] = np.full(n, 10000.0, dtype=np.float64)
    result['czsc_duan_end_price'] = np.full(n, 10000.0, dtype=np.float64)
    result['czsc_zs_level'] = np.zeros(n, dtype=np.int32)
    result['czsc_zs_zd'] = np.full(n, 9900.0, dtype=np.float64)
    result['czsc_zs_zg'] = np.full(n, 10100.0, dtype=np.float64)
    result['czsc_zs_position'] = np.array(['inside'] * n, dtype=object)
    result['czsc_bs_type'] = np.array([''] * n, dtype=object)
    result['czsc_trend'] = np.zeros(n, dtype=np.int8)
    # v4.1 mock columns
    result['czsc_bi_force'] = np.full(n, 0.0, dtype=np.float64)
    result['czsc_beichi'] = np.zeros(n, dtype=np.int8)
    result['czsc_zs_event'] = np.array([''] * n, dtype=object)
    result['czsc_trend_continue'] = np.zeros(n, dtype=np.int8)
    result['czsc_amp_narrow'] = np.zeros(n, dtype=np.int8)
    result['czsc_vol_surge'] = np.zeros(n, dtype=np.int8)
    result['czsc_vol_shrink'] = np.zeros(n, dtype=np.int8)
    result['czsc_prior_low_ok'] = np.ones(n, dtype=np.int8)
    result['czsc_ml_align'] = np.zeros(n, dtype=np.int8)
    return result
