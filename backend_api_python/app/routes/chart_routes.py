"""
Trade chart visualization API routes.

Provides:
  GET /api/chart/trades   — HTML page: strategy trades on K-line (iframe-friendly)
  GET /api/chart/backtest — HTML page: backtest trades on K-line (uses persisted result)
"""
from __future__ import annotations

import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from flask import Response, jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.utils.auth import login_required
from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)

chart_blp = Blueprint("chart", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_strategy_trades(strategy_id: int, limit: int = 500) -> List[Dict[str, Any]]:
    """Load trades for a strategy from qd_strategy_trades."""
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT id, strategy_id, symbol, type, price, amount, value,
                   commission, commission_ccy, profit, close_reason,
                   matched_entry_price, grid_matched_profit, created_at
            FROM qd_strategy_trades
            WHERE strategy_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (int(strategy_id), limit),
        )
        rows = cur.fetchall() or []
        cur.close()
    trades = []
    for row in rows:
        t = dict(row) if row else {}
        # Normalize datetime for JSON
        created_at = t.get("created_at")
        if isinstance(created_at, datetime):
            dt = created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            t["time"] = dt.strftime("%Y-%m-%d %H:%M")
            t["_ts"] = int(dt.timestamp())
        trades.append(t)
    return trades


def _get_strategy_info(strategy_id: int) -> Optional[Dict[str, Any]]:
    """Load minimal strategy info from DB."""
    try:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT id, strategy_name, symbol, market_type, timeframe,
                       trading_config, exchange_config, status
                FROM qd_strategies_trading
                WHERE id = ?
                LIMIT 1
                """,
                (int(strategy_id),),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return None
        s = dict(row)
        tc = s.get("trading_config") or {}
        if isinstance(tc, str):
            import json
            try:
                tc = json.loads(tc)
            except Exception:
                tc = {}
        ec = s.get("exchange_config") or {}
        if isinstance(ec, str):
            import json
            try:
                ec = json.loads(ec)
            except Exception:
                ec = {}
        return {
            "id": s.get("id"),
            "name": s.get("strategy_name") or f"Strategy #{strategy_id}",
            "symbol": s.get("symbol") or tc.get("symbol") or "",
            "market_type": tc.get("market_type") or s.get("market_type") or "Crypto",
            "timeframe": tc.get("timeframe") or "1D",
            "exchange_id": ec.get("exchange_id") or "",
            "market": tc.get("market") or "Crypto",
        }
    except Exception as e:
        logger.warning(f"_get_strategy_info failed: {e}")
        return None


def _kline_limit_for_timeframe(timeframe: str) -> int:
    """Return appropriate candle limit based on timeframe."""
    tf = (timeframe or "1D").upper()
    if tf in ("1M", "1M"):
        return 5000
    if tf in ("5M",):
        return 3000
    if tf in ("15M", "30M"):
        return 2000
    return 1000


def _fetch_klines(
    market: str,
    symbol: str,
    timeframe: str,
    limit: int = 1000,
    exchange_id: str = "",
    market_type: str = "",
) -> List[Dict[str, Any]]:
    """Fetch K-line data via KlineService."""
    try:
        from app.services.kline import KlineService
        svc = KlineService()
        klines = svc.get_kline(
            market=market or "Crypto",
            symbol=symbol,
            timeframe=timeframe or "1D",
            limit=limit,
            exchange_id=exchange_id or None,
            market_type=market_type or None,
        )
        return klines or []
    except Exception as e:
        logger.warning(f"fetch_klines failed for {market}:{symbol} {timeframe}: {e}")
        return []


def _html_response(html: str) -> Response:
    return Response(html, mimetype="text/html")


# ---------------------------------------------------------------------------
# Route: strategy trades chart
# ---------------------------------------------------------------------------

@chart_blp.route("/chart/trades", methods=["GET"])
@login_required
def get_strategy_trades_chart():
    """
    Render an HTML page showing a strategy's trades on a K-line chart.

    Query params:
        strategyId (required): Strategy ID
        limit (optional): Max trades to display (default 500)
    """
    try:
        strategy_id = int(request.args.get("strategyId") or request.args.get("id") or 0)
        if not strategy_id:
            return jsonify({"code": 0, "msg": "strategyId is required", "data": None}), 400

        limit = int(request.args.get("limit") or 500)
        limit = max(1, min(2000, limit))

        info = _get_strategy_info(strategy_id)
        if not info:
            return jsonify({"code": 0, "msg": "Strategy not found", "data": None}), 404

        trades = _load_strategy_trades(strategy_id, limit=limit)
        if not trades:
            return jsonify({"code": 0, "msg": "No trades found for this strategy", "data": None}), 404

        # Determine K-line fetch params from strategy info
        symbol = info.get("symbol") or ""
        timeframe = info.get("timeframe") or "1D"
        market = info.get("market") or "Crypto"
        exchange_id = info.get("exchange_id") or ""
        market_type = info.get("market_type") or ""

        klines = _fetch_klines(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=_kline_limit_for_timeframe(timeframe),
            exchange_id=exchange_id,
            market_type=market_type,
        )

        from app.services.trade_chart import build_chart_html
        html = build_chart_html(
            klines=klines,
            trades=trades,
            symbol=symbol,
            timeframe=timeframe,
            backend_url=request.host_url.rstrip('/'),
        )
        return _html_response(html)

    except Exception as e:
        logger.error(f"get_strategy_trades_chart failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


# ---------------------------------------------------------------------------
# Route: backtest result chart
# ---------------------------------------------------------------------------

@chart_blp.route("/chart/backtest", methods=["GET", "POST"])
@login_required
def get_backtest_chart():
    """
    Render an HTML page showing backtest trades on a K-line chart.

    Accepts either:
      GET  ?market=Crypto&symbol=BTC/USDT&timeframe=1D&resultId=... (load saved result)
      POST with JSON body containing klines + trades (from backtest result)
    """
    try:
        result_id = None
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            klines = data.get("klines") or data.get("candles") or []
            trades = data.get("trades") or []
            symbol = data.get("symbol") or ""
            timeframe = data.get("timeframe") or ""
        else:
            # GET: load from query params + saved backtest result
            symbol = request.args.get("symbol") or ""
            timeframe = request.args.get("timeframe") or "1D"
            market = request.args.get("market") or "Crypto"
            klines = _fetch_klines(market=market, symbol=symbol, timeframe=timeframe, limit=_kline_limit_for_timeframe(timeframe))
            trades = []
            # If resultId provided, load trades from saved backtest
            result_id = request.args.get("resultId")
            if result_id:
                trades = _load_backtest_trades(int(result_id))

        from app.services.trade_chart import build_chart_html
        html = build_chart_html(
            klines=klines,
            trades=trades,
            symbol=symbol,
            timeframe=timeframe,
            result_id=int(result_id) if result_id else None,
            backend_url=request.host_url.rstrip('/'),
        )
        return _html_response(html)

    except Exception as e:
        logger.error(f"get_backtest_chart failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


def _load_backtest_trades(result_id: int) -> List[Dict[str, Any]]:
    """Load trades from a saved backtest result."""
    try:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT result_json FROM qd_backtest_runs
                WHERE id = ? LIMIT 1
                """,
                (result_id,),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return []
        import json
        result_json = row.get("result_json") if isinstance(row, dict) else row[0]
        if isinstance(result_json, str):
            result_json = json.loads(result_json)
        if isinstance(result_json, dict):
            return result_json.get("trades") or []
        return []
    except Exception as e:
        logger.warning(f"_load_backtest_trades failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Route: chart data API (JSON) — for SPA frontend integration
# ---------------------------------------------------------------------------

@chart_blp.route("/chart/trades/data", methods=["GET"])
@login_required
def get_strategy_trades_chart_data():
    """
    Return chart-ready JSON (candles + trades + summary) for SPA rendering.

    Query params:
        strategyId (required): Strategy ID
        limit (optional): Max trades (default 500)
    """
    try:
        strategy_id = int(request.args.get("strategyId") or request.args.get("id") or 0)
        if not strategy_id:
            return jsonify({"code": 0, "msg": "strategyId is required", "data": None}), 400

        limit = int(request.args.get("limit") or 500)
        limit = max(1, min(2000, limit))

        info = _get_strategy_info(strategy_id)
        if not info:
            return jsonify({"code": 0, "msg": "Strategy not found", "data": None}), 404

        trades = _load_strategy_trades(strategy_id, limit=limit)
        symbol = info.get("symbol") or ""
        timeframe = info.get("timeframe") or "1D"
        market = info.get("market") or "Crypto"
        exchange_id = info.get("exchange_id") or ""
        market_type = info.get("market_type") or ""

        klines = _fetch_klines(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=_kline_limit_for_timeframe(timeframe),
            exchange_id=exchange_id,
            market_type=market_type,
        )

        from app.services.trade_chart import (
            _build_summary,
            _prepare_candles,
            _prepare_markers,
            _prepare_trade_table,
        )
        candles = _prepare_candles(klines)
        markers = _prepare_markers(trades)
        table_rows = _prepare_trade_table(trades)
        summary = _build_summary(trades)

        return jsonify({
            "code": 1,
            "msg": "success",
            "data": {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": candles,
                "markers": markers,
                "trades": table_rows,
                "summary": summary,
            },
        })

    except Exception as e:
        logger.error(f"get_strategy_trades_chart_data failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


# Legacy alias for OpenAPI compat
chart_bp = chart_blp


# ---------------------------------------------------------------------------
# Route: backtest chart data API (JSON) — for dynamic timeframe switching
# ---------------------------------------------------------------------------

@chart_blp.route("/chart/backtest/data", methods=["GET"])
@login_required
def get_backtest_chart_data():
    """
    Return chart-ready JSON (candles + trades + markers + summary) for SPA/iframe rendering.

    Query params:
        market (optional): Market type (default "Crypto")
        symbol (required): Trading pair (e.g., "BTC/USDT")
        timeframe (required): K-line timeframe (e.g., "1m", "5m", "1D")
        resultId (optional): Backtest result ID to load trades from
    """
    try:
        symbol = request.args.get("symbol") or ""
        if not symbol:
            return jsonify({"code": 0, "msg": "symbol is required", "data": None}), 400

        timeframe = request.args.get("timeframe") or "1D"
        market = request.args.get("market") or "Crypto"
        result_id = request.args.get("resultId")

        # Fetch K-line data
        klines = _fetch_klines(market=market, symbol=symbol, timeframe=timeframe, limit=_kline_limit_for_timeframe(timeframe))

        # Load trades from saved backtest if resultId provided
        trades = []
        if result_id:
            trades = _load_backtest_trades(int(result_id))

        from app.services.trade_chart import (
            _build_summary,
            _calculate_bollinger_bands,
            _calculate_rsi,
            _calculate_kdj,
            _prepare_candles,
            _prepare_markers,
            _prepare_trade_table,
        )
        candles = _prepare_candles(klines)
        markers = _prepare_markers(trades)
        table_rows = _prepare_trade_table(trades)
        summary = _build_summary(trades)
        bb_data = _calculate_bollinger_bands(candles)
        rsi_data = _calculate_rsi(candles)
        kdj_data = _calculate_kdj(candles)

        # Strip internal fields from markers for JS
        markers_for_js = []
        for m in markers:
            markers_for_js.append({
                "time": m["time"],
                "position": m["position"],
                "color": m["color"],
                "shape": m["shape"],
                "text": m["text"],
            })

        return jsonify({
            "code": 1,
            "msg": "success",
            "data": {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": candles,
                "markers": markers_for_js,
                "trades": table_rows,
                "summary": summary,
                "bb": bb_data,
                "rsi": rsi_data,
                "kdj": kdj_data,
            },
        })

    except Exception as e:
        logger.error(f"get_backtest_chart_data failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


# ---------------------------------------------------------------------------
# Route: combined review page (metrics + chart + trades)
# ---------------------------------------------------------------------------

@chart_blp.route("/chart/review", methods=["GET"])
@login_required
def get_review_chart_page():
    """Render a combined performance-review + trade-chart HTML page.

    This page shows:
      - Performance KPI cards (from strategy review metrics)
      - K-line chart with trade markers
      - Trade detail table

    Query params:
        strategyId / id  — required strategy DB id
        lookbackDays     — lookback window (default 30)
        limit            — max trades (default 500, max 2000)
    """
    try:
        strategy_id = int(request.args.get("strategyId") or request.args.get("id") or 0)
        if not strategy_id:
            return jsonify({"code": 0, "msg": "strategyId is required", "data": None}), 400

        lookback_days = int(request.args.get("lookbackDays") or 30)
        lookback_days = max(1, min(365, lookback_days))
        limit = int(request.args.get("limit") or 500)
        limit = max(1, min(2000, limit))

        info = _get_strategy_info(strategy_id)
        if not info:
            return jsonify({"code": 0, "msg": "Strategy not found", "data": None}), 404

        # Build review metrics via StrategyReviewService
        from app.services.strategy_review import StrategyReviewService
        review_svc = StrategyReviewService()
        from flask import g
        user_id = int(getattr(g, "user_id", 1))
        report = review_svc.build_report(
            strategy_id=strategy_id,
            user_id=user_id,
            lookback_days=lookback_days,
            include_ai=False,
            language="zh-CN",
        )
        metrics = report.get("metrics") or {}
        strategy_name = (report.get("strategy") or {}).get("name") or info.get("name") or ""

        # Load trades for chart
        trades = _load_strategy_trades(strategy_id, limit=limit)

        # Fetch K-line data
        symbol = info.get("symbol") or ""
        timeframe = info.get("timeframe") or "1D"
        market = info.get("market") or "Crypto"
        exchange_id = info.get("exchange_id") or ""
        market_type = info.get("market_type") or ""

        klines = _fetch_klines(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=_kline_limit_for_timeframe(timeframe),
            exchange_id=exchange_id,
            market_type=market_type,
        )

        from app.services.trade_chart import build_review_page_html
        html = build_review_page_html(
            klines=klines,
            trades=trades,
            metrics=metrics,
            symbol=symbol,
            timeframe=timeframe,
            strategy_name=strategy_name,
            lookback_days=lookback_days,
        )
        return _html_response(html)

    except Exception as e:
        logger.error(f"get_review_chart_page failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
