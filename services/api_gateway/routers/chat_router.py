"""Chat routes: SSE streaming chat and message history retrieval."""
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator

import asyncpg
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.api_gateway.middleware.auth_middleware import get_current_engineer  # noqa: E402
from services.shared.models import AgentRequest, BusinessUnitScope  # noqa: E402

log = structlog.get_logger()

router = APIRouter(prefix="/api/chat", tags=["chat"])

ORCHESTRATOR_ENDPOINT = os.getenv("ORCHESTRATOR_ENDPOINT", "http://localhost:8001")


# ── Shared dependency ──────────────────────────────────────────────────────────


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


# ── SSE helpers ────────────────────────────────────────────────────────────────


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream_orchestrator(
    agent_request: AgentRequest,
) -> AsyncIterator[str]:
    """Stream-forward SSE from the orchestrator to the browser.

    The orchestrator's /process endpoint now returns SSE (sources → token
    chunks → done).  We open an httpx streaming connection and forward each
    SSE line directly so the browser sees tokens as they arrive from Gemini,
    rather than waiting for the full response.
    """
    payload = agent_request.model_dump(mode="json")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{ORCHESTRATOR_ENDPOINT}/process",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                # aiter_lines() strips trailing \n; we must re-add \n\n so
                # the browser EventSource parser recognises each event.
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"
                    # empty lines between SSE events are skipped by aiter_lines
    except httpx.ConnectError:
        log.error("chat.orchestrator_unreachable", endpoint=ORCHESTRATOR_ENDPOINT)
        yield _sse({"type": "error", "message": "Orchestrator service unavailable"})
    except httpx.HTTPStatusError as exc:
        log.error("chat.orchestrator_error", status=exc.response.status_code)
        yield _sse({"type": "error", "message": f"Orchestrator returned {exc.response.status_code}"})
    except Exception as exc:
        log.error("chat.stream_error", error=str(exc))
        yield _sse({"type": "error", "message": "An unexpected error occurred"})


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("")
async def chat(
    request: Request,
    caller: dict = Depends(get_current_engineer),
) -> StreamingResponse:
    """Accept a chat message and stream the agent response as SSE.

    Body fields:
        message: Engineer's question or request.
        session_id: Optional UUID to continue an existing conversation.
        context_scope: Business unit selection and incident-mode flag.
    """
    body = await request.json()

    session_id_str: str = body.get("session_id") or str(uuid.uuid4())
    context_scope = BusinessUnitScope(**body["context_scope"])

    agent_request = AgentRequest(
        session_id=uuid.UUID(session_id_str),
        engineer_id=caller["engineer_id"],
        message=body["message"],
        context_scope=context_scope,
    )

    log.info(
        "chat.request",
        engineer_id=caller["engineer_id"],
        session_id=session_id_str,
    )

    return StreamingResponse(
        _stream_orchestrator(agent_request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: str,
    caller: dict = Depends(get_current_engineer),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return the full message history for a session owned by the caller."""
    try:
        row = await pool.fetchrow(
            "SELECT engineer_id, messages FROM chat_sessions WHERE id = $1",
            uuid.UUID(session_id),
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session ID")

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if row["engineer_id"] != caller["engineer_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    raw = row["messages"]
    messages: list = json.loads(raw) if isinstance(raw, str) else (raw or [])

    return {"session_id": session_id, "messages": messages}
