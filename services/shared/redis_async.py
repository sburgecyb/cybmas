"""Async Redis helpers: bounded timeouts and optional disable without hanging requests."""
import os
from typing import Any


def is_redis_disabled() -> bool:
    """When true, callers should skip Redis entirely (no TCP)."""
    return os.getenv("REDIS_DISABLED", "").strip().lower() in ("1", "true", "yes")


def redis_url_from_env() -> str:
    """REDIS_URL with localhost default for local dev."""
    return (
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379").strip()
        or "redis://127.0.0.1:6379"
    )


def _timeout_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        return v if v > 0 else default
    except ValueError:
        return default


def async_redis_from_url(url: str, **kwargs: Any) -> Any:
    """Build ``redis.asyncio`` client with connect/socket timeouts (fail fast if Redis is gone)."""
    import redis.asyncio as redis

    opts: dict[str, Any] = {
        "socket_connect_timeout": _timeout_env("REDIS_SOCKET_CONNECT_TIMEOUT", 2.0),
        "socket_timeout": _timeout_env("REDIS_SOCKET_TIMEOUT", 3.0),
    }
    opts.update(kwargs)
    return redis.from_url(url, **opts)
