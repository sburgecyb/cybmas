"""Orchestrator service entry point.

Provides the process_request() coroutine consumed by the API Gateway.
It loads session history, classifies the engineer's intent, and returns
routing metadata so the gateway can forward the request to the correct
specialist agent — or the ADK orchestrator can delegate internally.

The DB pool and Redis client are module-level lazy singletons.
"""
import json
import os
import sys
from typing import Any

import asyncpg
import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(".env.local")

from services.orchestrator.intent_classifier import classify_intent  # noqa: E402
from services.orchestrator.router import route_to_agent  # noqa: E402
from services.shared.models import AgentRequest  # noqa: E402

log = structlog.get_logger()

# ── Lazy singletons ────────────────────────────────────────────────────────────

_db_pool: asyncpg.Pool | None = None
_redis_client: Any | None = None


async def get_db_pool() -> asyncpg.Pool:
    """Return (creating if necessary) the asyncpg connection pool."""
    global _db_pool
    if _db_pool is None:
        dsn = os.getenv("DATABASE_URL", "").replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        _db_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _db_pool


async def get_redis():
    """Return (creating if necessary) the Redis client."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as redis

        _redis_client = redis.from_url(
            os.getenv("REDIS_URL", "redis://127.0.0.1:6379"),
            decode_responses=True,
        )
    return _redis_client


# ── Orchestration logic ────────────────────────────────────────────────────────


async def process_request(request: AgentRequest) -> dict:
    """Classify intent and return routing metadata for an engineer request.

    Steps:
        1. Load session history from DB (if session_id provided).
        2. Classify intent using rule-based + Gemini fallback.
        3. Determine the target agent endpoint.
        4. Return routing info including the last 5 history messages as context.

    Args:
        request: Validated AgentRequest from the API Gateway.

    Returns:
        Dict with keys: intent, agent_endpoint, context_messages, session_id.
    """
    db_pool = await get_db_pool()

    # ── 1. Load session history ────────────────────────────────────────────────
    history: list[dict] = []
    if request.session_id:
        row = await db_pool.fetchrow(
            "SELECT messages FROM chat_sessions WHERE id = $1",
            request.session_id,
        )
        if row and row["messages"]:
            raw = row["messages"]
            history = json.loads(raw) if isinstance(raw, str) else raw

    # ── 2. Classify intent ─────────────────────────────────────────────────────
    has_history = len(history) > 0
    intent = await classify_intent(
        message=request.message,
        context_scope=request.context_scope,
        has_conversation_history=has_history,
    )

    # ── 3. Determine last agent from session metadata ──────────────────────────
    last_agent: str | None = None
    for msg in reversed(history):
        agent_tag = (msg.get("metadata") or {}).get("agent")
        if agent_tag:
            last_agent = agent_tag
            break

    # ── 4. Route ───────────────────────────────────────────────────────────────
    agent_endpoint = route_to_agent(intent, request.context_scope, last_agent)

    # Last 5 turns as context for the specialist agent
    context_messages = history[-5:] if history else []

    log.info(
        "orchestrator.request_routed",
        engineer_id=request.engineer_id,
        intent=intent.value,
        agent_endpoint=agent_endpoint,
        history_length=len(history),
    )

    return {
        "intent": intent.value,
        "agent_endpoint": agent_endpoint,
        "context_messages": context_messages,
        "session_id": str(request.session_id) if request.session_id else None,
    }
