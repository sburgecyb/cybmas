"""Session management routes: list and delete chat sessions."""
import json
import os
import sys
import uuid

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.api_gateway.middleware.auth_middleware import get_current_engineer  # noqa: E402

log = structlog.get_logger()

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ── Shared dependency ──────────────────────────────────────────────────────────


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("")
async def list_sessions(
    caller: dict = Depends(get_current_engineer),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return the 20 most recent sessions for the authenticated engineer."""
    rows = await pool.fetch(
        """
        SELECT id, title, messages, updated_at
        FROM chat_sessions
        WHERE engineer_id = $1
        ORDER BY updated_at DESC
        LIMIT 20
        """,
        caller["engineer_id"],
    )

    sessions: list[dict] = []
    for row in rows:
        raw = row["messages"] or "[]"
        messages: list = json.loads(raw) if isinstance(raw, str) else raw
        last_msg = messages[-1] if messages else None
        preview: str | None = (last_msg.get("content", "")[:100] if last_msg else None)

        sessions.append(
            {
                "id": str(row["id"]),
                "title": row["title"] or "Untitled session",
                "last_message_preview": preview,
                "updated_at": row["updated_at"].isoformat(),
            }
        )

    return {"sessions": sessions, "total": len(sessions)}


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    caller: dict = Depends(get_current_engineer),
    pool: asyncpg.Pool = Depends(get_pool),
) -> None:
    """Delete a session — the caller must own it."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session ID")

    row = await pool.fetchrow(
        "SELECT engineer_id FROM chat_sessions WHERE id = $1",
        sid,
    )

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if row["engineer_id"] != caller["engineer_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await pool.execute("DELETE FROM chat_sessions WHERE id = $1", sid)
    log.info("sessions.deleted", session_id=session_id, engineer_id=caller["engineer_id"])
