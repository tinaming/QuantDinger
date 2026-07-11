"""
CoinOS Skills API routes — crypto market data, trading, whale analytics,
Freqtrade strategy management, on-chain DEX, and account management.

All endpoints proxy to the ``coinos-skills`` Node.js CLI scripts and return
the unified envelope ``{ ok, data, error, meta }``.

Mount point: ``/api/coinos``
"""
from __future__ import annotations

import logging
import re

from flask import jsonify, request
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.services.coinos.runner import CoinOSError, list_skills, run_skill
from app.utils.auth import login_required

logger = logging.getLogger(__name__)

# NOTE: url_prefix is set by register.py, NOT here (avoids double-prefix bug)
coinos_blp = Blueprint(
    "coinos", __name__,
    description="CoinOS Skills — crypto market data, trading, whale analytics, Freqtrade, on-chain DEX",
)


# ---------------------------------------------------------------------------
# Shared schemas (for OpenAPI documentation only)
# ---------------------------------------------------------------------------

class CoinOSSuccessSchema(Schema):
    """Success envelope returned by all CoinOS endpoints."""
    ok = fields.Boolean(metadata={"description": "true on success"})
    data = fields.Raw(allow_none=True, metadata={"description": "Response payload from the script"})
    error = fields.Raw(allow_none=True)
    meta = fields.Raw(allow_none=True)


class CoinOSErrorBodySchema(Schema):
    """Error envelope returned when a CoinOS script fails."""
    ok = fields.Boolean(metadata={"example": False})
    error = fields.Dict(metadata={"description": "Error details with code and message"})


class CoinOSSkillInfoSchema(Schema):
    """Metadata about a CoinOS skill."""
    name = fields.String()
    available = fields.Boolean()
    scripts = fields.List(fields.String())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_TIMEOUT = 600  # hard cap: 10 minutes
_ACTION_RE = re.compile(r'^[a-zA-Z0-9_\-./]+$')
_GROUP_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _validate_action(action: str) -> str:
    """Reject path traversal and shell metacharacters in action."""
    if not action or len(action) > 200 or ".." in action or "\0" in action:
        raise CoinOSError("Invalid action parameter", skill="", script="", action=action, code="INVALID_ACTION")
    if not _ACTION_RE.match(action):
        raise CoinOSError("Action contains illegal characters", skill="", script="", action=action, code="INVALID_ACTION")
    return action


def _validate_timeout(raw) -> int | None:
    """Validate and clamp user-supplied timeout."""
    if raw is None:
        return None
    if not isinstance(raw, (int, float)) or raw <= 0:
        return None
    return min(int(raw), _MAX_TIMEOUT)


def _run(skill: str, script: str, action: str, params: dict | None = None, timeout: int | None = None):
    """Execute a skill script and return JSON response."""
    try:
        action = _validate_action(action)
        timeout = _validate_timeout(timeout)
        result = run_skill(skill, script, action, params=params, timeout=timeout)
        return jsonify(result), 200
    except CoinOSError as exc:
        return jsonify({
            "ok": False,
            "error": {"code": exc.code, "message": str(exc)},
        }), 400
    except Exception as exc:
        logger.exception("Unexpected error in CoinOS %s/%s/%s", skill, script, action)
        return jsonify({
            "ok": False,
            "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
        }), 500


# ---------------------------------------------------------------------------
# Meta endpoints
# ---------------------------------------------------------------------------

@coinos_blp.route("/skills", methods=["GET"])
@coinos_blp.doc(
    summary="List available CoinOS skills",
    description="Returns metadata about all registered CoinOS skills and their availability.",
    tags=["CoinOS"],
)
@login_required
def get_skills():
    """List all CoinOS skills and their status."""
    return jsonify(list_skills())


# ---------------------------------------------------------------------------
# AiCoin Market Data (aicoin-market skill, 183 endpoints)
# ---------------------------------------------------------------------------

@coinos_blp.route("/market/<path:action>", methods=["GET", "POST"])
@coinos_blp.doc(
    summary="AiCoin market data proxy",
    description=(
        "Proxy to all 183 AiCoin Open API v3 endpoints. "
        "GET passes query params; POST sends JSON body. "
        "Common endpoints: `market/ticker`, `coins/tickers`, `market/klines`, "
        "`derivatives/funding-rates`, `content/newsflashes`, `signals/alerts`, etc."
    ),
    tags=["CoinOS-Market"],
)
@login_required
def market_proxy(action: str):
    """Proxy to AiCoin market data endpoints."""
    if request.method == "POST":
        params = request.get_json(silent=True) or {}
    else:
        params = dict(request.args)
    return _run("aicoin-market", "aicoin", action, params=params)


@coinos_blp.route("/market-catalog", methods=["GET"])
@coinos_blp.doc(
    summary="AiCoin API catalog",
    description="List all available AiCoin v3 API endpoints with parameters.",
    tags=["CoinOS-Market"],
)
@login_required
def market_catalog():
    """Return the full AiCoin v3 API catalog."""
    group = request.args.get("group", "")
    if group and not _GROUP_RE.match(group):
        return jsonify({"ok": False, "error": {"code": "INVALID_GROUP", "message": "group must be alphanumeric with - or _"}}), 400
    action = f"catalog {group}".strip() if group else "catalog"
    return _run("aicoin-market", "aicoin", action)


@coinos_blp.route("/market-key-info", methods=["GET"])
@coinos_blp.doc(
    summary="AiCoin API key info",
    description="Check current AiCoin API key tier and permissions.",
    tags=["CoinOS-Market"],
)
@login_required
def market_key_info():
    """Return AiCoin API key info."""
    return _run("aicoin-market", "aicoin", "key")


# ---------------------------------------------------------------------------
# Hyperliquid Whale Analytics (aicoin-hyperliquid skill)
# ---------------------------------------------------------------------------

@coinos_blp.route("/hyperliquid/<path:action>", methods=["GET", "POST"])
@coinos_blp.doc(
    summary="Hyperliquid whale analytics",
    description=(
        "Hyperliquid on-chain perpetuals analytics: whale positions, liquidations, "
        "open interest, trader statistics, smart money tracking. "
        "Endpoints: `hyperliquid/tickers`, `hyperliquid/whales/open-positions`, "
        "`hyperliquid/liquidations/history`, `hyperliquid/smart-money/find`, etc."
    ),
    tags=["CoinOS-Hyperliquid"],
)
@login_required
def hyperliquid_proxy(action: str):
    """Proxy to Hyperliquid analytics endpoints."""
    if request.method == "POST":
        params = request.get_json(silent=True) or {}
    else:
        params = dict(request.args)
    if not action.startswith("hyperliquid/"):
        action = f"hyperliquid/{action}"
    return _run("aicoin-hyperliquid", "aicoin", action, params=params)


# ---------------------------------------------------------------------------
# CEX Trading (aicoin-trading skill)
# ---------------------------------------------------------------------------

@coinos_blp.route("/trading/<action>", methods=["POST"])
@coinos_blp.doc(
    summary="CEX trading operations",
    description=(
        "Execute trades on Binance, OKX, Bybit, Bitget, Gate, HTX, Pionex, Hyperliquid. "
        "Actions: `create_order`, `close_position`, `set_stop`, `cancel_order`, "
        "`positions`, `open_orders`, `balance`, `markets`, `set_leverage`, "
        "`set_trading_params`, `save_key`. "
        "Two-step confirmation required for orders."
    ),
    tags=["CoinOS-Trading"],
)
@login_required
def trading_action(action: str):
    """Execute a trading action via CCXT."""
    body = request.get_json(silent=True) or {}
    timeout = body.pop("_timeout", None)
    return _run("aicoin-trading", "exchange", action, params=body or None, timeout=timeout)


@coinos_blp.route("/trading/auto/<action>", methods=["POST"])
@coinos_blp.doc(
    summary="Auto trading strategies",
    description="Automated trading strategy execution. Actions vary by script.",
    tags=["CoinOS-Trading"],
)
@login_required
def trading_auto(action: str):
    """Run auto-trade actions."""
    body = request.get_json(silent=True) or {}
    return _run("aicoin-trading", "auto-trade", action, params=body or None)


@coinos_blp.route("/trading/register/<exchange>", methods=["POST"])
@coinos_blp.doc(
    summary="Exchange registration (referral)",
    description="Get AiCoin referral link for exchange registration.",
    tags=["CoinOS-Trading"],
)
@login_required
def trading_register(exchange: str):
    """Get exchange registration referral link."""
    return _run("aicoin-trading", "register", exchange)


# ---------------------------------------------------------------------------
# Freqtrade Strategy Management (aicoin-freqtrade skill)
# ---------------------------------------------------------------------------

@coinos_blp.route("/freqtrade/deploy/<action>", methods=["POST"])
@coinos_blp.doc(
    summary="Freqtrade strategy deployment",
    description=(
        "Create, backtest, hyperopt, and deploy Freqtrade strategies. "
        "Actions: `check`, `deploy`, `create_strategy`, `backtest`, `hyperopt`, "
        "`download_data`, `strategy_list`, `start`, `stop`, `status`, `logs`."
    ),
    tags=["CoinOS-Freqtrade"],
)
@login_required
def freqtrade_deploy(action: str):
    """Freqtrade deployment and backtesting."""
    body = request.get_json(silent=True) or {}
    timeout = body.pop("_timeout", None)
    return _run("aicoin-freqtrade", "ft-deploy", action, params=body or None, timeout=timeout)


@coinos_blp.route("/freqtrade/control/<action>", methods=["POST"])
@coinos_blp.doc(
    summary="Freqtrade live bot control",
    description=(
        "Control a running Freqtrade bot: query profit, trades, balance, "
        "switch strategy/pairs, force enter/exit, reload config. "
        "Actions: `daemon_info`, `profit`, `trades_open`, `trades_history`, "
        "`balance`, `profit_per_pair`, `daily`, `weekly`, `monthly`, "
        "`force_enter`, `force_exit`, `set_strategy`, `set_pairs`, "
        "`set_dry_run`, `restart`, `reload`, `start`, `stop`, `logs`."
    ),
    tags=["CoinOS-Freqtrade"],
)
@login_required
def freqtrade_control(action: str):
    """Freqtrade live bot control."""
    body = request.get_json(silent=True) or {}
    return _run("aicoin-freqtrade", "ft", action, params=body or None)


@coinos_blp.route("/freqtrade/dev/<action>", methods=["POST"])
@coinos_blp.doc(
    summary="Freqtrade development tools",
    description="Strategy debugging: candles, whitelist, blacklist, strategy details.",
    tags=["CoinOS-Freqtrade"],
)
@login_required
def freqtrade_dev(action: str):
    """Freqtrade dev/debug tools."""
    body = request.get_json(silent=True) or {}
    return _run("aicoin-freqtrade", "ft-dev", action, params=body or None)


# ---------------------------------------------------------------------------
# Exchange Account Management (aicoin-account skill)
# ---------------------------------------------------------------------------

@coinos_blp.route("/account/<action>", methods=["POST"])
@coinos_blp.doc(
    summary="Exchange account management",
    description=(
        "Query balances, positions, order history, manage API keys. "
        "Actions: `balance`, `positions`, `open_orders`, `closed_orders`, "
        "`my_trades`, `transfer`, `exchanges`."
    ),
    tags=["CoinOS-Account"],
)
@login_required
def account_action(action: str):
    """Exchange account operations."""
    body = request.get_json(silent=True) or {}
    return _run("aicoin-account", "exchange", action, params=body or None)


@coinos_blp.route("/account/key-info", methods=["GET"])
@coinos_blp.doc(
    summary="API key info",
    description="Check configured exchange API key status.",
    tags=["CoinOS-Account"],
)
@login_required
def account_key_info():
    """Get API key info."""
    return _run("aicoin-account", "api-key-info", "")


@coinos_blp.route("/account/tier", methods=["GET"])
@coinos_blp.doc(
    summary="AiCoin data tier check",
    description="Check current AiCoin API tier and available features.",
    tags=["CoinOS-Account"],
)
@login_required
def account_tier():
    """Check AiCoin data tier."""
    action = "verify" if request.args.get("verify") else ""
    return _run("aicoin-account", "check-tier", action)


@coinos_blp.route("/account/register/<exchange>", methods=["POST"])
@coinos_blp.doc(
    summary="Exchange registration referral",
    description="Get AiCoin referral link for exchange registration with kickback.",
    tags=["CoinOS-Account"],
)
@login_required
def account_register(exchange: str):
    """Get exchange registration link."""
    return _run("aicoin-account", "register", exchange)


# ---------------------------------------------------------------------------
# On-Chain DEX (aicoin-onchain skill, OKX Web3)
# ---------------------------------------------------------------------------

@coinos_blp.route("/onchain/<script>/<action>", methods=["POST"])
@coinos_blp.doc(
    summary="On-chain DEX operations",
    description=(
        "OKX Web3 DEX API: token swap, wallet portfolio, gas estimation, "
        "transaction broadcasting. Scripts: `swap`, `portfolio`, `market`, "
        "`token`, `trade`, `gateway`."
    ),
    tags=["CoinOS-Onchain"],
)
@login_required
def onchain_action(script: str, action: str):
    """On-chain DEX operations via OKX Web3."""
    body = request.get_json(silent=True) or {}
    return _run("aicoin-onchain", script, action, params=body or None)
