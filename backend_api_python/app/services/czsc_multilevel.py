"""
CZSC Multi-Level (多级别联立) Analysis Service for ChanQuant.

Provides cross-frequency structural analysis by:
1. Resampling base-frequency bars to multiple target frequencies
2. Running CZSC analysis on each frequency
3. Combining results into a multi-level structural summary

This enables AI agents to understand market structure across timeframes
(e.g., 5-minute buy point confirmed by 30-minute trend direction).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import pandas as pd

from app.services.czsc_bridge import (
    CZSC_COLUMNS,
    _CZSC_AVAILABLE,
    _TIMEFRAME_TO_FREQ,
    compute_czsc_features,
    is_czsc_enabled,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Supported analysis frequencies (czsc Freq enum values)
_ANALYSIS_FREQS = {
    "1分钟": "1m",
    "5分钟": "5m",
    "15分钟": "15m",
    "30分钟": "30m",
    "60分钟": "1H",
    "120分钟": "2H",
    "240分钟": "4H",
    "日线": "1D",
    "周线": "1W",
    "月线": "1M",
}

# Reverse lookup
_FREQ_TO_TIMEFRAME = {v: k for k, v in _ANALYSIS_FREQS.items()}

# Minimum bars required for meaningful CZSC analysis per frequency
_MIN_BARS_FOR_ANALYSIS = 30


def _try_resample(df: pd.DataFrame, target_freq: str, base_freq: str) -> Optional[pd.DataFrame]:
    """Try to resample DataFrame to target frequency using czsc's resample_bars.

    Falls back to pandas resample if czsc resample is unavailable.
    """
    try:
        from czsc import resample_bars
        result = resample_bars(df, target_freq=target_freq, raw_bars=False, base_freq=base_freq)
        if isinstance(result, pd.DataFrame) and not result.empty:
            return result
        return None
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"czsc resample_bars failed for {target_freq}: {e}")

    # Fallback: pandas resample
    try:
        _PD_FREQ_MAP = {
            "1分钟": "1min", "5分钟": "5min", "15分钟": "15min", "30分钟": "30min",
            "60分钟": "1h", "120分钟": "2h", "240分钟": "4h",
            "日线": "1D", "周线": "1W", "月线": "1ME",
        }
        pd_freq = _PD_FREQ_MAP.get(target_freq)
        if not pd_freq:
            return None

        resampled = df.resample(pd_freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        if len(resampled) < _MIN_BARS_FOR_ANALYSIS:
            return None
        return resampled
    except Exception as e:
        logger.debug(f"pandas resample fallback failed for {target_freq}: {e}")
        return None


def _summarize_freq(df: pd.DataFrame, freq_name: str, timeframe: str) -> Dict[str, Any]:
    """Build a structural summary for one frequency's CZSC analysis."""
    czsc_cols = {c["name"] for c in CZSC_COLUMNS}
    present = [c for c in czsc_cols if c in df.columns]

    summary: Dict[str, Any] = {
        "freq": freq_name,
        "timeframe": timeframe,
        "bar_count": len(df),
    }

    if not present:
        summary["status"] = "no_features"
        return summary

    last = df.iloc[-1]

    # Bi (笔) summary
    if "czsc_bi_dir" in df.columns:
        bi_dir = last.get("czsc_bi_dir")
        summary["bi_direction"] = int(bi_dir) if pd.notna(bi_dir) else None
        # Count bi transitions
        bi_series = df["czsc_bi_dir"].dropna()
        if not bi_series.empty:
            transitions = (bi_series != bi_series.shift(1)).sum()
            summary["bi_count"] = max(int(transitions) - 1, 0)

    # Duan (段) summary
    if "czsc_duan_dir" in df.columns:
        duan_dir = last.get("czsc_duan_dir")
        summary["duan_direction"] = int(duan_dir) if pd.notna(duan_dir) else None

    # Buy/Sell points
    if "czsc_bs_type" in df.columns:
        bs_mask = df["czsc_bs_type"].astype(str).str.strip() != ""
        bs_count = int(bs_mask.sum())
        summary["bs_point_count"] = bs_count
        if bs_count > 0:
            last_bs = df[bs_mask].tail(1)
            if not last_bs.empty:
                summary["last_bs_type"] = str(last_bs.iloc[0].get("czsc_bs_type", ""))

    # Trend
    if "czsc_trend" in df.columns:
        trend = last.get("czsc_trend")
        summary["trend"] = int(trend) if pd.notna(trend) else None

    # ZS (中枢) position
    if "czsc_zs_position" in df.columns:
        zs_pos = last.get("czsc_zs_position")
        summary["zs_position"] = str(zs_pos) if pd.notna(zs_pos) else None

    # FX (分型) mark
    if "czsc_fx_mark" in df.columns:
        fx_mark = last.get("czsc_fx_mark")
        summary["latest_fx"] = int(fx_mark) if pd.notna(fx_mark) else None

    summary["status"] = "ok"
    return summary


def analyze_multilevel(
    df: pd.DataFrame,
    base_timeframe: str = "1m",
    target_timeframes: Optional[List[str]] = None,
    *,
    symbol: str = "SYMBOL",
) -> Dict[str, Any]:
    """Run CZSC analysis across multiple timeframes.

    Args:
        df:                Base-frequency OHLCV DataFrame.
        base_timeframe:    Timeframe of the input data (e.g. '1m', '5m', '1H').
        target_timeframes: List of target timeframes to analyze.
                          Defaults to auto-selecting based on data timeframe.
        symbol:            Symbol name for czsc.

    Returns:
        Dict with:
            base_timeframe: str
            levels: list of per-frequency structural summaries
            cross_validation: dict of multi-level consistency checks
    """
    if not is_czsc_enabled():
        return {"error": "czsc not available", "levels": []}

    if target_timeframes is None:
        # Auto-select target timeframes based on base
        target_timeframes = _auto_select_targets(base_timeframe)

    if not target_timeframes:
        return {"error": "No valid target timeframes specified", "levels": []}

    base_czsc_freq = _TIMEFRAME_TO_FREQ.get(base_timeframe, base_timeframe)

    levels: List[Dict[str, Any]] = []
    freq_summaries: Dict[str, Dict[str, Any]] = {}

    # Analyze base timeframe first
    try:
        base_result = compute_czsc_features(df.copy(), freq=base_timeframe, symbol=symbol)
        base_summary = _summarize_freq(base_result, base_czsc_freq, base_timeframe)
        base_summary["is_base"] = True
        levels.append(base_summary)
        freq_summaries[base_czsc_freq] = base_summary
    except Exception as e:
        logger.warning(f"Base timeframe {base_timeframe} analysis failed: {e}")
        levels.append({
            "freq": base_czsc_freq, "timeframe": base_timeframe,
            "status": "error", "error": str(e), "is_base": True,
        })

    # Analyze each target timeframe (skip base) — in parallel
    non_base_tfs = [tf for tf in target_timeframes if tf != base_timeframe]

    def _process_single_freq(tf: str) -> Dict[str, Any]:
        """Process one target timeframe: resample + CZSC + summarize."""
        czsc_freq = _TIMEFRAME_TO_FREQ.get(tf, tf)
        try:
            resampled = _try_resample(df, czsc_freq, base_czsc_freq)
            if resampled is None or len(resampled) < _MIN_BARS_FOR_ANALYSIS:
                return {
                    "freq": czsc_freq, "timeframe": tf,
                    "status": "insufficient_data",
                    "bar_count": len(resampled) if resampled is not None else 0,
                    "_is_base": False,
                }

            result = compute_czsc_features(resampled, freq=tf, symbol=symbol)
            summary = _summarize_freq(result, czsc_freq, tf)
            summary["is_base"] = False
            summary["_is_base"] = False
            return summary
        except Exception as e:
            logger.warning(f"Target timeframe {tf} analysis failed: {e}")
            return {
                "freq": czsc_freq, "timeframe": tf,
                "status": "error", "error": str(e), "is_base": False,
                "_is_base": False,
            }

    if non_base_tfs:
        max_workers = min(len(non_base_tfs), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_single_freq, tf): tf
                for tf in non_base_tfs
            }
            for future in as_completed(futures):
                result_summary = future.result()
                result_summary.pop("_is_base", None)
                levels.append(result_summary)
                if result_summary.get("status") == "ok":
                    freq_key = result_summary.get("freq", "")
                    freq_summaries[freq_key] = result_summary

    # Cross-frequency validation
    cross = _cross_validate(freq_summaries)

    return {
        "base_timeframe": base_timeframe,
        "levels": levels,
        "cross_validation": cross,
    }


def _auto_select_targets(base_timeframe: str) -> List[str]:
    """Auto-select target timeframes based on base timeframe.

    Convention: analyze 2-3 higher timeframes above the base.
    """
    _HIERARCHY = ["1m", "5m", "15m", "30m", "1H", "2H", "4H", "1D", "1W", "1M"]

    try:
        idx = _HIERARCHY.index(base_timeframe)
    except ValueError:
        # Unknown timeframe, default to common set
        return ["5m", "1H", "1D"]

    # Pick 2-3 timeframes above the base
    targets = []
    for offset in (1, 2, 3):
        if idx + offset < len(_HIERARCHY):
            targets.append(_HIERARCHY[idx + offset])

    return targets if targets else [_HIERARCHY[-1]]


def _cross_validate(freq_summaries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Perform cross-frequency consistency checks.

    Returns validation results like trend alignment, bi direction agreement, etc.
    """
    result: Dict[str, Any] = {}

    # Collect trends across frequencies
    trends = {
        freq: s.get("trend")
        for freq, s in freq_summaries.items()
        if s.get("trend") is not None
    }
    if len(trends) >= 2:
        trend_values = list(trends.values())
        all_same = len(set(trend_values)) == 1
        result["trend_alignment"] = {
            "aligned": all_same,
            "trends": {k: _trend_label(v) for k, v in trends.items()},
        }

    # Collect bi directions
    bi_dirs = {
        freq: s.get("bi_direction")
        for freq, s in freq_summaries.items()
        if s.get("bi_direction") is not None
    }
    if len(bi_dirs) >= 2:
        dir_values = list(bi_dirs.values())
        all_same = len(set(dir_values)) == 1
        result["bi_direction_alignment"] = {
            "aligned": all_same,
            "directions": {k: "up" if v == 1 else "down" for k, v in bi_dirs.items()},
        }

    # Collect duan directions
    duan_dirs = {
        freq: s.get("duan_direction")
        for freq, s in freq_summaries.items()
        if s.get("duan_direction") is not None
    }
    if len(duan_dirs) >= 2:
        dir_values = list(duan_dirs.values())
        all_same = len(set(dir_values)) == 1
        result["duan_direction_alignment"] = {
            "aligned": all_same,
            "directions": {k: "up" if v == 1 else "down" for k, v in duan_dirs.items()},
        }

    # Buy/sell point signals across frequencies
    bs_signals = {
        freq: s.get("last_bs_type")
        for freq, s in freq_summaries.items()
        if s.get("last_bs_type")
    }
    if bs_signals:
        result["bs_point_summary"] = {
            "frequencies_with_signals": list(bs_signals.keys()),
            "signals": bs_signals,
        }

    return result


def _trend_label(val: Optional[int]) -> str:
    """Convert trend integer to human label."""
    if val is None:
        return "unknown"
    return {0: "consolidation", 1: "uptrend", -1: "downtrend"}.get(val, f"unknown({val})")
