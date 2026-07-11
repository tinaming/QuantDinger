"""
CoinOS skill script runner — executes Node.js CLI scripts via subprocess.

Each coinos-skills script follows a uniform pattern:
    node <script>.mjs <action> '<json_params>'
and returns a JSON envelope ``{ ok, data, error, meta }``.

The runner resolves the skill directory, spawns the process, and parses
the result. Timeouts and errors are surfaced as service-layer exceptions.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill directory resolution
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]  # coinos/runner.py -> services -> app -> backend_api_python -> repo root
_COINOS_ROOT = _REPO_ROOT / "coinos-skills" / "skills"

# Map skill name -> skill directory (containing scripts/)
SKILL_DIRS: dict[str, Path] = {
    "aicoin-market": _COINOS_ROOT / "aicoin-market",
    "aicoin-trading": _COINOS_ROOT / "aicoin-trading",
    "aicoin-hyperliquid": _COINOS_ROOT / "aicoin-hyperliquid",
    "aicoin-freqtrade": _COINOS_ROOT / "aicoin-freqtrade",
    "aicoin-account": _COINOS_ROOT / "aicoin-account",
    "aicoin-onchain": _COINOS_ROOT / "aicoin-onchain",
}

# Map skill -> { script_alias: script_filename }
SKILL_SCRIPTS: dict[str, dict[str, str]] = {
    "aicoin-market": {"aicoin": "aicoin.mjs"},
    "aicoin-hyperliquid": {"aicoin": "aicoin.mjs"},
    "aicoin-trading": {
        "exchange": "exchange.mjs",
        "trade": "trade.mjs",
        "auto-trade": "auto-trade.mjs",
        "register": "register.mjs",
        "verify-order-matrix": "verify-order-matrix.mjs",
    },
    "aicoin-freqtrade": {
        "ft-deploy": "ft-deploy.mjs",
        "ft": "ft.mjs",
        "ft-dev": "ft-dev.mjs",
    },
    "aicoin-account": {
        "exchange": "exchange.mjs",
        "api-key-info": "api-key-info.mjs",
        "check-tier": "check-tier.mjs",
        "register": "register.mjs",
    },
    "aicoin-onchain": {
        "swap": "swap.mjs",
        "portfolio": "portfolio.mjs",
        "market": "market.mjs",
        "token": "token.mjs",
        "trade": "trade.mjs",
        "gateway": "gateway.mjs",
    },
}

# Default timeout per skill (seconds). Trading ops may need more time.
_DEFAULT_TIMEOUT = 60
_SKILL_TIMEOUTS: dict[str, int] = {
    "aicoin-trading": 120,
    "aicoin-freqtrade": 300,  # backtest / deploy can be slow
    "aicoin-onchain": 90,
}


# Limit concurrent CoinOS subprocess executions to avoid exhausting Gunicorn threads.
_COINOS_MAX_CONCURRENT = int(os.getenv("COINOS_MAX_CONCURRENT", "2"))
_coinos_semaphore = threading.Semaphore(_COINOS_MAX_CONCURRENT)


class CoinOSError(Exception):
    """Raised when a CoinOS skill script fails."""

    def __init__(self, message: str, skill: str, script: str, action: str, code: str | None = None):
        super().__init__(message)
        self.skill = skill
        self.script = script
        self.action = action
        self.code = code


def _node_binary() -> str:
    """Resolve the node binary path."""
    node = os.getenv("COINOS_NODE_BIN", "")
    if node:
        return node
    found = shutil.which("node")
    if found:
        return found
    raise CoinOSError(
        "Node.js not found. Install Node.js 18+ or set COINOS_NODE_BIN.",
        skill="", script="", action="", code="NODE_NOT_FOUND",
    )


def run_skill(
    skill: str,
    script: str,
    action: str,
    params: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Execute a CoinOS skill script and return parsed JSON result.

    Parameters
    ----------
    skill : str
        Skill name (e.g. ``aicoin-market``).
    script : str
        Script alias (e.g. ``aicoin``, ``exchange``, ``swap``).
    action : str
        Action / endpoint path (e.g. ``market/ticker``, ``create_order``).
    params : dict, optional
        JSON-serialisable parameters passed as the second CLI argument.
    timeout : int, optional
        Override default timeout in seconds.

    Returns
    -------
    dict
        Parsed JSON from the script's stdout.

    Raises
    ------
    CoinOSError
        On script failure, timeout, or missing skill/script.
    """
    if skill not in SKILL_DIRS:
        raise CoinOSError(f"Unknown skill: {skill}", skill=skill, script=script, action=action, code="UNKNOWN_SKILL")

    skill_dir = SKILL_DIRS[skill]
    if not skill_dir.is_dir():
        raise CoinOSError(
            f"Skill directory not found: {skill_dir}. Did you clone coinos-skills?",
            skill=skill, script=script, action=action, code="SKILL_DIR_MISSING",
        )

    scripts_map = SKILL_SCRIPTS.get(skill, {})
    script_file = scripts_map.get(script)
    if not script_file:
        raise CoinOSError(
            f"Unknown script '{script}' for skill '{skill}'. Available: {list(scripts_map.keys())}",
            skill=skill, script=script, action=action, code="UNKNOWN_SCRIPT",
        )

    script_path = skill_dir / "scripts" / script_file
    if not script_path.is_file():
        raise CoinOSError(
            f"Script file not found: {script_path}",
            skill=skill, script=script, action=action, code="SCRIPT_FILE_MISSING",
        )

    # Build command
    cmd = [_node_binary(), str(script_path), action]
    if params is not None:
        cmd.append(json.dumps(params, ensure_ascii=False, separators=(",", ":")))

    effective_timeout = timeout or _SKILL_TIMEOUTS.get(skill, _DEFAULT_TIMEOUT)

    logger.info("CoinOS exec: skill=%s script=%s action=%s timeout=%ds", skill, script, action, effective_timeout)

    try:
        with _coinos_semaphore:
            result = subprocess.run(
                cmd,
                cwd=str(skill_dir),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                env=_build_env(),
            )
    except subprocess.TimeoutExpired:
        raise CoinOSError(
            f"Script timed out after {effective_timeout}s",
            skill=skill, script=script, action=action, code="TIMEOUT",
        )
    except OSError as exc:
        raise CoinOSError(
            f"Failed to execute node: {exc}",
            skill=skill, script=script, action=action, code="EXEC_ERROR",
        )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # Try parsing stdout as JSON
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            # Some scripts output non-JSON (e.g. freqtrade daemon logs)
            parsed = {"ok": result.returncode == 0, "data": stdout, "raw": True}
    else:
        parsed = {"ok": result.returncode == 0, "data": None}

    # Check for errors
    if result.returncode != 0 or (isinstance(parsed, dict) and parsed.get("ok") is False):
        error_msg = ""
        error_code = None
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict):
                error_msg = err.get("message", str(err))
                error_code = err.get("code")
            elif isinstance(err, str):
                error_msg = err
        if not error_msg:
            error_msg = stderr or f"Script exited with code {result.returncode}"

        raise CoinOSError(
            error_msg,
            skill=skill, script=script, action=action,
            code=error_code or f"EXIT_{result.returncode}",
        )

    if stderr:
        logger.debug("CoinOS stderr (%s/%s): %s", skill, script, stderr[:500])

    return parsed


# Suffixes that should NEVER be forwarded even if prefix matches.
_BLOCKED_ENV_KEYWORDS = frozenset({
    "PASSWORD", "SECRET", "PRIVATE_KEY", "CREDENTIAL", "TOKEN_INTERNAL",
})

# Allowed env-var prefixes forwarded to Node.js subprocesses.
# Blocks SECRET_KEY, DATABASE_URL, ADMIN_PASSWORD, LLM keys, etc.
_ALLOWED_ENV_PREFIXES = (
    "COINOS_",       # CoinOS-specific config
    "AICOIN_",       # AiCoin API credentials
    "BINANCE_",      # Binance exchange keys
    "OKX_",          # OKX exchange + Web3 keys
    "BYBIT_",        # Bybit exchange keys
    "BITGET_",       # Bitget exchange keys
    "GATE_",         # Gate.io exchange keys
    "HTX_",          # HTX exchange keys
    "PIONEX_",       # Pionex exchange keys
    "HYPERLIQUID_",  # Hyperliquid wallet keys
    "WALLET_",       # Wallet private keys (onchain)
    "FREQTRADE_",    # Freqtrade REST auth
    "PROXY_URL",     # HTTP proxy for exchange traffic
    "HTTPS_PROXY",   # Standard proxy env
    "HTTP_PROXY",    # Standard proxy env
    "NODE_ENV",      # Node.js environment
    "PATH",          # System PATH
    "HOME",          # Home directory
    "TMPDIR",        # Temp directory
    "LANG",          # Locale
    "NODE_PATH",     # Node module resolution
)


def _build_env() -> dict[str, str]:
    """Build subprocess env, forwarding only whitelisted variables."""
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if any(key.startswith(p) for p in _ALLOWED_ENV_PREFIXES):
            # Extra guard: block sensitive suffixes even if prefix matches
            upper = key.upper()
            if any(blocked in upper for blocked in _BLOCKED_ENV_KEYWORDS):
                continue
            env[key] = value
    # Ensure NODE_PATH includes skill node_modules
    node_path = env.get("NODE_PATH", "")
    for skill_dir in SKILL_DIRS.values():
        nm = str(skill_dir / "node_modules")
        if nm not in node_path:
            node_path = f"{nm}{os.pathsep}{node_path}" if node_path else nm
    env["NODE_PATH"] = node_path
    return env


def list_skills() -> list[dict[str, Any]]:
    """Return metadata about available CoinOS skills."""
    skills = []
    for name, skill_dir in SKILL_DIRS.items():
        available = skill_dir.is_dir()
        scripts = list(SKILL_SCRIPTS.get(name, {}).keys())
        skills.append({
            "name": name,
            "available": available,
            "scripts": scripts,
        })
    return skills
