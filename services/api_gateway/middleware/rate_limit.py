"""Per-engineer rate limiter: 60 requests per minute enforced via Redis."""
import asyncio
import os
import time
from contextlib import suppress

import structlog
from fastapi import HTTPException, Request, status

log = structlog.get_logger()

_LIMIT = 60          # requests per minute
_WINDOW = 60         # seconds
_TTL = 120           # key TTL — 2× window so Redis cleans up naturally
_REDIS_OP_TIMEOUT = 5.0  # seconds — avoid hanging when Redis host is gone


async def check_rate_limit(request: Request) -> None:
    """Raise HTTP 429 if the engineer exceeds 60 requests per minute.

    Uses a sliding-window approximation: one Redis key per engineer per
    UTC minute bucket, incremented on each request, expiring after 2 minutes.
    Skips rate-limiting for unauthenticated requests (let auth middleware
    handle those separately).
    """
    engineer_id: str | None = getattr(request.state, "engineer_id", None)
    if not engineer_id:
        return

    ready = getattr(request.app.state, "backends_ready", None)
    if ready is not None and not ready.is_set():
        with suppress(Exception):
            await asyncio.wait_for(ready.wait(), timeout=60.0)

    redis = request.app.state.redis
    if redis is None:
        return
    bucket = int(time.time() // _WINDOW)
    key = f"ratelimit:{engineer_id}:{bucket}"

    try:
        async def _incr_and_ttl() -> int:
            n = await redis.incr(key)
            if n == 1:
                await redis.expire(key, _TTL)
            return n

        count = await asyncio.wait_for(_incr_and_ttl(), timeout=_REDIS_OP_TIMEOUT)

        if count > _LIMIT:
            seconds_until_reset = _WINDOW - (int(time.time()) % _WINDOW)
            log.warning(
                "rate_limit.exceeded",
                engineer_id=engineer_id,
                count=count,
                retry_after=seconds_until_reset,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Maximum 60 requests per minute.",
                headers={"Retry-After": str(seconds_until_reset)},
            )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        log.warning("rate_limit.redis_timeout", timeout_s=_REDIS_OP_TIMEOUT)
    except Exception as exc:
        # Redis errors should not block the request
        log.warning("rate_limit.redis_error", error=str(exc))
