"""Async database client — asyncpg connection pool and context manager.

All services acquire connections through this module.
DATABASE_URL is read from the environment (set via .env.local locally,
Secret Manager / Cloud Run env vars in production).
"""
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


async def get_db_pool() -> asyncpg.Pool:
    """Create and return an asyncpg connection pool.

    Reads DATABASE_URL from the environment.
    URL format: postgresql+asyncpg://user:password@host:port/dbname
    The asyncpg driver prefix is stripped before connecting.

    Returns:
        A connected asyncpg.Pool with min_size=2, max_size=10.
    """
    database_url = os.environ["DATABASE_URL"]
    # asyncpg expects plain postgresql:// — strip the SQLAlchemy driver prefix if present
    asyncpg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn=asyncpg_url,
        min_size=2,
        max_size=10,
    )
    return pool


@asynccontextmanager
async def get_db_connection(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection from the pool and release it on exit.

    Usage:
        async with get_db_connection(pool) as conn:
            row = await conn.fetchrow("SELECT ...")

    Args:
        pool: An active asyncpg.Pool returned by get_db_pool().

    Yields:
        An asyncpg.Connection checked out from the pool.
    """
    async with pool.acquire() as connection:
        yield connection
