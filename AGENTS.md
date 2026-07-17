# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

---

## Project Overview

ChanQuant is a self-hosted, open-source AI quant trading infrastructure. The stack is:

- **Backend**: Python 3.12 / Flask / Gunicorn (in `backend_api_python/`)
- **Database**: PostgreSQL 16 + Redis 7
- **Frontend**: Vue SPA served by Nginx (prebuilt image from GHCR, separate repo)
- **MCP Server**: `ChanQuant-mcp` Python package (in `mcp_server/`)
- **Deployment**: Docker Compose

The backend is the primary codebase in this repo. The frontend source lives in a sibling repo (`ChanQuant-Vue`) and is pulled as a prebuilt image by default.

---

## Common Commands

### Development (Local, without Docker)

```powershell
# Start the backend dev server (Flask threaded mode)
cd d:\aaron\miniso\ChanQuant\backend_api_python
python run.py
```

Requires `backend_api_python/.env` to be configured (copy from `env.example` first).

### Docker Stack

```powershell
# Start full stack (postgres, redis, backend, frontend)
docker compose up -d

# Rebuild backend only (after code changes)
docker compose up -d --build backend

# View backend logs
docker compose logs -f backend
```

### Tests

```powershell
# Run all tests from backend_api_python/
cd d:\aaron\miniso\ChanQuant\backend_api_python
pytest

# Run a single test file
pytest tests/test_health.py

# Run a single test
pytest tests/test_health.py::test_health_endpoint

# Run tests matching a keyword
pytest -k "grid"
```

Tests use `conftest.py` which sets `SKIP_STARTUP_HOOKS=1` and `CACHE_ENABLED=false` automatically. The test app is created with `create_app("testing")`.

### Backend Quality Check

```powershell
# Run structural quality guardrail (checks file sizes, banned patterns, etc.)
cd d:\aaron\miniso\ChanQuant\backend_api_python
python scripts/backend_quality_check.py
```

The baseline is in `scripts/backend_quality_baseline.json` — it records known large files/functions as regression guards.

### Version Bump

```powershell
# Bump the fallback version (repo-root VERSION + backend VERSION)
python scripts/bump_version.py 3.0.32
```

### MCP Server

```powershell
# Install and run MCP server locally
cd d:\aaron\miniso\ChanQuant\mcp_server
pip install -e .
ChanQuant-mcp
```

---

## Architecture

### Request Flow

```
Browser/MCP Client
       │
       ▼
  Nginx (port 8888) ──► Vue SPA (static)
       │
       ▼
  Flask API (port 5000)
       │
       ├── /api/...          Human Web API (JWT auth, flask-smorest OpenAPI)
       │
       └── /api/agent/v1/... Agent Gateway (token auth, audit logged)
              │
              ▼
        Service Layer (single source of truth for both surfaces)
```

### Two API Surfaces, One Service Layer

The critical architectural decision: the **Agent Gateway** (`/api/agent/v1/`) is a thin authentication layer, not a parallel implementation. Both the human web API and agent gateway call the same service classes.

- **Human Web API**: JWT sessions, registered via flask-smorest (OpenAPI-documented blueprints)
- **Agent Gateway**: Scoped tokens (`qd_agent_xxx` prefix), capability classes (R/W/B/N/C/T), audit logging, rate limiting, idempotency keys

### Application Factory Pattern

`app/__init__.py::create_app()` is the Flask factory. It:

1. Configures CORS from `FRONTEND_URL`
2. Bootstraps the database (runs `migrations/init.sql` idempotently via `SKIP_AUTO_MIGRATE`)
3. Ensures admin user exists
4. Registers routes via `app/routes/__init__.py::register_routes()`
5. Runs startup hooks via `app/startup.py::run_startup_hooks()`

### Startup Hooks (Background Workers)

`run_startup_hooks()` starts these background threads (all idempotent, controlled by env vars):

| Worker | Env Var | Purpose |
|--------|---------|---------|
| Pending Order Worker | `ENABLE_PENDING_ORDER_WORKER` | Dispatches queued orders, syncs positions |
| Grid Fill Poller | `ENABLE_GRID_FILL_POLLER` | Polls exchanges for grid bot limit-order fills |
| Portfolio Monitor | `ENABLE_PORTFOLIO_MONITOR` | Background portfolio health checks |
| USDT Order Worker | `USDT_PAY_ENABLED` | Watches blockchain for USDT payment confirmations |
| AI Calibration Worker | `ENABLE_OFFLINE_AI_CALIBRATION` | Periodically tunes AI decision thresholds |
| Reflection Worker | `ENABLE_REFLECTION_WORKER` | Validates past AI decisions against actual outcomes |
| Strategy Restore | `DISABLE_RESTORE_RUNNING_STRATEGIES` | Restores live strategies after restart |

Use `SKIP_STARTUP_HOOKS=1` to disable all hooks (used in tests).

### Key Subsystems

| Subsystem | Location | Notes |
|-----------|----------|-------|
| Routes (Human) | `app/routes/*.py` | Flask blueprints registered via flask-smorest |
| Routes (Agent) | `app/routes/agent_v1/` | Separate blueprint at `/api/agent/v1` |
| Services | `app/services/` | Business logic; called by both route surfaces |
| Data Sources | `app/data_sources/` | Market-specific OHLCV fetchers with circuit breakers |
| Data Providers | `app/data_providers/` | Higher-level aggregation (news, sentiment, calendar) |
| Utils | `app/utils/` | Auth, DB pool, agent auth, safe exec, caching |
| Markets | `app/markets/` | Market registry and models |
| OpenAPI | `app/openapi/` | flask-smorest schemas and blueprint registration |

### Dual Strategy Runtimes

ChanQuant supports two strategy authoring models:

1. **IndicatorStrategy** — vectorized dataframe scripts producing `buy`/`sell` signal columns; backtests run in `app/services/backtest.py`
2. **ScriptStrategy** — event-driven `on_bar(ctx, bar)` scripts with explicit `ctx.buy()` / `ctx.sell()` calls; runtime in `app/services/strategy_script_runtime.py`

Live strategies run in threads within the Gunicorn worker process (see `STRATEGY_MAX_THREADS` env var, default 64).

### Execution Adapters

Execution is split by broker type:

- `app/services/exchange_execution.py` — CCXT crypto (Binance, OKX, Bybit, etc.)
- `app/services/ibkr_trading/` — Interactive Brokers (TWS/IB Gateway)
- `app/services/mt5_trading/` — MetaTrader 5 (Windows only)
- `app/services/alpaca_trading/` — Alpaca (US stocks, ETFs, crypto)

### Database

- Single PostgreSQL 16 instance; schema defined in `migrations/init.sql` (all `CREATE TABLE IF NOT EXISTS`)
- Auto-migrated on every startup unless `SKIP_AUTO_MIGRATE=true`
- Connection pooling via `app/utils/db_postgres.py` (psycopg2 ThreadedConnectionPool)
- Tables prefixed `qd_` (e.g., `qd_users`, `qd_strategies`, `qd_analysis_memory`, `qd_agent_tokens`)

### Concurrency Model

- Gunicorn: 1 worker + N threads by default (`GUNICORN_WORKERS=1`, `GUNICORN_THREADS=8`)
- `preload_app = False` — background threads start in the worker process, not master
- Route-level thread pools for parallel fetches (`MARKET_EXECUTOR_WORKERS`, `PORTFOLIO_EXECUTOR_WORKERS`)

---

## Environment Configuration

All backend config is via `backend_api_python/.env` (copy from `env.example`).

Key areas:

| Area | Key Variables |
|------|--------------|
| Auth | `SECRET_KEY` (must not be default), `ADMIN_USER`, `ADMIN_PASSWORD` |
| Database | `DATABASE_URL`, `DB_POOL_MIN`, `DB_POOL_MAX` |
| LLM/AI | `LLM_PROVIDER`, provider-specific keys (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, etc.) |
| Agent Gateway | `AGENT_LIVE_TRADING_ENABLED`, `ChanQuant_DEPLOYMENT_MODE` |
| Workers | `ENABLE_PENDING_ORDER_WORKER`, `ENABLE_PORTFOLIO_MONITOR`, `ENABLE_REFLECTION_WORKER` |
| Proxy | `PROXY_URL` (for exchange traffic), `LLM_PROXY_URL` (separate for LLM providers) |

The root `.env` (optional) only controls Docker Compose settings (ports, image prefixes).

---

## Testing Conventions

- Tests live in `backend_api_python/tests/`
- `conftest.py` sets minimal env vars and creates the test app
- Test names follow `test_<feature>.py` pattern
- Integration tests requiring live exchange keys are marked with `@pytest.mark.integration`
- No database required for most tests (services are tested in isolation or via mocks)

---

## Agent Gateway Design

The Agent Gateway at `/api/agent/v1/` is intentionally separate from human routes:

- **Identity**: Agent tokens only (never JWT user sessions)
- **Capability classes**: R (Read), W (Workspace write), B (Backtest), N (Notifications), C (Credentials, admin-only), T (Trading, denied by default)
- **Audit**: Every call logged to `qd_agent_audit`
- **Safety**: Tokens default to `paper_only=true`; live trading requires explicit opt-in

See `docs/agent/AI_INTEGRATION_DESIGN.md` for the full design document.

---

## MCP Server

The `mcp_server/` directory contains the `ChanQuant-mcp` Python package:

- Wraps the Agent Gateway as Model Context Protocol tools
- Published to PyPI as `ChanQuant-mcp`
- Supports stdio, SSE, and streamable-http transports
- Requires an agent token (`ChanQuant_AGENT_TOKEN`) and base URL (`ChanQuant_BASE_URL`)

---

## Important Patterns

### Data Source Factory

`app/data_sources/factory.py` provides a factory pattern for market-specific data fetchers. Each market (crypto, US stock, CN stock, HK stock, forex, futures, MOEX) has its own module with circuit breaker and rate limiting.

### Safe Exec for Strategy Code

User-submitted strategy Python runs through `app/utils/safe_exec.py` which provides sandboxed execution with restricted builtins. Strategy code operates on pandas DataFrames (IndicatorStrategy) or via an event-driven context object (ScriptStrategy).

### Credential Encryption

Exchange API keys stored in `qd_exchange_credentials.encrypted_config` are encrypted using Fernet, derived from `SECRET_KEY`. Do not rotate `SECRET_KEY` casually — it invalidates all stored credentials.

### SaaS Mode Guard

When `ChanQuant_DEPLOYMENT_MODE=saas`, the Agent Gateway enforces:
- T-scope (trading) rejected at token issuance with 403
- `paper_only=true` forced on all tokens

This is tested by `tests/test_agent_v1_saas_guard.py`.
