"""
CZSC (缠论) Pre-computation Bridge for QuantDinger.

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
# Timeframe mapping: QuantDinger -> czsc Freq
# ---------------------------------------------------------------------------
# QuantDinger timeframes: '1m', '5m', '15m', '30m', '1H', '4H', '1D', '1W'
# czsc Freq enum (1.0.x): F1, F5, F15, F30, F60, F240 (or D), D, W

_TIMEFRAME_TO_FREQ: Dict[str, str] = {
    '1m': '1分钟',
    '5m': '5分钟',
    '15m': '15分钟',
    '30m': '30分钟',
    '1H': '60分钟',
    '1h': '60分钟',
    '4H': '日线',     # czsc has no 4H; approximate to daily for structure analysis
    '4h': '日线',
    '1D': '日线',
    '1d': '日线',
    '1W': '周线',
    '1w': '周线',
}


def _map_timeframe_to_freq(timeframe: str) -> Optional[Any]:
    """Map QuantDinger timeframe string to czsc Freq enum."""
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
]


def get_czsc_column_docs() -> str:
    """Return formatted documentation string for all czsc_ columns.

    Used by the AI generation system prompt to teach LLMs about available
    Chan Theory features.
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
# Core: compute czsc features and inject as DataFrame columns
# ---------------------------------------------------------------------------

def compute_czsc_features(
    df: pd.DataFrame,
    freq: str = '1H',
    *,
    force: bool = False,
    symbol: str = 'SYMBOL',
) -> pd.DataFrame:
    """Pre-compute Chan Theory features and inject them as czsc_ columns.

    Args:
        df: Standard OHLCV DataFrame with columns open/high/low/close/volume.
            May have DatetimeIndex or integer index.
        freq: QuantDinger timeframe string (e.g. '1H', '15m', '1D').
        force: If True, compute features even if code doesn't reference czsc_.
        symbol: Symbol name for czsc analysis (default 'SYMBOL').

    Returns:
        A copy of df with czsc_ columns added. If czsc is unavailable or
        computation fails, returns df unchanged (no error).
    """
    if not _CZSC_AVAILABLE:
        return df

    if df is None or len(df) < 10:
        # Need enough bars for meaningful Chan analysis (at least a few strokes)
        return df

    try:
        return _compute_features_inner(df, freq, symbol)
    except Exception as e:
        logger.warning(f"czsc_bridge: feature computation failed: {e}", exc_info=True)
        return df


def _compute_features_inner(df: pd.DataFrame, freq: str, symbol: str = 'SYMBOL') -> pd.DataFrame:
    """Inner implementation: convert to RawBar, run CZSC, map back to df."""
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

    # ---- Step 3: Map fractals (分型) to df index ----
    _map_fractals(czsc_obj, czsc_df, fx_mark, fx_price, n)

    # ---- Step 4: Map strokes (笔) to df index ----
    _map_strokes(czsc_obj, czsc_df, bi_dir, bi_start_price, bi_end_price, bi_length, n)

    # ---- Step 5: Map centers (中枢) to df index ----
    _map_centers(czsc_obj, czsc_df, zs_level, zs_zd, zs_zg, zs_position, n)

    # ---- Step 6: Detect buy/sell points (买卖点) ----
    _detect_buy_sell_points(czsc_obj, czsc_df, bs_type, n)

    # ---- Step 7: Classify trend ----
    _classify_trend(czsc_obj, trend_arr, n)

    # ---- Step 8: Assign columns to result df ----
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

    logger.info(
        f"czsc_bridge: injected {len(CZSC_COLUMNS)} columns "
        f"({len(czsc_obj.bi_list)} strokes, {len(czsc_obj.fx_list)} fractals) "
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
    """Map CZSC centers (中枢) to per-bar arrays."""
    try:
        zs_list = getattr(czsc_obj, 'zs_list', []) or []
    except Exception:
        return

    for level_idx, zs in enumerate(zs_list):
        # Determine the bar range this center spans
        start_idx, end_idx = _get_zs_bar_range(zs, czsc_df, n)
        zd = float(getattr(zs, 'zd', 0) or 0)
        zg = float(getattr(zs, 'zg', 0) or 0)

        # Level: count of component strokes or nesting level
        bis = getattr(zs, 'bis', []) or []
        level = max(1, len(bis) // 3)  # Rough heuristic: 3 strokes per center level

        for j in range(start_idx, min(end_idx + 1, n)):
            zs_level[j] = max(zs_level[j], level)
            zs_zd[j] = zd
            zs_zg[j] = zg

        # Mark position for bars AFTER the center
        for j in range(end_idx, min(end_idx + 1, n)):
            pass  # Position is computed below for all bars

    # Compute position for all bars with a center
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


def _detect_buy_sell_points(czsc_obj: Any, czsc_df: pd.DataFrame,
                            bs_type: np.ndarray, n: int) -> None:
    """Detect Chan Theory buy/sell points (买卖点) based on stroke/center relationships.

    Simplified detection:
    - 1buy (第一类买点): Last downward stroke ends below center ZD (trend reversal)
    - 2buy (第二类买点): First upward pullback after 1buy that holds above 1buy low
    - 3buy (第三类买点): Price pulls back but stays above center ZG (breakout confirmed)
    - Mirror logic for sell points.
    """
    try:
        bi_list = getattr(czsc_obj, 'bi_list', []) or []
    except Exception:
        return

    if len(bi_list) < 3:
        return

    # czsc 1.0.x doesn't expose zs_list directly; compute centers from bi_list
    # A center (中枢) is formed by 3+ consecutive strokes with overlapping price ranges
    # Simplified: use last 3-5 strokes to detect buy/sell points
    last_strokes = bi_list[-5:] if len(bi_list) >= 5 else bi_list
    
    # Compute a simple center from the last few strokes
    if len(last_strokes) >= 3:
        # Get price range overlap
        ranges = []
        for bi in last_strokes[:-1]:  # Exclude last stroke for center definition
            try:
                high = float(getattr(bi.fx_b, 'fx', 0)) if hasattr(bi, 'fx_b') and bi.fx_b else 0
                low = float(getattr(bi.fx_a, 'fx', 0)) if hasattr(bi, 'fx_a') and bi.fx_a else 0
                if high > 0 and low > 0:
                    ranges.append((min(low, high), max(low, high)))
            except Exception:
                pass
        
        if len(ranges) >= 2:
            # Find overlapping range (simplified center)
            zd = max(r[0] for r in ranges)  # Highest low
            zg = min(r[1] for r in ranges)  # Lowest high
            
            if zd < zg:  # Valid center exists
                last_bi = last_strokes[-1]
                last_bi_start_idx, last_bi_end_idx = _bi_bar_range(last_bi, czsc_df)
                
                # Check if last stroke is below/above center
                last_fx = getattr(last_bi, 'fx_b', None)
                if last_fx:
                    last_price = float(getattr(last_fx, 'fx', 0))
                    direction = str(getattr(last_bi, 'direction', ''))
                    _is_down = ('向下' in direction or 'down' in direction.lower()
                                or direction == '-1' or '下降' in direction)
                    _is_up = ('向上' in direction or 'up' in direction.lower()
                              or direction == '1' or '上升' in direction)
                    
                    # 1buy: downward stroke ends below center
                    if _is_down:
                        if last_price < zd:
                            for j in range(max(0, last_bi_end_idx), min(last_bi_end_idx + 1, n)):
                                bs_type[j] = '1buy'
                    
                    # 1sell: upward stroke ends above center
                    elif _is_up:
                        if last_price > zg:
                            for j in range(max(0, last_bi_end_idx), min(last_bi_end_idx + 1, n)):
                                bs_type[j] = '1sell'
                    
                    # 3buy: price pulls back but stays above zg
                    if len(last_strokes) >= 4:
                        prev_bi = last_strokes[-2]
                        prev_dir = str(getattr(prev_bi, 'direction', ''))
                        _prev_up = ('向上' in prev_dir or 'up' in prev_dir.lower()
                                    or prev_dir == '1' or '上升' in prev_dir)
                        if _prev_up:
                            if last_price > zg and _is_down:
                                for j in range(max(0, last_bi_end_idx), min(last_bi_end_idx + 1, n)):
                                    bs_type[j] = '3buy'
                    
                    # 3sell: price pulls back but stays below zd
                    if len(last_strokes) >= 4:
                        prev_bi = last_strokes[-2]
                        prev_dir = str(getattr(prev_bi, 'direction', ''))
                        _prev_down = ('向下' in prev_dir or 'down' in prev_dir.lower()
                                      or prev_dir == '-1' or '下降' in prev_dir)
                        if _prev_down:
                            if last_price < zd and _is_up:
                                for j in range(max(0, last_bi_end_idx), min(last_bi_end_idx + 1, n)):
                                    bs_type[j] = '3sell'


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
    trend_arr[:] = trend_val


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
    result['czsc_zs_level'] = np.zeros(n, dtype=np.int32)
    result['czsc_zs_zd'] = np.full(n, 9900.0, dtype=np.float64)
    result['czsc_zs_zg'] = np.full(n, 10100.0, dtype=np.float64)
    result['czsc_zs_position'] = np.array(['inside'] * n, dtype=object)
    result['czsc_bs_type'] = np.array([''] * n, dtype=object)
    result['czsc_trend'] = np.zeros(n, dtype=np.int8)
    return result
