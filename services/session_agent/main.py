"""Session & Feedback Agent service — DB pool singleton.

get_db_pool() is called by the tool functions via lazy import to avoid
circular dependencies between agent.py and the tools.
"""
import os
import sys

import asyncpg
import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(".env.local")

log = structlog.get_logger()

# ── DB pool singleton ──────────────────────────────────────────────────────────

_db_pool: asyncpg.Pool | None = None


async def get_db_pool() -> asyncpg.Pool:
    """Return the shared asyncpg connection pool, creating it on first call.

    Reads DATABASE_URL from the environment and strips the SQLAlchemy
    driver prefix so asyncpg can use the DSN directly.
    """
    global _db_pool
    if _db_pool is None:
        dsn = os.environ["DATABASE_URL"].replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        _db_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        log.info("session_agent.db_pool_created")
    return _db_pool


async def close_db_pool() -> None:
    """Close the pool gracefully on service shutdown."""
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
        log.info("session_agent.db_pool_closed")
