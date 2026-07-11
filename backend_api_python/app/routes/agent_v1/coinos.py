"""CoinOS Skills proxy — Agent Gateway surface.

Exposes CoinOS Node.js skill scripts through the Agent Gateway so AI agents
(using scoped tokens) can call crypto market data, trading, whale analytics,
Freqtrade, on-chain DEX, and account management.

Scope mapping:
  R (Read)    — market data, hyperliquid, skills list, account info, key-info, tier
  T (Trading) — CEX trading, freqtrade deploy/control, onchain DEX, account mutations

The service layer (``app.services.coinos.runner``) is shared with the
human-facing ``/api/coinos`` blueprint — same Node.js scripts, same envelope.
"""
from __future__ import annotations

import re

from flask import request

from app.services.coinos.runner import CoinOSError, list_skills, run_skill
from app.utils.agent_auth import SCOPE_R, SCOPE_T, agent_required
from app.utils.logger import get_logger

from . import agent_v1_bp
from ._helpers import envelope, error

logger = get_logger(__name__)

# Shared input-validation helpers (same rules as the human route).
_MAX_TIMEOUT = 600
_ACTION_RE = re.compile(r'^[a-zA-Z0-9_\-./]+$')
_GROUP_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _validate_action(action: str) -> str:
    if not action or len(action) > 200 or ".." in action or "\0" in action:
        raise CoinOSError("Invalid action parameter", skill="", script="", action=action, code="INVALID_ACTION")
    if not _ACTION_RE.match(action):
        raise CoinOSError("Action contains illegal characters", skill="", script="", action=action, code="INVALID_ACTION")
    return action


def _validate_timeout(raw) -> int | None:
    if raw is None:
        return None
    if not isinstance(raw, (int, float)) or raw <= 0:
        return None
    return min(int(raw), _MAX_TIMEOUT)


def _run(skill: str, script: str, action: str, params: dict | None = None, timeout: int | None = None):
    """Execute a skill script and return an agent-envelope response."""
    try:
        action = _validate_action(action)
        timeout = _validate_timeout(timeout)
        result = run_skill(skill, script, action, params=params, timeout=timeout)
        return envelope(result)
    except CoinOSError as exc:
        return envelope(
            {"error_code": exc.code or "COINOS_ERROR",
             "skill": exc.skill, "script": exc.script, "action": exc.action,
             "retriable": exc.code == "TIMEOUT"},
            message=str(exc),
            code=400,
            status=400,
        )
    except Exception:
        logger.exception("Unexpected error in agent CoinOS %s/%s/%s", skill, script, action)
        return envelope(
            {"error_code": "INTERNAL_ERROR"},
            message="An unexpected error occurred in CoinOS skill execution.",
            code=500,
            status=500,
        )


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@agent_v1_bp.route("/coinos/skills", methods=["GET"])
@agent_required(SCOPE_R)
def coinos_skills():
    """List available CoinOS skills and their scripts."""
    return envelope(list_skills())


# ---------------------------------------------------------------------------
# Market Data (R scope)
# ---------------------------------------------------------------------------

@agent_v1_bp.route("/coinos/market/<path:action>", methods=["GET", "POST"])
@agent_required(SCOPE_R)
def coinos_market(action: str):
    """Proxy to AiCoin market data (183 endpoints). GET=query, POST=JSON body."""
    if request.method == "POST":
        params = request.get_json(silent=True) or {}
    else:
        params = dict(request.args)
    return _run("aicoin-market", "aicoin", action, params=params)


@agent_v1_bp.route("/coinos/market-catalog", methods=["GET"])
@agent_required(SCOPE_R)
def coinos_market_catalog():
    """List AiCoin v3 API catalog."""
    group = request.args.get("group", "")
    if group and not _GROUP_RE.match(group):
        return envelope({"error_code": "INVALID_GROUP"}, message="group must be alphanumeric with - or _", code=400, status=400)
    action = f"catalog {group}".strip() if group else "catalog"
    return _run("aicoin-market", "aicoin", action)


@agent_v1_bp.route("/coinos/market-key-info", methods=["GET"])
@agent_required(SCOPE_R)
def coinos_market_key_info():
    """Check AiCoin API key tier and permissions."""
    return _run("aicoin-market", "aicoin", "key")


# ---------------------------------------------------------------------------
# Hyperliquid Whale Analytics (R scope)
# ---------------------------------------------------------------------------

@agent_v1_bp.route("/coinos/hyperliquid/<path:action>", methods=["GET", "POST"])
@agent_required(SCOPE_R)
def coinos_hyperliquid(action: str):
    """Hyperliquid on-chain whale analytics: positions, liquidations, OI, smart money."""
    if request.method == "POST":
        params = request.get_json(silent=True) or {}
    else:
        params = dict(request.args)
    if not action.startswith("hyperliquid/"):
        action = f"hyperliquid/{action}"
    return _run("aicoin-hyperliquid", "aicoin", action, params=params)


# ---------------------------------------------------------------------------
# CEX Trading (T scope)
# ---------------------------------------------------------------------------

@agent_v1_bp.route("/coinos/trading/<action>", methods=["POST"])
@agent_required(SCOPE_T)
def coinos_trading(action: str):
    """Execute CEX trades via CCXT. Actions: create_order, close_position, balance, etc."""
    body, err = _get_body()
    if err:
        return err
    timeout = body.pop("_timeout", None)
    return _run("aicoin-trading", "exchange", action, params=body or None, timeout=timeout)


@agent_v1_bp.route("/coinos/trading/auto/<action>", methods=["POST"])
@agent_required(SCOPE_T)
def coinos_trading_auto(action: str):
    """Automated trading strategy execution."""
    body, err = _get_body()
    if err:
        return err
    return _run("aicoin-trading", "auto-trade", action, params=body or None)


# ---------------------------------------------------------------------------
# Freqtrade (T scope for deploy/control, R scope for dev queries)
# ---------------------------------------------------------------------------

@agent_v1_bp.route("/coinos/freqtrade/deploy/<action>", methods=["POST"])
@agent_required(SCOPE_T)
def coinos_freqtrade_deploy(action: str):
    """Freqtrade strategy deployment: create, backtest, hyperopt, deploy."""
    body, err = _get_body()
    if err:
        return err
    timeout = body.pop("_timeout", None)
    return _run("aicoin-freqtrade", "ft-deploy", action, params=body or None, timeout=timeout)


@agent_v1_bp.route("/coinos/freqtrade/control/<action>", methods=["POST"])
@agent_required(SCOPE_T)
def coinos_freqtrade_control(action: str):
    """Freqtrade live bot control: profit, trades, balance, force enter/exit, etc."""
    body, err = _get_body()
    if err:
        return err
    return _run("aicoin-freqtrade", "ft", action, params=body or None)


@agent_v1_bp.route("/coinos/freqtrade/dev/<action>", methods=["POST"])
@agent_required(SCOPE_R)
def coinos_freqtrade_dev(action: str):
    """Freqtrade dev/debug tools (read-only): candles, whitelist, blacklist."""
    body, err = _get_body()
    if err:
        return err
    return _run("aicoin-freqtrade", "ft-dev", action, params=body or None)


# ---------------------------------------------------------------------------
# Account Management (R for queries, T for mutations)
# ---------------------------------------------------------------------------

@agent_v1_bp.route("/coinos/account/<action>", methods=["POST"])
@agent_required(SCOPE_R)
def coinos_account(action: str):
    """Account queries: balance, positions, open_orders, closed_orders, my_trades, exchanges."""
    body, err = _get_body()
    if err:
        return err
    return _run("aicoin-account", "exchange", action, params=body or None)


@agent_v1_bp.route("/coinos/account/key-info", methods=["GET"])
@agent_required(SCOPE_R)
def coinos_account_key_info():
    """Check configured exchange API key status."""
    return _run("aicoin-account", "api-key-info", "")


@agent_v1_bp.route("/coinos/account/tier", methods=["GET"])
@agent_required(SCOPE_R)
def coinos_account_tier():
    """Check AiCoin API tier and available features."""
    verify = "verify" if request.args.get("verify") else ""
    return _run("aicoin-account", "check-tier", verify)


# ---------------------------------------------------------------------------
# On-Chain DEX (T scope — moves capital)
# ---------------------------------------------------------------------------

@agent_v1_bp.route("/coinos/onchain/<script>/<action>", methods=["POST"])
@agent_required(SCOPE_T)
def coinos_onchain(script: str, action: str):
    """On-chain DEX via OKX Web3: token swap, wallet, gas estimation, tx broadcast."""
    body, err = _get_body()
    if err:
        return err
    return _run("aicoin-onchain", script, action, params=body or None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_body() -> tuple[dict | None, tuple | None]:
    """Parse optional JSON body — CoinOS endpoints tolerate empty bodies."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return None, error(400, "JSON body must be an object")
    return body, None
