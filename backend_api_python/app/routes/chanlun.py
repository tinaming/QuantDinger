"""ChanLun (缠论) aggregated analysis API — ChanQuant core experience.

Endpoints:
    GET  /api/chanlun/analyze    — Full CZSC analysis for a single symbol
    GET  /api/chanlun/structure  — Structural summary (bi, center, buy/sell pt)
    POST /api/chanlun/scan       — Parallel multi-symbol CZSC signal scan
    GET  /api/chanlun/templates  — List pre-built ChanLun strategy templates
    POST /api/chanlun/templates/<template_id>/apply — Get template code
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
from flask import request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.services.czsc_bridge import (
    compute_czsc_features,
    get_czsc_import_error,
    is_czsc_enabled,
)
from app.services.kline import KlineService
from app.markets.cn_stock_hours import is_cn_market_open, get_cn_market_session, next_cn_market_event
from app.data_sources.cn_stock_batch import get_batch_fetcher
from app.utils.auth import login_required
from app.utils.logger import get_logger

logger = get_logger(__name__)

chanlun_blp = Blueprint(
    "chanlun",
    __name__,
    description="ChanLun (缠论) aggregated analysis API — ChanQuant core experience.",
)

_kline_service = KlineService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """Convert kline rows to a DataFrame suitable for compute_czsc_features."""
    df = pd.DataFrame(rows)
    col_map = {c: c.lower() for c in df.columns}
    df = df.rename(columns=col_map)
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"K-line data missing column: {col}")
    if "volume" not in df.columns:
        df["volume"] = 0
    if "dt" in df.columns:
        df["dt"] = pd.to_datetime(df["dt"])
        df = df.set_index("dt")
    elif "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    return df


def _extract_structure(df: pd.DataFrame) -> dict[str, Any]:
    """Extract structural summary from a CZSC-annotated DataFrame."""
    if df is None or len(df) == 0:
        return {}

    last = df.iloc[-1]
    result: dict[str, Any] = {}

    # Current stroke direction
    if "czsc_bi_dir" in df.columns:
        bi_dir = last.get("czsc_bi_dir")
        if pd.notna(bi_dir):
            bi_dir = int(bi_dir)
            result["bi_direction"] = {1: "up", -1: "down"}.get(bi_dir, "none")

    # Latest fractal
    if "czsc_fx_mark" in df.columns:
        fx = last.get("czsc_fx_mark")
        if pd.notna(fx):
            fx = int(fx)
            result["latest_fx"] = {1: "top", -1: "bottom"}.get(fx, "none")

    # Current segment direction
    if "czsc_duan_dir" in df.columns:
        duan = last.get("czsc_duan_dir")
        if pd.notna(duan):
            duan = int(duan)
            result["duan_direction"] = {1: "up", -1: "down"}.get(duan, "none")

    # Recent center (中枢)
    if "czsc_zs_zd" in df.columns and "czsc_zs_zg" in df.columns:
        zd = last.get("czsc_zs_zd")
        zg = last.get("czsc_zs_zg")
        if pd.notna(zd) and pd.notna(zg):
            result["center"] = {"zd": float(zd), "zg": float(zg)}

    # ZS position
    if "czsc_zs_position" in df.columns:
        pos = last.get("czsc_zs_position")
        if pd.notna(pos) and str(pos).strip():
            result["zs_position"] = str(pos)

    # Recent buy/sell point
    if "czsc_bs_type" in df.columns:
        bs_mask = df["czsc_bs_type"].astype(str).str.strip() != ""
        if bs_mask.any():
            last_bs_row = df[bs_mask].iloc[-1]
            result["last_bs_type"] = str(last_bs_row["czsc_bs_type"])
            result["bs_point_count"] = int(bs_mask.sum())

    # Trend
    if "czsc_trend" in df.columns:
        trend = last.get("czsc_trend")
        if pd.notna(trend):
            result["trend"] = {1: "uptrend", -1: "downtrend"}.get(int(trend), "consolidation")

    return result


def _analyze_one_symbol(symbol: str, market: str, timeframe: str, limit: int) -> dict[str, Any]:
    """Run CZSC analysis for one symbol and return summary dict."""
    try:
        rows = _kline_service.get_kline(
            market=market, symbol=symbol, timeframe=timeframe, limit=limit,
        ) or []
        if not rows or len(rows) < 10:
            return {
                "symbol": symbol, "status": "insufficient_data",
                "bar_count": len(rows),
            }
        df = _rows_to_dataframe(rows)
        result_df = compute_czsc_features(df, freq=timeframe, symbol=symbol)
        structure = _extract_structure(result_df)
        czsc_cols = [c for c in result_df.columns if c.startswith("czsc_")]

        # Extract recent buy/sell signals
        bs_col = "czsc_bs_type"
        signals: list[dict[str, Any]] = []
        if bs_col in result_df.columns:
            mask = result_df[bs_col].astype(str).str.strip() != ""
            for idx, row in result_df[mask].tail(5).iterrows():
                sig: dict[str, Any] = {
                    "bs_type": row[bs_col],
                    "index": int(idx) if isinstance(idx, (int, float)) else str(idx),
                }
                if "close" in result_df.columns and pd.notna(row.get("close")):
                    sig["price"] = float(row["close"])
                signals.append(sig)

        return {
            "symbol": symbol,
            "status": "ok",
            "bar_count": len(result_df),
            "structure": structure,
            "signals": signals,
            "czsc_columns": czsc_cols,
        }
    except Exception as e:
        logger.warning(f"chanlun scan: {symbol} failed: {e}")
        return {"symbol": symbol, "status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@chanlun_blp.route("/analyze", methods=["GET"])
@login_required
def chanlun_analyze():
    """Full CZSC (缠论) analysis for a single symbol.

    Query params:
        symbol    (required) — e.g. '300750', '000001.SZ'
        market    (default 'CNStock')
        timeframe (default '30m')
        limit     (default 300, max 2000)
    """
    symbol = request.args.get("symbol", "").strip()
    market = request.args.get("market", "CNStock").strip()
    timeframe = request.args.get("timeframe", "30m").strip()
    try:
        limit = min(int(request.args.get("limit", 300)), 2000)
    except (ValueError, TypeError):
        limit = 300

    if not symbol:
        return {"code": 0, "msg": "symbol is required", "data": None}, 400

    if not is_czsc_enabled():
        return {
            "code": 0,
            "msg": "czsc library is not installed",
            "data": {"import_error": get_czsc_import_error()},
        }, 400

    try:
        rows = _kline_service.get_kline(
            market=market, symbol=symbol, timeframe=timeframe, limit=limit,
        ) or []
    except Exception as e:
        logger.error(f"chanlun/analyze kline fetch failed: {e}", exc_info=True)
        return {"code": 0, "msg": "kline fetch failed", "data": None}, 502

    if not rows or len(rows) < 10:
        return {"code": 0, "msg": f"Insufficient data: {len(rows)} bars", "data": None}, 400

    try:
        df = _rows_to_dataframe(rows)
        result_df = compute_czsc_features(df, freq=timeframe, symbol=symbol)
    except Exception as e:
        logger.error(f"chanlun/analyze computation failed: {e}", exc_info=True)
        return {"code": 0, "msg": "computation failed", "data": None}, 500

    czsc_columns = [c for c in result_df.columns if c.startswith("czsc_")]
    structure = _extract_structure(result_df)

    # Extract signals
    bs_col = "czsc_bs_type"
    signals: list[dict[str, Any]] = []
    if bs_col in result_df.columns:
        mask = result_df[bs_col].astype(str).str.strip() != ""
        for idx, row in result_df[mask].tail(20).iterrows():
            sig: dict[str, Any] = {
                "bs_type": row[bs_col],
                "index": int(idx) if isinstance(idx, (int, float)) else str(idx),
            }
            if "close" in result_df.columns and pd.notna(row.get("close")):
                sig["price"] = float(row["close"])
            if "czsc_trend" in result_df.columns and pd.notna(row.get("czsc_trend")):
                sig["trend"] = int(row["czsc_trend"])
            signals.append(sig)

    # Latest bar czsc values
    latest: dict[str, Any] = {}
    if len(result_df) > 0:
        last = result_df.iloc[-1]
        for col in czsc_columns:
            val = last[col]
            if isinstance(val, float) and pd.isna(val):
                continue
            if hasattr(val, "item"):
                val = val.item()
            latest[col] = val

    return {
        "code": 1,
        "msg": "success",
        "data": {
            "symbol": symbol,
            "market": market,
            "timeframe": timeframe,
            "bar_count": len(result_df),
            "structure": structure,
            "signals": signals,
            "czsc_columns": czsc_columns,
            "latest": latest,
            **({
                "market_status": {
                    "is_open": is_cn_market_open(),
                    "session": get_cn_market_session(),
                    "next_event": next_cn_market_event(),
                }
            } if market == "CNStock" else {}),
        },
    }


@chanlun_blp.route("/structure", methods=["GET"])
@login_required
def chanlun_structure():
    """ChanLun structural summary for a symbol.

    Query params:
        symbol (required), market (default 'CNStock'), timeframe (default '30m')
    """
    symbol = request.args.get("symbol", "").strip()
    market = request.args.get("market", "CNStock").strip()
    timeframe = request.args.get("timeframe", "30m").strip()
    try:
        limit = min(int(request.args.get("limit", 300)), 2000)
    except (ValueError, TypeError):
        limit = 300

    if not symbol:
        return {"code": 0, "msg": "symbol is required", "data": None}, 400

    if not is_czsc_enabled():
        return {"code": 0, "msg": "czsc library is not installed", "data": None}, 400

    try:
        rows = _kline_service.get_kline(
            market=market, symbol=symbol, timeframe=timeframe, limit=limit,
        ) or []
        if not rows or len(rows) < 10:
            return {"code": 0, "msg": f"Insufficient data: {len(rows)} bars", "data": None}, 400

        df = _rows_to_dataframe(rows)
        result_df = compute_czsc_features(df, freq=timeframe, symbol=symbol)
        structure = _extract_structure(result_df)

        return {"code": 1, "msg": "success", "data": {
            "symbol": symbol, "market": market, "timeframe": timeframe,
            "bar_count": len(result_df), "structure": structure,
            **({
                "market_status": {
                    "is_open": is_cn_market_open(),
                    "session": get_cn_market_session(),
                    "next_event": next_cn_market_event(),
                }
            } if market == "CNStock" else {}),
        }}
    except Exception as e:
        logger.error(f"chanlun/structure failed: {e}", exc_info=True)
        return {"code": 0, "msg": str(e), "data": None}, 500


@chanlun_blp.route("/scan", methods=["POST"])
@login_required
def chanlun_scan():
    """Parallel multi-symbol CZSC signal scan.

    Body JSON:
        symbols  (required) — list of symbol strings, e.g. ['300750', '600519']
        market   (default 'CNStock')
        timeframe (default '30m')
        limit    (default 300)
    """
    data = request.get_json() or {}
    symbols = data.get("symbols") or []
    market = str(data.get("market", "CNStock")).strip()
    timeframe = str(data.get("timeframe", "30m")).strip()
    try:
        limit = min(int(data.get("limit", 300)), 2000)
    except (ValueError, TypeError):
        limit = 300

    if not symbols or not isinstance(symbols, list):
        return {"code": 0, "msg": "symbols must be a non-empty list", "data": None}, 400

    if not is_czsc_enabled():
        return {"code": 0, "msg": "czsc library is not installed", "data": None}, 400

    max_workers = min(len(symbols), 4)
    results: list[dict[str, Any]] = []

    # Try batch fetcher for CNStock market to enrich results with real-time quotes
    _batch_quotes: dict = {}
    if market == "CNStock":
        try:
            _fetcher = get_batch_fetcher()
            if _fetcher.is_available():
                _batch_quotes = _fetcher.get_batch_quotes(symbols)
        except Exception as _e:
            logger.debug(f"chanlun scan: batch fetcher unavailable: {_e}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_analyze_one_symbol, sym, market, timeframe, limit): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            results.append(future.result())

    # Sort results to match input order
    order = {sym: i for i, sym in enumerate(symbols)}
    results.sort(key=lambda r: order.get(r.get("symbol", ""), 999))

    # Merge batch quotes into scan results
    if _batch_quotes:
        for r in results:
            sym = r.get("symbol", "")
            if sym in _batch_quotes:
                r["quote"] = _batch_quotes[sym]

    return {"code": 1, "msg": "success", "data": {
        "market": market,
        "timeframe": timeframe,
        "count": len(results),
        "results": results,
    }}


@chanlun_blp.route("/templates", methods=["GET"])
@login_required
def chanlun_list_templates():
    """List pre-built ChanLun strategy templates."""
    from app.services.chanlun_templates import list_templates
    return {"code": 1, "msg": "success", "data": list_templates()}


@chanlun_blp.route("/templates/<template_id>/apply", methods=["POST"])
@login_required
def chanlun_apply_template(template_id: str):
    """Return template code for frontend usage.

    URL param:
        template_id — one of the template IDs from GET /api/chanlun/templates
    """
    from app.services.chanlun_templates import get_template
    tpl = get_template(template_id)
    if tpl is None:
        return {"code": 0, "msg": f"Template not found: {template_id}", "data": None}, 404
    return {"code": 1, "msg": "success", "data": tpl}
