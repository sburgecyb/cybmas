"""API Gateway — FastAPI application entry point.

Responsibilities:
- JWT authentication and CORS
- Per-engineer rate limiting via Redis
- Route all /api/* requests to the appropriate specialist agent
  (via the Orchestrator) and stream responses back as SSE
- Session and feedback persistence delegated to downstream services
"""
import asyncio
import os
import re
import sys
from contextlib import asynccontextmanager, suppress
from typing import Any

import asyncpg
import httpx
import structlog
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"))

from services.shared.redis_async import (  # noqa: E402
    async_redis_from_url,
    is_redis_disabled,
    redis_url_from_env,
)

from services.api_gateway.middleware.auth_middleware import get_current_engineer  # noqa: E402
from services.api_gateway.middleware.rate_limit import check_rate_limit  # noqa: E402
from services.api_gateway.routers.auth_router import router as auth_router  # noqa: E402
from services.api_gateway.routers.chat_router import router as chat_router  # noqa: E402
from services.api_gateway.routers.feedback_router import router as feedback_router  # noqa: E402
from services.api_gateway.routers.sessions_router import router as sessions_router  # noqa: E402

# ── Logging ────────────────────────────────────────────────────────────────────

_log_format = os.getenv("LOG_FORMAT", "console")
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        (
            structlog.processors.JSONRenderer()
            if _log_format == "json"
            else structlog.dev.ConsoleRenderer()
        ),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the HTTP port immediately; connect DB/Redis in the background.

    Uvicorn only starts listening after lifespan yields. A slow or stuck
    ``create_pool`` (e.g. Cloud SQL socket misconfiguration) would otherwise
    exceed Cloud Run's startup probe timeout.
    """
    app.state.db_pool = None
    app.state.redis = None
    app.state.backends_ready = asyncio.Event()
    app.state.http_client = httpx.AsyncClient(timeout=120.0)

    async def _connect_backends() -> None:
        dsn = os.getenv("DATABASE_URL", "").replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        try:
            if dsn.strip():
                app.state.db_pool = await asyncpg.create_pool(
                    dsn, min_size=2, max_size=10
                )
            else:
                log.error("api_gateway.missing_database_url")
        except Exception as exc:
            log.exception("api_gateway.db_pool_failed", error=str(exc))
        try:
            if is_redis_disabled():
                log.info("api_gateway.redis_disabled")
            else:
                app.state.redis = async_redis_from_url(redis_url_from_env())
        except Exception as exc:
            log.exception("api_gateway.redis_client_failed", error=str(exc))
        log.info("api_gateway.backends_init_finished")
        app.state.backends_ready.set()

    init_task = asyncio.create_task(_connect_backends())
    log.info("api_gateway.listening_pending_backends")

    yield

    init_task.cancel()
    with suppress(asyncio.CancelledError):
        await init_task
    if app.state.db_pool is not None:
        await app.state.db_pool.close()
    if app.state.redis is not None:
        await app.state.redis.aclose()
    await app.state.http_client.aclose()
    log.info("api_gateway.stopped")


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Multi-Agent Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
# Starlette returns HTTP 400 on preflight (OPTIONS) if Origin is not allowed — exact
# string match on allow_origins, unless CORS_ORIGIN_REGEX full-matches (see .env.example).


def _parse_cors_origins(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.split(","):
        o = part.strip()
        if not o:
            continue
        while o.endswith("/"):
            o = o[:-1]
        out.append(o)
    return out


_origins = _parse_cors_origins(os.getenv("CORS_ORIGINS", "http://localhost:3000"))
_cors_regex = (os.getenv("CORS_ORIGIN_REGEX") or "").strip() or None
_cors_pattern = re.compile(_cors_regex) if _cors_regex else None


def cors_headers_for_request(request: Request) -> dict[str, str]:
    """Mirror CORSMiddleware allow-list so error responses still get ACAO (browser won't hide 500 as CORS)."""
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if origin in _origins:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }
    if _cors_pattern is not None and _cors_pattern.fullmatch(origin):
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }
    return {}


app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(
    chat_router,
    dependencies=[Depends(get_current_engineer), Depends(check_rate_limit)],
)
app.include_router(
    sessions_router,
    dependencies=[Depends(get_current_engineer), Depends(check_rate_limit)],
)
app.include_router(
    feedback_router,
    dependencies=[Depends(get_current_engineer), Depends(check_rate_limit)],
)

# ── Health ─────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


# ── Global exception handler ───────────────────────────────────────────────────


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "api_gateway.unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
        headers=cors_headers_for_request(request),
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("API_GATEWAY_PORT", "8000")),
        reload=True,
    )
