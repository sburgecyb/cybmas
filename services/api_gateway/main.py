"""API Gateway — FastAPI application entry point.

Responsibilities:
- JWT authentication and CORS
- Per-engineer rate limiting via Redis
- Route all /api/* requests to the appropriate specialist agent
  (via the Orchestrator) and stream responses back as SSE
- Session and feedback persistence delegated to downstream services
"""
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import structlog
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"))

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
    import redis.asyncio as aioredis

    dsn = os.getenv("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    app.state.db_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    app.state.redis = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
    )
    log.info("api_gateway.started")

    yield

    await app.state.db_pool.close()
    await app.state.redis.aclose()
    log.info("api_gateway.stopped")


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Multi-Agent Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────

_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
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
