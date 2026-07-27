"""Agent v1 — trade chart HTML endpoint.

GET /api/agent/v1/chart/trades  — renders strategy trades on K-line as HTML.

This endpoint is intentionally auth-light: it returns a self-contained HTML
page designed to be loaded in an iframe or browser tab.  Token-based auth is
still checked via the standard agent_v1 token header, but scope is not
enforced (chart is a read-only visualisation aid).
"""
from __future__ import annotations

import traceback

from flask import Response, request

from app.utils.logger import get_logger

from . import agent_v1_bp
from ._helpers import error

logger = get_logger(__name__)


def _html_response(html: str) -> Response:
    return Response(html, mimetype="text/html")


@agent_v1_bp.route("/chart/trades", methods=["GET"])
def chart_trades():
    """Render an HTML K-line chart for a strategy's trade history.

    Query params:
        strategyId / id  — required strategy DB id
        limit            — max trades (default 500, max 2000)
    """
    strategy_id = int(request.args.get("strategyId") or request.args.get("id") or 0)
    if not strategy_id:
        return error(400, "strategyId query parameter is required")

    limit = int(request.args.get("limit") or 500)
    limit = max(1, min(2000, limit))

    try:
        from app.routes.chart_routes import (
            _fetch_klines,
            _get_strategy_info,
            _load_strategy_trades,
        )
        from app.services.trade_chart import build_chart_html

        info = _get_strategy_info(strategy_id)
        if not info:
            return error(404, "Strategy not found")

        trades = _load_strategy_trades(strategy_id, limit=limit)
        if not trades:
            return error(404, "No trades found for this strategy")

        symbol = info.get("symbol") or ""
        timeframe = info.get("timeframe") or "1D"
        market = info.get("market") or "Crypto"
        exchange_id = info.get("exchange_id") or ""
        market_type = info.get("market_type") or ""

        klines = _fetch_klines(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=1000,
            exchange_id=exchange_id,
            market_type=market_type,
        )

        html = build_chart_html(
            klines=klines,
            trades=trades,
            symbol=symbol,
            timeframe=timeframe,
        )
        return _html_response(html)

    except Exception as e:
        logger.error(f"agent_v1 chart/trades failed: {e}")
        logger.error(traceback.format_exc())
        return error(500, str(e))
