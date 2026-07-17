"""CZSC (缠论) analysis endpoints for Agent Gateway.

Endpoints:
    GET  /czsc/status          - czsc availability check
    POST /czsc/analyze         - run CZSC structural analysis
    GET  /czsc/signals         - list all registered signal functions
    POST /czsc/signals/compute - compute selected signals on K-line data
    POST /czsc/multilevel      - multi-timeframe joint analysis
    POST /czsc/resample        - resample bars to target frequency
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from app.services.czsc_bridge import (
    compute_czsc_features,
    get_czsc_import_error,
    is_czsc_enabled,
)
from app.services.czsc_signals import (
    compute_czsc_signal_columns,
    get_signal_docs_for_prompt,
    list_czsc_signals,
    list_signals_grouped,
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


@agent_v1_bp.route("/czsc/signals", methods=["GET"])
@agent_required(SCOPE_R)
def czsc_list_signals():
    """List all available czsc signal functions.

    Query params:
        grouped    (optional, default 'true')  - group results by namespace
        namespace  (optional)                   - filter by namespace(s), comma-separated
        category   (optional)                   - 'kline' or 'trader'
    """
    from flask import request as _req

    if not is_czsc_enabled():
        return error(400, "czsc library not available", details={"import_error": get_czsc_import_error()})

    grouped = str(_req.args.get("grouped", "true")).lower() in ("true", "1", "yes")
    ns_filter = _req.args.get("namespace")
    category = _req.args.get("category")

    include_kline = category in (None, "", "kline", "both")
    include_trader = category in (None, "", "trader", "both")

    if grouped:
        result = list_signals_grouped(include_kline=include_kline, include_trader=include_trader)
        if ns_filter:
            ns_set = {s.strip() for s in ns_filter.split(",")}
            result = {k: v for k, v in result.items() if k in ns_set}
        total = sum(len(v) for v in result.values())
        return envelope({"grouped": True, "total": total, "namespaces": result})
    else:
        result = list_czsc_signals(include_kline=include_kline, include_trader=include_trader)
        if ns_filter:
            ns_set = {s.strip() for s in ns_filter.split(",")}
            result = [s for s in result if s.get("namespace") in ns_set]
        return envelope({"grouped": False, "total": len(result), "signals": result})


@agent_v1_bp.route("/czsc/signals/compute", methods=["POST"])
@agent_required(SCOPE_R)
def czsc_compute_signals():
    """Compute selected czsc signal functions on K-line data.

    JSON body params:
        market         (required) — e.g. 'CNStock', 'Crypto'
        symbol         (required) — e.g. '000001.SZ', 'BTCUSDT'
        timeframe      (optional, default '1H')
        limit          (optional, default 500, range 100..3000)
        signals_config (required) — list of signal config dicts, each with 'name' key
        sdt            (optional, default '20170101') — signal computation start date
        init_n         (optional, default 500) — warmup bar count
    """
    body, err = get_json_or_400()
    if err:
        return err

    market = str(body.get("market") or "").strip()
    symbol = str(body.get("symbol") or "").strip()
    timeframe = str(body.get("timeframe") or "1H").strip()
    limit = clip_int(body.get("limit"), default=500, lo=100, hi=3000)
    signals_config = body.get("signals_config")
    sdt = str(body.get("sdt") or "20170101").strip()
    init_n = clip_int(body.get("init_n"), default=500, lo=10, hi=2000)

    if not market or not symbol:
        return error(400, "market and symbol are required")
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    if not signals_config or not isinstance(signals_config, list):
        return error(400, "signals_config must be a non-empty list of signal config dicts")

    # Validate each config has 'name'
    for i, cfg in enumerate(signals_config):
        if not isinstance(cfg, dict) or "name" not in cfg:
            return error(400, f"signals_config[{i}] must be a dict with 'name' key")

    if not is_czsc_enabled():
        return error(400, "czsc library not available", details={"import_error": get_czsc_import_error()})

    # Fetch K-line data
    try:
        rows = _kline_service.get_kline(
            market=market, symbol=symbol, timeframe=timeframe, limit=limit,
        ) or []
    except Exception as exc:
        logger.error(f"agent_v1/czsc/signals/compute kline fetch failed: {exc}", exc_info=True)
        return error(500, "kline fetch failed", details=str(exc), retriable=True, http=502)

    if not rows or len(rows) < 10:
        return error(400, f"Insufficient data: got {len(rows)} bars, need at least 10")

    # Build DataFrame
    try:
        df = pd.DataFrame(rows)
        col_map = {c: c.lower() for c in df.columns}
        df = df.rename(columns=col_map)
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                return error(400, f"K-line data missing column: {col}")
        if "dt" in df.columns:
            df["dt"] = pd.to_datetime(df["dt"])
            df = df.set_index("dt")
        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
    except Exception as exc:
        logger.error(f"agent_v1/czsc/signals/compute DataFrame build failed: {exc}", exc_info=True)
        return error(400, "Failed to build DataFrame", details=str(exc))

    # Compute signals
    try:
        result_df = compute_czsc_signal_columns(
            df, signals_config=signals_config, freq=timeframe,
            symbol=symbol, sdt=sdt, init_n=init_n,
        )
    except Exception as exc:
        logger.error(f"agent_v1/czsc/signals/compute computation failed: {exc}", exc_info=True)
        return error(500, "Signal computation failed", details=str(exc), retriable=False)

    # Extract czsc_signal_ columns
    signal_cols = [c for c in result_df.columns if c.startswith("czsc_signal_")]
    if not signal_cols:
        return error(
            400,
            "Signal computation produced no results. Check signal names or data sufficiency.",
            details={"bar_count": len(result_df), "configs_count": len(signals_config)},
        )

    # Build latest row values for signal columns
    last = result_df.iloc[-1]
    latest: dict[str, Any] = {}
    for col in signal_cols:
        val = last[col]
        if isinstance(val, float) and pd.isna(val):
            continue
        if hasattr(val, "item"):
            val = val.item()
        latest[col] = val

    return envelope({
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_count": len(result_df),
        "signal_columns": signal_cols,
        "signal_count": len(signal_cols),
        "latest": latest,
    })


@agent_v1_bp.route("/czsc/multilevel", methods=["POST"])
@agent_required(SCOPE_R)
def czsc_multilevel():
    """Multi-timeframe CZSC joint analysis.

    JSON body params:
        market              (required) — e.g. 'CNStock', 'Crypto'
        symbol              (required) — e.g. '000001.SZ', 'BTCUSDT'
        timeframe           (optional, default '5m') — base timeframe
        limit               (optional, default 500, range 100..3000)
        target_timeframes   (optional) — list of target timeframes to analyze
    """
    body, err = get_json_or_400()
    if err:
        return err

    market = str(body.get("market") or "").strip()
    symbol = str(body.get("symbol") or "").strip()
    timeframe = str(body.get("timeframe") or "5m").strip()
    limit = clip_int(body.get("limit"), default=500, lo=100, hi=3000)
    target_tfs = body.get("target_timeframes")

    if not market or not symbol:
        return error(400, "market and symbol are required")
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    if not is_czsc_enabled():
        return error(400, "czsc library not available", details={"import_error": get_czsc_import_error()})

    # Validate target_timeframes
    if target_tfs is not None:
        if not isinstance(target_tfs, list) or not all(isinstance(t, str) for t in target_tfs):
            return error(400, "target_timeframes must be a list of timeframe strings")

    # Fetch K-line data
    try:
        rows = _kline_service.get_kline(
            market=market, symbol=symbol, timeframe=timeframe, limit=limit,
        ) or []
    except Exception as exc:
        logger.error(f"agent_v1/czsc/multilevel kline fetch failed: {exc}", exc_info=True)
        return error(500, "kline fetch failed", details=str(exc), retriable=True, http=502)

    if not rows or len(rows) < 10:
        return error(400, f"Insufficient data: got {len(rows)} bars, need at least 10")

    # Build DataFrame
    try:
        df = pd.DataFrame(rows)
        col_map = {c: c.lower() for c in df.columns}
        df = df.rename(columns=col_map)
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                return error(400, f"K-line data missing column: {col}")
        if "volume" not in df.columns:
            df["volume"] = 0
        if "dt" in df.columns:
            df["dt"] = pd.to_datetime(df["dt"])
            df = df.set_index("dt")
        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
    except Exception as exc:
        logger.error(f"agent_v1/czsc/multilevel DataFrame build failed: {exc}", exc_info=True)
        return error(400, "Failed to build DataFrame", details=str(exc))

    # Run multi-level analysis
    try:
        from app.services.czsc_multilevel import analyze_multilevel
        result = analyze_multilevel(
            df, base_timeframe=timeframe,
            target_timeframes=target_tfs, symbol=symbol,
        )
    except Exception as exc:
        logger.error(f"agent_v1/czsc/multilevel analysis failed: {exc}", exc_info=True)
        return error(500, "Multi-level analysis failed", details=str(exc), retriable=False)

    result["market"] = market
    result["symbol"] = symbol
    return envelope(result)


@agent_v1_bp.route("/czsc/resample", methods=["POST"])
@agent_required(SCOPE_R)
def czsc_resample():
    """Resample K-line bars to a target frequency.

    Uses czsc's Rust-backed resample_bars when available, falls back to pandas.

    JSON body params:
        market       (required) — e.g. 'CNStock', 'Crypto'
        symbol       (required) — e.g. '000001.SZ', 'BTCUSDT'
        timeframe    (optional, default '1m') — source timeframe
        target_freq  (required) — target frequency (e.g. '5分钟', '60分钟', '日线')
        limit        (optional, default 500, range 100..5000)
    """
    body, err = get_json_or_400()
    if err:
        return err

    market = str(body.get("market") or "").strip()
    symbol = str(body.get("symbol") or "").strip()
    timeframe = str(body.get("timeframe") or "1m").strip()
    target_freq = str(body.get("target_freq") or "").strip()
    limit = clip_int(body.get("limit"), default=500, lo=100, hi=5000)

    if not market or not symbol:
        return error(400, "market and symbol are required")
    if not target_freq:
        return error(400, "target_freq is required (e.g. '5分钟', '60分钟', '日线')")
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    # Fetch K-line data
    try:
        rows = _kline_service.get_kline(
            market=market, symbol=symbol, timeframe=timeframe, limit=limit,
        ) or []
    except Exception as exc:
        logger.error(f"agent_v1/czsc/resample kline fetch failed: {exc}", exc_info=True)
        return error(500, "kline fetch failed", details=str(exc), retriable=True, http=502)

    if not rows or len(rows) < 10:
        return error(400, f"Insufficient data: got {len(rows)} bars, need at least 10")

    # Build DataFrame
    try:
        df = pd.DataFrame(rows)
        col_map = {c: c.lower() for c in df.columns}
        df = df.rename(columns=col_map)
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                return error(400, f"K-line data missing column: {col}")
        if "volume" not in df.columns:
            df["volume"] = 0
        if "dt" in df.columns:
            df["dt"] = pd.to_datetime(df["dt"])
            df = df.set_index("dt")
        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
    except Exception as exc:
        logger.error(f"agent_v1/czsc/resample DataFrame build failed: {exc}", exc_info=True)
        return error(400, "Failed to build DataFrame", details=str(exc))

    # Resample
    try:
        from app.services.czsc_multilevel import _try_resample
        from app.services.czsc_bridge import _TIMEFRAME_TO_FREQ
        base_czsc_freq = _TIMEFRAME_TO_FREQ.get(timeframe, timeframe)
        result_df = _try_resample(df, target_freq, base_czsc_freq)
        if result_df is None or result_df.empty:
            return error(400, f"Resample to {target_freq} failed or produced empty result")

        # Convert to records
        records = result_df.reset_index().to_dict(orient="records")
        # Ensure JSON-serializable
        for rec in records:
            for k, v in rec.items():
                if isinstance(v, pd.Timestamp):
                    rec[k] = v.isoformat()
                elif hasattr(v, "item"):
                    rec[k] = v.item()

        return envelope({
            "market": market,
            "symbol": symbol,
            "source_timeframe": timeframe,
            "target_freq": target_freq,
            "bar_count": len(result_df),
            "bars": records[-100:],  # Return last 100 bars to keep response small
        })
    except Exception as exc:
        logger.error(f"agent_v1/czsc/resample failed: {exc}", exc_info=True)
        return error(500, "Resample failed", details=str(exc), retriable=False)
