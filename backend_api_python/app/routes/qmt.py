"""
QMT (miniQMT) human-facing API routes.

Mirrors ``routes/ibkr.py`` / ``routes/alpaca.py`` so the BrokerPanel SPA can
talk to A-share trading the same way it talks to IBKR/Alpaca.

In Docker (Linux) the backend has no xtquant IPC — every call proxies to the
Windows-host QMT Bridge (``QMT_BRIDGE_URL``, default host.docker.internal:5002).
"""
from __future__ import annotations

import os
import platform

import requests as _requests
from flask import jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.utils.auth import login_required
from app.utils.local_brokers import (
    desktop_broker_cloud_reject_message,
    local_desktop_brokers_allowed,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

qmt_blp = Blueprint("qmt", __name__)

_IS_LINUX = platform.system() != "Windows"
_BRIDGE_URL = os.getenv(
    "QMT_BRIDGE_URL",
    "http://host.docker.internal:5002" if _IS_LINUX else "http://127.0.0.1:5002",
)


def _deny_if_cloud():
    if not local_desktop_brokers_allowed():
        return jsonify({"success": False, "error": desktop_broker_cloud_reject_message()}), 403
    return None


def _bridge_get(path: str, params=None):
    r = _requests.get(f"{_BRIDGE_URL}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _bridge_post(path: str, json_body=None):
    r = _requests.post(f"{_BRIDGE_URL}{path}", json=json_body or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _bridge_delete(path: str):
    r = _requests.delete(f"{_BRIDGE_URL}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


def _unwrap_bridge(payload: dict) -> dict:
    """Normalize bridge ``{code,data,message}`` into IBKR-style ``{success,data}``."""
    if not isinstance(payload, dict):
        return {"success": False, "error": "invalid bridge response"}
    code = payload.get("code")
    if code in (0, "0", None) and "data" in payload:
        # bridge success uses code=0
        return {"success": True, "data": payload.get("data") or {}, "message": payload.get("message") or "ok"}
    if payload.get("success") is True:
        return payload
    err = payload.get("message") or payload.get("error") or payload.get("msg") or "QMT bridge error"
    return {"success": False, "error": err, "data": payload.get("data")}


def _placeholder_status():
    return {
        "connected": False,
        "account_id": os.getenv("QMT_ACCOUNT_ID", ""),
        "qmt_path": os.getenv("QMT_PATH", ""),
        "session_id": int(os.getenv("QMT_SESSION_ID", "0") or 0),
        "bridge": _IS_LINUX,
        "bridge_url": _BRIDGE_URL if _IS_LINUX else None,
    }


@qmt_blp.route("/status", methods=["GET"])
@login_required
def get_status():
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        raw = _bridge_get("/qmt/status")
        out = _unwrap_bridge(raw)
        if out.get("success"):
            data = dict(out.get("data") or {})
            data["bridge"] = _IS_LINUX
            data["bridge_url"] = _BRIDGE_URL if _IS_LINUX else None
            return jsonify({"success": True, "data": data})
        # Bridge up but not connected — still return a stable shape
        return jsonify({"success": True, "data": {**_placeholder_status(), **(out.get("data") or {})}})
    except Exception as e:
        logger.warning("QMT status via bridge failed: %s", e)
        return jsonify({"success": True, "data": {**_placeholder_status(), "error": str(e)}})


@qmt_blp.route("/connect", methods=["POST"])
@login_required
def connect():
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        # Body is ignored — bridge uses host env (QMT_PATH / ACCOUNT / SESSION).
        raw = _bridge_post("/qmt/connect")
        out = _unwrap_bridge(raw)
        if out.get("success"):
            return jsonify({
                "success": True,
                "message": out.get("message") or "Connected successfully",
                "data": out.get("data") or {"connected": True},
            })
        return jsonify({"success": False, "error": out.get("error") or "Connection failed"}), 400
    except Exception as e:
        logger.error("QMT connect failed: %s", e)
        return jsonify({"success": False, "error": f"QMT Bridge unreachable: {e}"}), 502


@qmt_blp.route("/disconnect", methods=["POST"])
@login_required
def disconnect():
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        raw = _bridge_post("/qmt/disconnect")
        out = _unwrap_bridge(raw)
        return jsonify({
            "success": True,
            "message": out.get("message") or "Disconnected",
            "data": out.get("data") or {"connected": False},
        })
    except Exception as e:
        logger.error("QMT disconnect failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 502


@qmt_blp.route("/account", methods=["GET"])
@login_required
def get_account():
    """Map bridge /qmt/asset → BrokerPanel account KPI fields."""
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        raw = _bridge_get("/qmt/asset")
        out = _unwrap_bridge(raw)
        if not out.get("success"):
            return jsonify({"success": False, "error": out.get("error") or "Not connected"}), 400
        asset = out.get("data") or {}
        # Flatten nested success payloads from bridge
        if isinstance(asset.get("success"), bool) and "cash" not in asset:
            asset = {k: v for k, v in asset.items() if k != "success"}
        data = {
            "account_id": asset.get("account_id") or os.getenv("QMT_ACCOUNT_ID", ""),
            "cash": float(asset.get("cash") or 0),
            "frozen_cash": float(asset.get("frozen_cash") or 0),
            "market_value": float(asset.get("market_value") or 0),
            "total_asset": float(asset.get("total_asset") or 0),
            # Aliases used by BrokerAccountCard KPI branches
            "equity": float(asset.get("total_asset") or 0),
            "net_liquidation": float(asset.get("total_asset") or 0),
            "total_cash_value": float(asset.get("cash") or 0),
            "currency": "CNY",
        }
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error("QMT account failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 502


@qmt_blp.route("/positions", methods=["GET"])
@login_required
def get_positions():
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        params = {}
        if request.args.get("symbol"):
            params["symbol"] = request.args.get("symbol")
        raw = _bridge_get("/qmt/positions", params=params or None)
        out = _unwrap_bridge(raw)
        if not out.get("success"):
            return jsonify({"success": False, "error": out.get("error") or "Not connected"}), 400
        data = out.get("data") or {}
        positions = data.get("positions") if isinstance(data, dict) else data
        if not isinstance(positions, list):
            positions = []
        return jsonify({"success": True, "data": positions})
    except Exception as e:
        logger.error("QMT positions failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 502


@qmt_blp.route("/orders", methods=["GET"])
@login_required
def get_orders():
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        params = {}
        if request.args.get("symbol"):
            params["symbol"] = request.args.get("symbol")
        raw = _bridge_get("/qmt/orders", params=params or None)
        out = _unwrap_bridge(raw)
        if not out.get("success"):
            return jsonify({"success": False, "error": out.get("error") or "Not connected"}), 400
        data = out.get("data") or {}
        orders = data.get("orders") if isinstance(data, dict) else data
        if not isinstance(orders, list):
            orders = []
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        logger.error("QMT orders failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 502


@qmt_blp.route("/order", methods=["POST"])
@login_required
def place_order():
    """Place order via bridge. UI must preview + user confirm before calling."""
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        data = request.get_json() or {}
        symbol = (data.get("symbol") or "").strip()
        side = (data.get("side") or "").strip().lower()
        quantity = data.get("quantity") or data.get("volume") or data.get("amount")
        if not symbol:
            return jsonify({"success": False, "error": "Missing symbol"}), 400
        if side not in ("buy", "sell"):
            return jsonify({"success": False, "error": "side must be buy or sell"}), 400
        try:
            volume = int(float(quantity))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "quantity must be a number"}), 400
        if volume < 100:
            return jsonify({
                "success": False,
                "error": f"qmt_volume_below_lot:{volume} (A-share board lot is 100 shares)",
            }), 400

        order_type = (data.get("orderType") or data.get("order_type") or "market").lower()
        body = {
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "order_type": "limit" if order_type == "limit" else "market",
        }
        if body["order_type"] == "limit":
            price = data.get("price")
            if price is None or float(price) <= 0:
                return jsonify({"success": False, "error": "Limit order requires price"}), 400
            body["price"] = float(price)

        raw = _bridge_post("/qmt/orders", json_body=body)
        out = _unwrap_bridge(raw)
        if out.get("success"):
            d = out.get("data") or {}
            return jsonify({
                "success": True,
                "message": out.get("message") or "Order submitted",
                "data": {
                    "orderId": d.get("order_id") or d.get("orderId"),
                    "filled": d.get("traded_volume") or d.get("filled") or 0,
                    "avgPrice": d.get("traded_price") or d.get("avgPrice") or d.get("price"),
                    "status": d.get("order_status") or d.get("status"),
                    "raw": d,
                },
            })
        return jsonify({"success": False, "error": out.get("error") or "Order failed"}), 400
    except Exception as e:
        logger.error("QMT place order failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 502


@qmt_blp.route("/order/<int:order_id>", methods=["DELETE"])
@login_required
def cancel_order(order_id: int):
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        raw = _bridge_delete(f"/qmt/orders/{order_id}")
        out = _unwrap_bridge(raw)
        if out.get("success"):
            return jsonify({"success": True, "message": f"Order {order_id} cancelled"})
        return jsonify({"success": False, "error": out.get("error") or "Cancel failed"}), 400
    except Exception as e:
        logger.error("QMT cancel failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 502


@qmt_blp.route("/quote", methods=["GET"])
@login_required
def get_quote():
    denied = _deny_if_cloud()
    if denied is not None:
        return denied
    try:
        symbol = request.args.get("symbol")
        if not symbol:
            return jsonify({"success": False, "error": "Missing symbol"}), 400
        raw = _bridge_get("/qmt/quote", params={"symbol": symbol})
        out = _unwrap_bridge(raw)
        if not out.get("success"):
            return jsonify({"success": False, "error": out.get("error") or "No quote"}), 400
        return jsonify({"success": True, "data": out.get("data") or {}})
    except Exception as e:
        logger.error("QMT quote failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 502


# openapi-compat: legacy import name
qmt_bp = qmt_blp
