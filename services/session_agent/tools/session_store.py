"""Session store tools — persist and retrieve chat sessions from PostgreSQL."""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.shared.models import ChatSession, SessionSummary, ToolResult  # noqa: E402

log = structlog.get_logger()

# ── SQL ────────────────────────────────────────────────────────────────────────

_UPSERT_SESSION_SQL = """
    INSERT INTO chat_sessions
        (id, engineer_id, title, context_scope, messages, created_at, updated_at)
    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $6)
    ON CONFLICT (id) DO UPDATE SET
        title         = EXCLUDED.title,
        context_scope = EXCLUDED.context_scope,
        messages      = EXCLUDED.messages,
        updated_at    = EXCLUDED.updated_at
"""

_LOAD_SESSION_SQL = """
    SELECT id, engineer_id, title, context_scope, messages, created_at, updated_at
    FROM chat_sessions
    WHERE id = $1
"""

_LIST_SESSIONS_SQL = """
    SELECT id, title, messages, updated_at
    FROM chat_sessions
    WHERE engineer_id = $1
    ORDER BY updated_at DESC
    LIMIT $2
"""

# ── Tools ──────────────────────────────────────────────────────────────────────


async def save_session(
    session_id: str,
    engineer_id: str,
    title: str,
    context_scope: dict,
    messages: list[dict],
) -> dict:
    """Save or update a chat session for an engineer.

    Use this tool to persist conversation history after each message exchange.

    Args:
        session_id: UUID string of the session.
        engineer_id: Email or ID of the engineer.
        title: Short title for the session (first user message truncated to 60 chars).
        context_scope: Dict with business_units list and include_incidents bool.
        messages: Full list of ChatMessage dicts in the conversation.

    Returns:
        Dictionary with success status and session_id.
    """
    try:
        from services.session_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        now = datetime.now(timezone.utc)

        await pool.execute(
            _UPSERT_SESSION_SQL,
            uuid.UUID(session_id),
            engineer_id,
            title,
            json.dumps(context_scope),
            json.dumps(messages, default=str),
            now,
        )

        log.info(
            "session_store.saved",
            session_id=session_id,
            engineer_id=engineer_id,
            message_count=len(messages),
        )
        return ToolResult(success=True, data={"session_id": session_id}).model_dump()

    except Exception as exc:
        log.error("session_store.save_failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()


async def load_session(session_id: str) -> dict:
    """Load a specific chat session by ID.

    Use this tool to resume a previous conversation.

    Args:
        session_id: UUID string of the session to load.

    Returns:
        Dictionary with full session including all messages.
    """
    try:
        from services.session_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        row = await pool.fetchrow(_LOAD_SESSION_SQL, uuid.UUID(session_id))

        if not row:
            return ToolResult(
                success=False,
                error=f"Session {session_id} not found",
            ).model_dump()

        # asyncpg deserialises JSONB columns to Python objects automatically
        result: dict = {
            "id": str(row["id"]),
            "engineer_id": row["engineer_id"],
            "title": row["title"],
            "context_scope": (
                json.loads(row["context_scope"])
                if isinstance(row["context_scope"], str)
                else row["context_scope"] or {}
            ),
            "messages": (
                json.loads(row["messages"])
                if isinstance(row["messages"], str)
                else row["messages"] or []
            ),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

        log.info(
            "session_store.loaded",
            session_id=session_id,
            message_count=len(result["messages"]),
        )
        return ToolResult(success=True, data=result).model_dump()

    except Exception as exc:
        log.error("session_store.load_failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()


async def list_engineer_sessions(engineer_id: str, limit: int = 20) -> dict:
    """List recent chat sessions for an engineer.

    Use this tool to show an engineer their conversation history.

    Args:
        engineer_id: Email or ID of the engineer.
        limit: Maximum number of sessions to return (default 20).

    Returns:
        Dictionary with list of session summaries ordered by most recent first.
    """
    try:
        from services.session_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        rows = await pool.fetch(_LIST_SESSIONS_SQL, engineer_id, limit)

        sessions: list[dict] = []
        for row in rows:
            raw_messages = row["messages"] or "[]"
            messages: list = (
                json.loads(raw_messages)
                if isinstance(raw_messages, str)
                else raw_messages
            )
            last_msg = messages[-1] if messages else None
            preview: str | None = (
                last_msg.get("content", "")[:100] if last_msg else None
            )
            sessions.append(
                {
                    "id": str(row["id"]),
                    "title": row["title"] or "Untitled session",
                    "last_message_preview": preview,
                    "updated_at": str(row["updated_at"]),
                }
            )

        log.info(
            "session_store.listed",
            engineer_id=engineer_id,
            count=len(sessions),
        )
        return ToolResult(success=True, data=sessions).model_dump()

    except Exception as exc:
        log.error("session_store.list_failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
