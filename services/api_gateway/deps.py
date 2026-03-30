"""Shared FastAPI dependencies for the API gateway."""
import asyncio
import os
import sys

import asyncpg
from fastapi import HTTPException, Request, status

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_BACKENDS_WAIT_S = int(os.getenv("API_GATEWAY_BACKENDS_WAIT_S", "120"))


async def get_db_pool(request: Request) -> asyncpg.Pool:
    """Return the DB pool after background startup has finished (or timed out)."""
    ready = getattr(request.app.state, "backends_ready", None)
    if ready is not None and not ready.is_set():
        await asyncio.wait_for(ready.wait(), timeout=_BACKENDS_WAIT_S)
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )
    return pool
