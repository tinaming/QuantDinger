"""Application startup hooks and process-local service singletons.

Multi-worker safety
-------------------
When Gunicorn runs multiple workers (``GUNICORN_WORKERS > 1``), every worker
process calls ``run_startup_hooks()`` independently.  One-shot tasks such as
strategy restore must not run more than once across the fleet.  We use a
PostgreSQL **advisory lock** (``pg_try_advisory_lock``) so exactly one worker
wins the lock and executes the guarded hooks; the others skip them silently.
The lock is session-scoped and released automatically when the worker's DB
connection closes (worker exit / restart), so no explicit unlock is required.
"""
from __future__ import annotations

import os
import threading
import time
import traceback

from flask import Flask

from app.utils.logger import get_logger


logger = get_logger(__name__)

_trading_executor = None
_pending_order_worker = None

# ---------------------------------------------------------------------------
# Background worker status tracking
# ---------------------------------------------------------------------------
# Updated by run_startup_hooks() so operators can inspect liveness via
# GET /api/settings/worker-status.
_WORKER_STATUS: dict = {
    "pending_order_worker": "not_started",
    "grid_fill_poller": "not_started",
    "portfolio_monitor": "not_started",
    "strategy_restore": "not_started",
    "usdt_order_worker": "not_started",
    "ai_calibration": "not_started",
    "reflection_worker": "not_started",
}
_worker_status_lock = threading.Lock()


def _set_worker_status(key: str, status: str) -> None:
    """Thread-safe status update."""
    with _worker_status_lock:
        if key in _WORKER_STATUS:
            _WORKER_STATUS[key] = status


def get_worker_status() -> dict:
    """Get current status of all background workers (snapshot copy)."""
    with _worker_status_lock:
        status = dict(_WORKER_STATUS)
    status["pid"] = os.getpid()
    return status


# ---------------------------------------------------------------------------
# Service singletons
# ---------------------------------------------------------------------------

def get_trading_executor():
    """Get the process-local trading executor singleton."""
    global _trading_executor
    if _trading_executor is None:
        from app.services.trading_executor import TradingExecutor
        _trading_executor = TradingExecutor()
    return _trading_executor


def get_pending_order_worker():
    """Get the process-local pending order worker singleton."""
    global _pending_order_worker
    if _pending_order_worker is None:
        from app.services.pending_order_worker import PendingOrderWorker
        _pending_order_worker = PendingOrderWorker()
    return _pending_order_worker


def _is_debug_reloader_parent() -> bool:
    debug = os.getenv("PYTHON_API_DEBUG", "false").lower() == "true"
    return debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"


# ---------------------------------------------------------------------------
# PostgreSQL advisory lock for multi-worker startup coordination
# ---------------------------------------------------------------------------
_STARTUP_ADVISORY_LOCK_ID = 9876543210  # arbitrary unique int64


def _acquire_startup_lock(conn, lock_id: int = _STARTUP_ADVISORY_LOCK_ID) -> bool:
    """Try to acquire a session-level advisory lock.

    Returns True if this worker is the *leader* (lock acquired).
    Returns False if another worker already holds the lock.
    The lock is automatically released when the connection is closed
    (i.e. when the worker process exits), so no explicit unlock is needed.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
            acquired = cur.fetchone()[0]
        if acquired:
            logger.info("Startup advisory lock acquired (lock_id=%s) — this worker will run one-shot hooks.", lock_id)
        else:
            logger.info("Startup advisory lock held by another worker (lock_id=%s) — skipping one-shot hooks.", lock_id)
        return bool(acquired)
    except Exception as exc:
        logger.warning("Could not acquire startup advisory lock; falling back to running hooks: %s", exc)
        # If advisory lock fails (e.g. read-only replica), fall back to running hooks
        # to avoid a total startup failure.
        return True


def _get_startup_lock_conn():
    """Open a lightweight dedicated connection for the advisory lock.

    We deliberately use a *separate* connection (not from the app pool) so the
    lock's lifetime is tied to this connection object, which we can close
    explicitly after hooks finish — releasing the lock without waiting for
    worker exit.
    """
    try:
        import psycopg2
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return None
        conn = psycopg2.connect(db_url, application_name="chanquant_startup_lock")
        conn.autocommit = True
        return conn
    except Exception as exc:
        logger.warning("Could not open advisory-lock connection; hooks will run without coordination: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Individual service starters
# ---------------------------------------------------------------------------

def start_portfolio_monitor():
    """Start the portfolio monitor service if enabled."""
    if os.getenv("ENABLE_PORTFOLIO_MONITOR", "true").lower() != "true":
        logger.info("Portfolio monitor is disabled. Set ENABLE_PORTFOLIO_MONITOR=true to enable.")
        _set_worker_status("portfolio_monitor", "disabled")
        return
    if _is_debug_reloader_parent():
        _set_worker_status("portfolio_monitor", "skipped_reloader_parent")
        return
    try:
        from app.services.portfolio_monitor import start_monitor_service
        start_monitor_service()
        _set_worker_status("portfolio_monitor", "running")
    except Exception as e:
        logger.error(f"Failed to start portfolio monitor: {e}")
        _set_worker_status("portfolio_monitor", "error")


def start_pending_order_worker():
    """Start the pending order worker."""
    if os.getenv("ENABLE_PENDING_ORDER_WORKER", "true").lower() != "true":
        logger.info("Pending order worker is disabled. Set ENABLE_PENDING_ORDER_WORKER=true to enable.")
        _set_worker_status("pending_order_worker", "disabled")
        return
    try:
        get_pending_order_worker().start()
        _set_worker_status("pending_order_worker", "running")
    except Exception as e:
        logger.error(f"Failed to start pending order worker: {e}")
        _set_worker_status("pending_order_worker", "error")


def start_grid_fill_poller():
    """Poll exchange for grid resting limit order fills."""
    if os.getenv("ENABLE_GRID_FILL_POLLER", "true").lower() != "true":
        logger.info("Grid fill poller disabled (ENABLE_GRID_FILL_POLLER=false)")
        _set_worker_status("grid_fill_poller", "disabled")
        return
    if _is_debug_reloader_parent():
        _set_worker_status("grid_fill_poller", "skipped_reloader_parent")
        return
    try:
        from app.services.grid.poller import get_grid_fill_poller
        get_grid_fill_poller().start()
        _set_worker_status("grid_fill_poller", "running")
    except Exception as e:
        logger.error(f"Failed to start grid fill poller: {e}")
        _set_worker_status("grid_fill_poller", "error")


def start_usdt_order_worker():
    """Start the USDT order background worker."""
    raw_enabled = os.getenv("USDT_PAY_ENABLED", "")
    enabled = raw_enabled.strip().lower() in ("1", "true", "yes")
    enabled_chains = os.getenv("USDT_PAY_ENABLED_CHAINS", "")
    poll_interval = os.getenv("USDT_WORKER_POLL_INTERVAL", "30")

    logger.info(
        "USDT pay boot check: USDT_PAY_ENABLED=%r (parsed=%s) chains=%r poll=%ss",
        raw_enabled, enabled, enabled_chains, poll_interval,
    )
    if not enabled:
        logger.info(
            "USDT order worker NOT started; USDT_PAY_ENABLED is %r. "
            "Set USDT_PAY_ENABLED=true in .env and restart the container.",
            raw_enabled,
        )
        _set_worker_status("usdt_order_worker", "disabled")
        return
    if _is_debug_reloader_parent():
        logger.info(
            "USDT order worker skipped in this Flask reloader parent "
            "(WERKZEUG_RUN_MAIN!=true); the child process will start it."
        )
        _set_worker_status("usdt_order_worker", "skipped_reloader_parent")
        return
    try:
        from app.services.usdt_payment_service import get_usdt_order_worker
        worker = get_usdt_order_worker()
        worker.start()
        logger.info(
            "USDT order worker boot OK; thread alive=%s, scanning every %ss",
            worker.is_alive() if hasattr(worker, "is_alive") else "n/a",
            poll_interval,
        )
        _set_worker_status("usdt_order_worker", "running")
    except Exception as e:
        logger.error(f"Failed to start USDT order worker: {e}", exc_info=True)
        _set_worker_status("usdt_order_worker", "error")


def restore_running_strategies():
    """Restore running strategies on startup.

    Guarded by the advisory lock in run_startup_hooks() so this runs exactly
    once across all Gunicorn workers.
    """
    if os.getenv("DISABLE_RESTORE_RUNNING_STRATEGIES", "false").lower() == "true":
        logger.info("Startup strategy restore is disabled via DISABLE_RESTORE_RUNNING_STRATEGIES")
        _set_worker_status("strategy_restore", "disabled")
        return
    if _is_debug_reloader_parent():
        _set_worker_status("strategy_restore", "skipped_reloader_parent")
        return
    try:
        from app.services.strategy import StrategyService

        strategy_service = StrategyService()
        trading_executor = get_trading_executor()
        running_strategies = strategy_service.get_running_strategies_with_type()
        if not running_strategies:
            logger.info("No running strategies to restore.")
            _set_worker_status("strategy_restore", "running")
            return

        logger.info(f"Restoring {len(running_strategies)} running strategies...")
        restored_count = 0
        for strategy_info in running_strategies:
            strategy_id = strategy_info["id"]
            strategy_type = strategy_info.get("strategy_type", "")
            try:
                success = trading_executor.start_strategy(strategy_id)
                strategy_type_name = strategy_type or "Strategy"
                if success:
                    restored_count += 1
                    logger.info(f"[OK] {strategy_type_name} {strategy_id} restored")
                else:
                    logger.warning(f"[FAIL] {strategy_type_name} {strategy_id} restore failed (state may be stale)")
                    try:
                        strategy_service.update_strategy_status(strategy_id, "stopped")
                        logger.info(f"[FIX] Updated strategy {strategy_id} status to 'stopped' after restore failure")
                    except Exception as e:
                        logger.error(f"Failed to update strategy {strategy_id} status after restore failure: {e}")
            except Exception as e:
                logger.error(f"Error restoring strategy {strategy_id}: {str(e)}")
                logger.error(traceback.format_exc())

        logger.info(f"Strategy restore completed: {restored_count}/{len(running_strategies)} restored")
        _set_worker_status("strategy_restore", "running")
        _schedule_post_restore_position_sync()
    except Exception as e:
        logger.error(f"Failed to restore running strategies: {str(e)}")
        logger.error(traceback.format_exc())
        _set_worker_status("strategy_restore", "error")


def _schedule_post_restore_position_sync() -> None:
    """Run one delayed position-sync pass after restored strategies start."""
    if os.getenv("POSITION_SYNC_ENABLED", "true").lower() != "true":
        return
    try:
        delay = float(os.getenv("POST_RESTORE_SYNC_DELAY_SEC", "12"))
    except Exception:
        delay = 12.0
    if delay < 0:
        delay = 0.0

    def _run() -> None:
        if delay > 0:
            time.sleep(delay)
        try:
            get_pending_order_worker()._sync_positions_best_effort()
            logger.info("Post-restore position sync finished (broken live strategies should be stopped)")
        except Exception as exc:
            logger.warning(f"Post-restore position sync failed: {exc}")

    threading.Thread(target=_run, name="PostRestorePositionSync", daemon=True).start()


def run_startup_hooks(app: Flask) -> None:
    """Run optional background startup hooks after route registration.

    Multi-worker coordination:
    - Long-running background services (pending_order_worker, grid_fill_poller,
      portfolio_monitor, usdt_order_worker) are started in *every* worker so
      each process has its own thread pool for handling requests that touch
      those services.
    - One-shot tasks (strategy restore) are guarded by a PostgreSQL advisory
      lock so only one worker in the fleet runs them, preventing duplicate
      strategy threads and race conditions.
    """
    skip_hooks = os.getenv("SKIP_STARTUP_HOOKS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if skip_hooks:
        return
    with app.app_context():
        _check_coinos_dependencies()

        # --- Per-worker services (safe to start in every worker) -----------
        start_pending_order_worker()
        start_grid_fill_poller()
        start_portfolio_monitor()
        start_usdt_order_worker()

        # --- AI background workers (idempotent; safe in every worker) ------
        try:
            from app.services.ai_calibration import start_ai_calibration_worker
            start_ai_calibration_worker()
            _set_worker_status("ai_calibration", "running")
        except Exception:
            _set_worker_status("ai_calibration", "error")
        try:
            from app.services.reflection import start_reflection_worker
            start_reflection_worker()
            _set_worker_status("reflection_worker", "running")
        except Exception:
            _set_worker_status("reflection_worker", "error")

        # --- One-shot hooks (advisory-lock guarded) -----------------------
        # Strategy restore must not run concurrently in multiple workers.
        lock_conn = _get_startup_lock_conn()
        is_leader = True  # default: run hooks if lock unavailable
        if lock_conn is not None:
            is_leader = _acquire_startup_lock(lock_conn)
        if is_leader:
            try:
                restore_running_strategies()
            finally:
                # Release the advisory lock by closing the dedicated connection
                # so the next worker restart can re-acquire it.
                if lock_conn is not None:
                    try:
                        lock_conn.close()
                    except Exception:
                        pass
        else:
            logger.info("Skipping strategy restore (another worker holds the advisory lock).")
            _set_worker_status("strategy_restore", "skipped_other_worker")


def _check_coinos_dependencies() -> None:
    """Non-blocking CoinOS dependency check at startup."""
    try:
        from app.services.coinos.runner import list_skills, _node_binary
        try:
            _node_binary()
        except Exception as exc:
            logger.warning("CoinOS: Node.js not available — /api/coinos/* endpoints will fail: %s", exc)
            return
        skills = list_skills()
        unavailable = [s["name"] for s in skills if not s["available"]]
        if unavailable:
            logger.warning("CoinOS: skills not available (coinos-skills/ may not be cloned): %s", unavailable)
        else:
            logger.info("CoinOS: all %d skills available", len(skills))
    except Exception as exc:
        logger.warning("CoinOS: dependency check failed: %s", exc)
