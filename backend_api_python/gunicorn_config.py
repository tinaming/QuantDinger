"""Gunicorn configuration for ChanQuant backend.

Background workers (strategy restore, portfolio monitor, etc.) are started
inside ``create_app()`` which is called once per worker.  We use gthread
(threads in a single worker) by default to keep a familiar single-process
model while still allowing concurrent I/O.  Increase ``workers`` for
higher throughput — background tasks are idempotent and use DB advisory
locks to coordinate, so duplicate work is minimal.

SaaS deployment (10-1000 users) recommended defaults:
    GUNICORN_WORKERS=2   — utilise 2 CPU cores; raise for heavier load.
    GUNICORN_THREADS=8   — 8 threads per worker for concurrent DB / HTTP I/O.

DB pool sizing with multiple workers:
    Each worker holds its own psycopg2 pool. Total DB connections is roughly
    GUNICORN_WORKERS × DB_POOL_MAX.  When GUNICORN_WORKERS=2, make sure
    PostgreSQL max_connections >= workers * DB_POOL_MAX + reserve.
    The DB_POOL_MAX=auto logic in db_postgres.py already accounts for this.
"""
import os

bind = f"{os.getenv('PYTHON_API_HOST', '0.0.0.0')}:{os.getenv('PYTHON_API_PORT', '5000')}"

# Default: 2 workers + 8 threads — suitable for a SaaS deployment with
# 10-1000 concurrent users on a 2-core machine.  Single-user / dev setups
# can set GUNICORN_WORKERS=1 in .env to match the old behaviour.
workers = int(os.getenv("GUNICORN_WORKERS", 2))
threads = int(os.getenv("GUNICORN_THREADS", 8))

worker_class = "gthread"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "360"))
graceful_timeout = 30
keepalive = 5

# Do NOT preload — background threads in create_app() rely on being in
# the actual worker process.  preload would start them in master then
# lose them after fork.  Each worker also acquires a PostgreSQL advisory
# lock before running one-shot startup hooks (strategy restore, etc.) to
# guarantee idempotency across workers.
preload_app = False

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

limit_request_line = 8190
limit_request_fields = 100
