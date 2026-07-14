"""CZSC (缠论) analysis endpoints for Agent Gateway."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from app.services.czsc_bridge import (
    compute_czsc_features,
    get_czsc_import_error,
    is_czsc_enabled,
)
from app.services.kline import KlineService
from app.utils.agent_auth import (
    SCOPE_R,
    agent_required,
    instrument_allowed,
    market_allowed,
)
from app.utils.logger import get_logger

from . import agent_v1_bp
from ._helpers import clip_int, envelope, error, get_json_or_400

logger = get_logger(__name__)
_kline_service = KlineService()

# Column-name pattern for duan (段) detection
_DUAN_PAT = re.compile(r"^czsc_duan_")


def _count_unique_values_in_col(df: pd.DataFrame, col: str) -> int:
    """Count the number of distinct value transitions in a column."""
    if col not in df.columns:
        return 0
    series = df[col].dropna()
    if series.empty:
        return 0
    shifted = series.shift(1)
    transitions = (series != shifted).sum()
    return max(int(transitions) - 1, 0)


def _extract_signals(df: pd.DataFrame, limit: int = 20) -> list[dict[str, Any]]:
    """Extract recent buy/sell point signals from czsc_bs_type column."""
    bs_col = "czsc_bs_type"
    if bs_col not in df.columns:
        return []

    # Filter rows where bs_type is non-empty
    mask = df[bs_col].astype(str).str.strip() != ""
    signal_rows = df[mask]

    signals: list[dict[str, Any]] = []
    for idx, row in signal_rows.tail(limit).iterrows():
        sig: dict[str, Any] = {
            "index": int(idx) if isinstance(idx, (int, float)) else str(idx),
            "bs_type": row[bs_col],
        }
        # Attach price if available
        for price_col in ("close", "czsc_fx_price"):
            if price_col in df.columns and pd.notna(row.get(price_col)):
                sig["price"] = float(row[price_col])
                break
        # Attach trend
        if "czsc_trend" in df.columns and pd.notna(row.get("czsc_trend")):
            sig["trend"] = int(row["czsc_trend"])
        signals.append(sig)
    return signals


@agent_v1_bp.route("/czsc/status", methods=["GET"])
@agent_required(SCOPE_R)
def czsc_status():
    """Return whether the czsc library is available and its version."""
    czsc_version = None
    if is_czsc_enabled():
        try:
            import czsc
            czsc_version = getattr(czsc, "__version__", "unknown")
        except Exception:
            czsc_version = "unknown"

    return envelope({
        "czsc_available": is_czsc_enabled(),
        "czsc_version": czsc_version,
        "import_error": get_czsc_import_error(),
    })


@agent_v1_bp.route("/czsc/analyze", methods=["POST"])
@agent_required(SCOPE_R)
def czsc_analyze():
    """Run CZSC (缠论) analysis on K-line data and return structural summary.

    JSON body params:
        market     (required) — e.g. 'CNStock', 'Crypto'
        symbol     (required) — e.g. '000001.SZ', 'BTCUSDT'
        timeframe  (optional, default '1H')
        limit      (optional, default 300, range 50..2000)
    """
    body, err = get_json_or_400()
    if err:
        return err

    market = str(body.get("market") or "").strip()
    symbol = str(body.get("symbol") or "").strip()
    timeframe = str(body.get("timeframe") or "1H").strip()
    limit = clip_int(body.get("limit"), default=300, lo=50, hi=2000)

    if not market or not symbol:
        return error(400, "market and symbol are required")
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    # Step 1: Check czsc availability
    if not is_czsc_enabled():
        return error(
            400,
            "czsc library is not installed. Install it with: pip install czsc",
            details={
                "install_command": "pip install czsc",
                "import_error": get_czsc_import_error(),
            },
        )

    # Step 2: Fetch K-line data
    try:
        rows = _kline_service.get_kline(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        ) or []
    except Exception as exc:
        logger.error(f"agent_v1/czsc/analyze kline fetch failed: {exc}", exc_info=True)
        return error(500, "kline fetch failed", details=str(exc), retriable=True, http=502)

    if not rows or len(rows) < 10:
        return error(
            400,
            f"Insufficient data for CZSC analysis: got {len(rows)} bars, need at least 10",
        )

    # Step 3: Convert to DataFrame
    try:
        df = pd.DataFrame(rows)
        # Normalize column names to lowercase for czsc_bridge compatibility
        col_map = {c: c.lower() for c in df.columns}
        df = df.rename(columns=col_map)

        # Ensure required OHLCV columns exist
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                return error(400, f"K-line data missing required column: {col}")

        # Parse datetime index if present
        if "dt" in df.columns:
            df["dt"] = pd.to_datetime(df["dt"])
            df = df.set_index("dt")
        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
    except Exception as exc:
        logger.error(f"agent_v1/czsc/analyze DataFrame conversion failed: {exc}", exc_info=True)
        return error(400, "Failed to convert kline data to DataFrame", details=str(exc))

    # Step 4: Compute CZSC features
    try:
        result_df = compute_czsc_features(df, freq=timeframe, symbol=symbol)
    except Exception as exc:
        logger.error(f"agent_v1/czsc/analyze computation failed: {exc}", exc_info=True)
        return error(500, "CZSC computation failed", details=str(exc), retriable=False)

    # Step 5: Extract czsc_ columns and build summary
    czsc_columns = [c for c in result_df.columns if c.startswith("czsc_")]

    if not czsc_columns:
        return error(
            400,
            "CZSC computation produced no features. Data may be insufficient.",
            details={"bar_count": len(result_df)},
        )

    # Count structural elements by column patterns
    has_duan_cols = any(_DUAN_PAT.match(c) for c in czsc_columns)

    # Count strokes (笔): transitions in czsc_bi_dir
    bi_count = _count_unique_values_in_col(result_df, "czsc_bi_dir")
    # Count duan (段): transitions in czsc_duan columns if present
    duan_count = _count_unique_values_in_col(result_df, "czsc_duan_dir") if has_duan_cols else 0
    # Count zhongshu (中枢): transitions in czsc_zs_level
    zhongshu_count = _count_unique_values_in_col(result_df, "czsc_zs_level")

    # Extract buy/sell signals
    signals = _extract_signals(result_df, limit=20)

    # Latest bar summary
    last = result_df.iloc[-1]
    latest: dict[str, Any] = {}
    for col in czsc_columns:
        val = last[col]
        if isinstance(val, float) and pd.isna(val):
            continue
        # Convert numpy types to Python native for JSON serialization
        if hasattr(val, "item"):
            val = val.item()
        latest[col] = val

    return envelope({
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_count": len(result_df),
        "bi_count": bi_count,
        "duan_count": duan_count,
        "zhongshu_count": zhongshu_count,
        "signals": signals,
        "czsc_columns": czsc_columns,
        "latest": latest,
    })
