"""
CZSC Signal Registry & Computation Service for ChanQuant.

Exposes czsc 1.0's 250+ signal functions to the Agent API and AI prompt:
  - list_czsc_signals():       enumerate all registered signals with metadata
  - compute_czsc_signal_columns():  compute selected signals as DataFrame columns
  - get_signal_docs_for_prompt():   generate signal reference docs for AI prompts

If czsc is not installed, list_czsc_signals() returns [] and
compute_czsc_signal_columns() returns the original DataFrame unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from app.services.czsc_bridge import (
    _CZSC_AVAILABLE,
    _CZSC_IMPORT_ERROR,
    _TIMEFRAME_TO_FREQ,
    is_czsc_enabled,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Graceful import of czsc native signal APIs
# ---------------------------------------------------------------------------
_list_all_signals = None
_generate_czsc_signals = None
_format_standard_kline = None

if _CZSC_AVAILABLE:
    try:
        from czsc._native import list_all_signals as _list_all_signals
        from czsc.traders import generate_czsc_signals as _generate_czsc_signals
        from czsc import format_standard_kline as _format_standard_kline
    except ImportError as e:
        logger.debug(f"czsc signal APIs not available: {e}")
    except Exception as e:
        logger.warning(f"czsc signal API import failed: {e}")


# ---------------------------------------------------------------------------
# Signal namespace → human-readable description (for AI prompt)
# ---------------------------------------------------------------------------
_NAMESPACE_DOCS: Dict[str, str] = {
    "bar":   "K 线形态信号：K 线组合形态、突破、缺口等",
    "cxt":   "缠论上下文信号：笔端点、买卖点、中枢突破/离开、趋势判定等",
    "tas":   "技术指标信号：MA/MACD/KDJ/Bollinger/ATR/RSI/CCI/SAR 等",
    "vol":   "成交量信号：量比、量价背离、缩量/放量等",
    "obv":   "OBV（能量潮）信号：OBV 趋势与背离",
    "cvolp": "成交量加权信号：成交量分布特征",
    "pressure": "支撑压力信号：前高前低、密集成交区、通道线等",
    "jcc":   "日本蜡烛图形态：三法、吞没、星线、锤子、乌云盖顶等",
    "ntmdk": "NTMDK 形态信号",
    "kcatr": "K 线 + ATR 复合信号",
    "clv":   "CLV（收盘位置值）信号",
    "ang":   "角度相关信号：笔/段斜率与角度",
    "coo":   "连续开盘缺口信号",
    "byi":   "笔延伸信号",
    "xl":    "线段/小级别联立信号",
    "zdy":   "自定义复合信号",
    "cxt_trader": "缠论交易级信号：结合多结构的复合买卖信号",
    "pos":   "持仓管理信号：仓位建议、加减仓等",
    "cat":   "分类信号",
}


# ---------------------------------------------------------------------------
# Public API: list signals
# ---------------------------------------------------------------------------

def list_czsc_signals(
    include_kline: bool = True,
    include_trader: bool = True,
) -> List[Dict[str, Any]]:
    """Return all registered czsc signal functions.

    Each entry is a dict with keys:
        name           - signal function name (e.g. 'cxt_bi_end_V240526')
        param_template - example params dict (e.g. {'freq': '30分钟'})
        category       - 'kline' or 'trader'
        namespace      - module prefix (e.g. 'cxt', 'tas', 'jcc', 'vol')

    Returns [] if czsc is not installed.
    """
    if _list_all_signals is None:
        return []
    try:
        raw = _list_all_signals(include_kline=include_kline, include_trader=include_trader)
        return list(raw)
    except Exception as e:
        logger.warning(f"list_all_signals failed: {e}")
        return []


def list_signals_grouped(
    include_kline: bool = True,
    include_trader: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return signals grouped by namespace.

    Returns:
        Dict mapping namespace → list of signal info dicts.
    """
    signals = list_czsc_signals(include_kline, include_trader)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for sig in signals:
        ns = sig.get("namespace", "other")
        grouped.setdefault(ns, []).append(sig)
    return grouped


# ---------------------------------------------------------------------------
# Public API: compute signals
# ---------------------------------------------------------------------------

def compute_czsc_signal_columns(
    df: pd.DataFrame,
    signals_config: List[Dict[str, Any]],
    freq: str = "1H",
    *,
    symbol: str = "SYMBOL",
    sdt: str = "20170101",
    init_n: int = 500,
) -> pd.DataFrame:
    """Compute selected czsc signal functions and merge results into df.

    Args:
        df:             Standard OHLCV DataFrame (open/high/low/close/volume).
        signals_config: List of signal config dicts. Each must have 'name' key
                        (signal function name) plus any required params.
                        Example: [{'name': 'cxt_bi_end_V240526', 'freq': '30分钟'}]
        freq:           ChanQuant timeframe string (e.g. '1H', '15m', '1D').
        symbol:         Symbol name for czsc.
        sdt:            Signal computation start date ('YYYYMMDD').
        init_n:         Number of warmup bars before signal computation starts.

    Returns:
        Original df with signal result columns merged in.
        Signal columns are prefixed with 'czsc_signal_' to avoid collisions.
        Returns original df unchanged on failure.
    """
    if not is_czsc_enabled() or _generate_czsc_signals is None or _format_standard_kline is None:
        logger.warning("czsc signal APIs not available, returning df unchanged")
        return df

    if not signals_config:
        return df

    if len(df) < 10:
        logger.warning(f"Insufficient data for signal computation: {len(df)} bars")
        return df

    try:
        # Step 1: Convert DataFrame → list[RawBar] via format_standard_kline
        czsc_freq = _TIMEFRAME_TO_FREQ.get(freq, freq)

        work_df = df.copy()
        # Ensure dt column exists
        if "dt" not in work_df.columns:
            if isinstance(work_df.index, pd.DatetimeIndex):
                work_df["dt"] = work_df.index
            else:
                work_df["dt"] = pd.date_range("2020-01-01", periods=len(work_df), freq="min")

        # Rename volume → vol for czsc convention
        if "volume" in work_df.columns and "vol" not in work_df.columns:
            work_df["vol"] = work_df["volume"]
        if "amount" not in work_df.columns:
            work_df["amount"] = 0.0

        work_df["symbol"] = symbol

        # tz-naive dt (czsc requirement)
        if hasattr(work_df["dt"].dtype, "tz") and work_df["dt"].dt.tz is not None:
            work_df["dt"] = work_df["dt"].dt.tz_localize(None)

        raw_bars = _format_standard_kline(work_df, freq=czsc_freq)
        if not raw_bars:
            logger.warning("format_standard_kline returned empty bars")
            return df

        # Step 2: Generate signals
        result = _generate_czsc_signals(
            bars=raw_bars,
            signals_config=signals_config,
            sdt=sdt,
            init_n=min(init_n, len(raw_bars) - 1),
            df=False,  # return list[dict]
        )

        if not result:
            logger.warning("generate_czsc_signals returned empty results")
            return df

        # Step 3: Build signal DataFrame and merge
        signal_df = pd.DataFrame(result)

        # Prefix columns with czsc_signal_ to avoid collisions
        rename_map = {c: f"czsc_signal_{c}" for c in signal_df.columns if c != "dt"}
        signal_df = signal_df.rename(columns=rename_map)

        # Align lengths: signal results may be shorter than df (init_n warmup excluded)
        # Pad with NaN at the front to match df length
        n_pad = len(df) - len(signal_df)
        if n_pad > 0:
            pad_df = pd.DataFrame(
                {col: [None] * n_pad for col in signal_df.columns},
                index=signal_df.columns,  # dummy, will be reset
            )
            # Build padded DataFrame properly
            pad_data = {}
            for col in signal_df.columns:
                pad_data[col] = [None] * n_pad + signal_df[col].tolist()
            signal_df = pd.DataFrame(pad_data, index=df.index)
        elif n_pad < 0:
            # signal_df is longer — trim from front
            signal_df = signal_df.iloc[-n_pad:].reset_index(drop=True)
            signal_df.index = df.index

        # Drop 'dt' column if it exists in signal_df (we use df's own index)
        dt_col = None
        for c in signal_df.columns:
            if c == "dt" or c.endswith("_dt"):
                dt_col = c
                break
        if dt_col and dt_col in signal_df.columns:
            signal_df = signal_df.drop(columns=[dt_col])

        # Merge signal columns into original df
        for col in signal_df.columns:
            df[col] = signal_df[col].values

        logger.info(
            f"Computed {len(signal_df.columns)} czsc signal columns "
            f"for {len(df)} bars ({len(signals_config)} signal configs)"
        )
        return df

    except Exception as e:
        logger.error(f"compute_czsc_signal_columns failed: {e}", exc_info=True)
        return df


# ---------------------------------------------------------------------------
# Public API: AI prompt documentation
# ---------------------------------------------------------------------------

def get_signal_docs_for_prompt(
    namespace_filter: Optional[Sequence[str]] = None,
    max_per_namespace: int = 15,
) -> str:
    """Generate signal function reference documentation for AI prompt injection.

    Args:
        namespace_filter: If provided, only include signals from these namespaces.
                         E.g. ['cxt', 'tas', 'jcc'] for core modules.
        max_per_namespace: Max signal examples per namespace to keep prompt concise.

    Returns:
        Markdown-formatted documentation string. Empty string if czsc unavailable.
    """
    signals = list_czsc_signals()
    if not signals:
        return ""

    # Group by namespace
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for sig in signals:
        ns = sig.get("namespace", "other")
        if namespace_filter and ns not in namespace_filter:
            continue
        grouped.setdefault(ns, []).append(sig)

    if not grouped:
        return ""

    lines = [
        "## CZSC 信号函数参考 (Signal Functions Reference)",
        "",
        "czsc 1.0 提供 250+ 信号函数，可通过 `czsc_signal_*` 列访问。",
        "以下是按模块分类的信号函数列表，策略代码可引用这些信号作为买卖条件。",
        "",
    ]

    # Sort namespaces for consistent output
    for ns in sorted(grouped.keys()):
        sigs = grouped[ns]
        desc = _NAMESPACE_DOCS.get(ns, "")
        lines.append(f"### {ns} 模块" + (f" — {desc}" if desc else ""))
        lines.append("")

        # Show up to max_per_namespace examples
        shown = sigs[:max_per_namespace]
        for sig in shown:
            name = sig.get("name", "")
            params = sig.get("param_template", {})
            if not isinstance(params, dict):
                params = {}
            params_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else ""
            lines.append(f"- `{name}`" + (f" ({params_str})" if params_str else ""))

        remaining = len(sigs) - len(shown)
        if remaining > 0:
            lines.append(f"- ... 及其他 {remaining} 个信号函数")
        lines.append("")

    # Add typical combination patterns
    lines.extend([
        "### 典型信号组合模式",
        "",
        "- **MACD 背驰买点**: `cxt_bi_end` (笔结束) + `tas_macd_bs1` (MACD 第一类买卖点)",
        "- **中枢突破**: `cxt_zs_break` (中枢突破) + `vol_volume_increase` (放量确认)",
        "- **趋势过滤**: `cxt_trend` (趋势方向) + `tas_ma_cross` (均线交叉)",
        "- **K 线形态 + 缠论**: `jcc_*` (蜡烛图形态) + `cxt_buy_point` (缠论买点)",
        "- **多指标共振**: `tas_kdj_golden_cross` + `tas_macd_golden_cross` + `cxt_bi_end`",
        "",
    ])

    return "\n".join(lines)
