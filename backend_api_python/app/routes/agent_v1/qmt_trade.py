"""QMT (miniQMT) A-Share Trading — Agent Gateway endpoints.

Provides REST API for A-share trading via the locally running miniQMT client.
When running inside Docker (Linux), automatically proxies to the QMT Bridge
service on the Windows host.

Security:
  - Read endpoints (status/asset/positions/orders/quote): SCOPE_R
  - Trading endpoints (connect/disconnect/place/cancel): SCOPE_T
  - All gated by ALLOW_LOCAL_DESKTOP_BROKERS env
  - Live order placement requires AGENT_LIVE_TRADING_ENABLED=true
"""
from __future__ import annotations

import os
import platform

import requests as _requests
from app.utils.agent_auth import (
    SCOPE_R, SCOPE_T, agent_required, current_user_id,
)
from app.utils.local_brokers import (
    local_desktop_brokers_allowed,
    desktop_broker_cloud_reject_message,
)
from app.utils.logger import get_logger
from flask import request

from . import agent_v1_bp
from ._helpers import envelope, error, get_json_or_400

logger = get_logger(__name__)

# ── Bridge detection ──────────────────────────────────────────────────
# When running on Linux (Docker), xtquant is unavailable. Proxy to the
# QMT Bridge on the Windows host. Bridge URL can be overridden via env.
_IS_LINUX = platform.system() != "Windows"
_BRIDGE_URL = os.getenv(
    "QMT_BRIDGE_URL",
    "http://host.docker.internal:5002" if _IS_LINUX else "http://127.0.0.1:5002",
)


def _use_bridge() -> bool:
    """True when xtquant cannot run locally (Linux / Docker)."""
    return _IS_LINUX


def _bridge_get(path, params=None, timeout=10):
    r = _requests.get(f"{_BRIDGE_URL}{path}", params=params, timeout=timeout)
    return r.json()


def _bridge_post(path, json_body=None, timeout=15):
    r = _requests.post(f"{_BRIDGE_URL}{path}", json=json_body or {}, timeout=timeout)
    return r.json()


def _bridge_delete(path, timeout=10):
    r = _requests.delete(f"{_BRIDGE_URL}{path}", timeout=timeout)
    return r.json()


# Place-order may block while bridge polls for fill (~12s) + IPC overhead.
_ORDER_BRIDGE_TIMEOUT = 45.0


def _get_qmt_config():
    """Build QMTConfig from environment variables."""
    from app.services.qmt_trading import QMTConfig
    return QMTConfig(
        qmt_path=os.getenv("QMT_PATH", ""),
        qmt_account_id=os.getenv("QMT_ACCOUNT_ID", ""),
        qmt_session_id=int(os.getenv("QMT_SESSION_ID", "123456")),
        qmt_lib_path=os.getenv("QMT_LIB_PATH", ""),
        strategy_name=os.getenv("QMT_STRATEGY_NAME", "ChanQuant"),
    )


def _get_client():
    """Get global QMT client singleton (only works on Windows)."""
    from app.services.qmt_trading import get_qmt_client
    config = _get_qmt_config()
    return get_qmt_client(config)


def _live_trading_enabled() -> bool:
    return os.getenv("AGENT_LIVE_TRADING_ENABLED", "false").lower() in ("1", "true", "yes")


# ==================== Read Endpoints (SCOPE_R) ====================

@agent_v1_bp.route("/qmt/status", methods=["GET"])
@agent_required(SCOPE_R)
def qmt_status():
    """QMT connection status and account summary."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    if _use_bridge():
        try:
            result = _bridge_get("/qmt/status")
            data = result.get("data", {})
            data["bridge"] = True
            data["bridge_url"] = _BRIDGE_URL
            data["live_trading_enabled"] = _live_trading_enabled()
            return result
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    client = _get_client()
    status = client.get_connection_status()
    status["live_trading_enabled"] = _live_trading_enabled()
    return envelope(status)


@agent_v1_bp.route("/qmt/asset", methods=["GET"])
@agent_required(SCOPE_R)
def qmt_asset():
    """Query account asset (cash, market value, total)."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    if _use_bridge():
        try:
            return _bridge_get("/qmt/asset")
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    client = _get_client()
    result = client.get_account_info()
    if not result.get("success"):
        return error(502, "Failed to query QMT asset", details=result.get("error", ""), http=502)
    return envelope(result)


@agent_v1_bp.route("/qmt/positions", methods=["GET"])
@agent_required(SCOPE_R)
def qmt_positions():
    """Query stock positions. Optional ?symbol= to filter."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    if _use_bridge():
        try:
            params = {}
            sym = request.args.get("symbol", "").strip()
            if sym:
                params["symbol"] = sym
            return _bridge_get("/qmt/positions", params=params)
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    symbol = request.args.get("symbol", "").strip() or None
    client = _get_client()
    positions = client.get_positions(symbol=symbol)
    return envelope({"positions": positions, "count": len(positions)})


@agent_v1_bp.route("/qmt/orders", methods=["GET"])
@agent_required(SCOPE_R)
def qmt_orders():
    """Query today's orders. Optional ?symbol= to filter."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    if _use_bridge():
        try:
            params = {}
            sym = request.args.get("symbol", "").strip()
            if sym:
                params["symbol"] = sym
            return _bridge_get("/qmt/orders", params=params)
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    symbol = request.args.get("symbol", "").strip() or None
    client = _get_client()
    orders = client.get_orders(symbol=symbol)
    return envelope({"orders": orders, "count": len(orders)})


@agent_v1_bp.route("/qmt/quote", methods=["GET"])
@agent_required(SCOPE_R)
def qmt_quote():
    """Real-time quote for an A-share. Required ?symbol= parameter."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return error(400, "symbol parameter is required (e.g. ?symbol=600036)")

    if _use_bridge():
        try:
            return _bridge_get("/qmt/quote", params={"symbol": symbol})
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    client = _get_client()
    result = client.get_quote(symbol)
    if not result.get("success"):
        return error(502, f"Failed to get quote for {symbol}",
                     details=result.get("error", ""), http=502)
    return envelope(result)


# ==================== Trading Endpoints (SCOPE_T) ====================

@agent_v1_bp.route("/qmt/connect", methods=["POST"])
@agent_required(SCOPE_T)
def qmt_connect():
    """Connect to the locally running miniQMT terminal."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    if _use_bridge():
        try:
            return _bridge_post("/qmt/connect")
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    client = _get_client()
    if client.connected:
        return envelope({"connected": True, "message": "Already connected"})

    ok = client.connect()
    if not ok:
        return error(502, "Failed to connect to miniQMT. "
                     "Ensure the terminal is running and logged in.",
                     http=502)
    return envelope({"connected": True, "message": "Connected successfully"})


@agent_v1_bp.route("/qmt/disconnect", methods=["POST"])
@agent_required(SCOPE_T)
def qmt_disconnect():
    """Disconnect from miniQMT."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    if _use_bridge():
        try:
            return _bridge_post("/qmt/disconnect")
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    client = _get_client()
    client.disconnect()
    return envelope({"connected": False, "message": "Disconnected"})


@agent_v1_bp.route("/qmt/orders", methods=["POST"])
@agent_required(SCOPE_T)
def qmt_place_order():
    """Place an A-share order (market or limit).

    Routes to QMT Bridge when running in Docker, or direct xtquant on Windows.
    Live execution requires AGENT_LIVE_TRADING_ENABLED=true.
    """
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    body, err = get_json_or_400()
    if err:
        return err

    symbol = (body.get("symbol") or "").strip()
    side = (body.get("side") or "").strip().lower()
    order_type = (body.get("order_type") or body.get("orderType") or "market").strip().lower()
    volume = body.get("volume") or body.get("qty") or body.get("quantity") or 0
    price = body.get("price") or body.get("limit_price") or body.get("limitPrice")
    comment = (body.get("comment") or body.get("remark") or "ChanQuant").strip()

    if not symbol:
        return error(400, "symbol is required (e.g. '600036' or '600036.SH')")
    if side not in ("buy", "sell"):
        return error(400, "side must be 'buy' or 'sell'")
    try:
        volume_f = float(volume)
        if volume_f <= 0:
            raise ValueError
    except Exception:
        return error(400, "volume must be a positive integer (shares)")

    if order_type == "limit":
        try:
            price_f = float(price or 0)
            if price_f <= 0:
                raise ValueError
        except Exception:
            return error(400, "price is required for limit orders")

    # Live trading gate
    if not _live_trading_enabled():
        from app.services.qmt_trading.symbols import normalize_symbol
        import uuid
        paper_order = {
            "order_uid": uuid.uuid4().hex,
            "symbol": normalize_symbol(symbol),
            "side": side,
            "order_type": order_type,
            "volume": int(volume_f),
            "price": float(price or 0) if order_type == "limit" else 0.0,
            "status": "paper",
            "paper": True,
            "message": "Live trading disabled. Set AGENT_LIVE_TRADING_ENABLED=true to enable.",
        }
        return envelope(paper_order, message="paper-fill")

    # Proxy to bridge or direct xtquant
    order_body = {
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "volume": int(volume_f),
        "comment": comment,
    }
    if order_type == "limit":
        order_body["price"] = float(price)

    if _use_bridge():
        try:
            return _bridge_post("/qmt/orders", json_body=order_body, timeout=_ORDER_BRIDGE_TIMEOUT)
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    # Direct xtquant (Windows only)
    client = _get_client()
    if not client.connected:
        if not client.connect():
            return error(502, "Cannot connect to miniQMT", http=502)

    if order_type == "limit":
        result = client.place_limit_order(
            symbol=symbol, side=side,
            volume=int(volume_f), price=float(price),
            comment=comment,
        )
    else:
        result = client.place_market_order(
            symbol=symbol, side=side,
            volume=int(volume_f),
            comment=comment,
        )

    if not result.success:
        return error(500, "QMT order failed", details=result.message, http=500)

    return envelope({
        "order_id": result.order_id,
        "filled": result.filled,
        "price": result.price,
        "status": result.status,
        "message": result.message,
        "paper": False,
    }, message="live-order")


@agent_v1_bp.route("/qmt/orders/<int:order_id>", methods=["DELETE"])
@agent_required(SCOPE_T)
def qmt_cancel_order(order_id: int):
    """Cancel an A-share order by order_id."""
    if not local_desktop_brokers_allowed():
        return error(403, desktop_broker_cloud_reject_message(), http=403)

    if _use_bridge():
        try:
            return _bridge_delete(f"/qmt/orders/{order_id}")
        except Exception as e:
            return error(502, "QMT Bridge unreachable", details=str(e), http=502)

    if not _live_trading_enabled():
        return envelope({
            "order_id": order_id,
            "cancelled": False,
            "paper": True,
            "message": "Live trading disabled. No real order to cancel.",
        })

    client = _get_client()
    ok = client.cancel_order(order_id)
    if not ok:
        return error(500, f"Failed to cancel order {order_id}", http=500)
    return envelope({
        "order_id": order_id,
        "cancelled": True,
        "message": "Cancel request accepted",
    })
