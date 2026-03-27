"""Orchestrator HTTP service — entry point for the API Gateway.

POST /process  — classifies intent, runs tool chain, streams SSE back:
                 sources event  (search results, sent immediately)
                 token events   (Gemini tokens streamed as they arrive)
                 done event     (session_id)
GET  /health   — liveness probe.

Run with:
    python -m uvicorn server:app --port 8001 --reload
from the services/orchestrator/ directory.
"""
import asyncio
import json
import os
import sys
import uuid as _uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import structlog
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env.local")

from services.orchestrator.intent_classifier import (  # noqa: E402
    JIRA_ID_PATTERN,
    IntentType,
    classify_intent,
)
from services.shared.models import AgentRequest  # noqa: E402

log = structlog.get_logger()

# ── Logging ────────────────────────────────────────────────────────────────────

_log_format = os.getenv("LOG_FORMAT", "console")
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        (
            structlog.processors.JSONRenderer()
            if _log_format == "json"
            else structlog.dev.ConsoleRenderer()
        ),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.l1l2_agent.main import get_db_pool as l1l2_pool
    from services.l3_agent.main import get_db_pool as l3_pool

    await l1l2_pool()
    await l3_pool()
    log.info("orchestrator.started")
    yield
    from services.l1l2_agent.main import close_db_pool as close_l1l2
    from services.l3_agent.main import close_db_pool as close_l3

    await close_l1l2()
    await close_l3()
    log.info("orchestrator.stopped")


app = FastAPI(title="cybmas Orchestrator", lifespan=lifespan)


# ── SSE helpers ────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _format_ticket_detail(d: dict) -> str:
    parts = [
        f"**{d.get('jira_id')}** — {d.get('summary')}",
        f"Status: **{d.get('status', 'Unknown')}** | Priority: {d.get('priority', 'Unknown')}",
    ]
    if d.get("description"):
        parts.append(f"\n{d['description'][:500]}")
    if d.get("resolution"):
        parts.append(f"\n**Resolution:** {d['resolution']}")
    comments: list = d.get("comments") or []
    if comments:
        parts.append("\n**Recent comments:**")
        for c in comments[-3:]:
            parts.append(f"- {c.get('author', 'Unknown')}: {c.get('body', '')[:200]}")
    return "\n".join(parts)


async def _lookup_ticket_in_db(jira_id: str) -> str | None:
    """Fetch a ticket directly from the local database by exact JIRA ID.

    Used as a fallback when the live JIRA API is unavailable (e.g. local dev).
    Returns formatted text or None if the ticket isn't in the DB.
    """
    try:
        from services.l1l2_agent.main import get_db_pool
        pool = await get_db_pool()

        row = await pool.fetchrow(
            """
            SELECT jira_id, summary, description, status, resolution,
                   discussion, ticket_type, business_unit
            FROM tickets
            WHERE jira_id = $1
            """,
            jira_id,
        )
        if not row:
            # Try case-insensitive match (some JIRA IDs may be lower-cased)
            row = await pool.fetchrow(
                "SELECT jira_id, summary, description, status, resolution, "
                "discussion, ticket_type, business_unit "
                "FROM tickets WHERE UPPER(jira_id) = UPPER($1)",
                jira_id,
            )
        if not row:
            return f"Ticket **{jira_id}** was not found in the knowledge base."

        discussion = row["discussion"] or []
        if isinstance(discussion, str):
            import json as _json
            try:
                discussion = _json.loads(discussion)
            except Exception:
                discussion = []

        data = {
            "jira_id":     row["jira_id"],
            "summary":     row["summary"],
            "description": row["description"],
            "status":      row["status"],
            "resolution":  row["resolution"],
            "priority":    row["ticket_type"],   # closest available field
            "assignee":    None,
            "comments":    discussion[:3],
        }
        return _format_ticket_detail(data)

    except Exception as exc:
        log.error("orchestrator.db_lookup_failed", jira_id=jira_id, error=str(exc))
        return None


# ── Response formatter (no LLM — instant) ─────────────────────────────────────


def _format_results_as_text(question: str, results: list[dict], result_type: str) -> str:
    """Build a human-readable response from search results without calling Gemini."""
    if not results:
        return (
            "No relevant results found for your query.\n\n"
            "Suggestions:\n"
            "- Try rephrasing with different keywords\n"
            "- Check that the correct business unit is selected\n"
            "- The issue may not have been recorded previously"
        )

    noun = "incident" if result_type == "incidents" else "ticket"
    plural = "s" if len(results) != 1 else ""
    lines: list[str] = [f"Found **{len(results)} relevant {noun}{plural}**:\n"]

    for i, r in enumerate(results[:5], 1):
        score_pct = round(r.get("score", 0) * 100)
        jira_id = r.get("jira_id", "")
        title = r.get("title") or r.get("summary") or "(no title)"
        status = r.get("status") or "Unknown"
        bu = r.get("business_unit") or "Unknown"

        lines.append(f"**[{i}] {jira_id} — {title}**")
        lines.append(f"Status: `{status}` | BU: `{bu}` | Match: {score_pct}%")

        description = r.get("summary") or ""
        if description and len(description) > 20:
            snippet = description[:300].rstrip()
            if len(description) > 300:
                snippet += "…"
            lines.append(snippet)

        meta: dict = r.get("metadata") or {}
        if meta.get("root_cause"):
            rc = meta["root_cause"][:200]
            lines.append(f"**Root cause:** {rc}")
        if meta.get("long_term_fix"):
            fix = meta["long_term_fix"][:200]
            lines.append(f"**Fix:** {fix}")

        lines.append("")

    lines.append(
        "_Ask about a specific ticket ID (e.g. "
        f'"{results[0].get("jira_id", "B1-1234")}") for full details and resolution steps._'
    )
    return "\n".join(lines)


# ── Session helpers ────────────────────────────────────────────────────────────


async def _load_session_messages(session_id: str) -> list[dict]:
    """Load existing messages for a session from the DB."""
    try:
        from services.l1l2_agent.main import get_db_pool
        pool = await get_db_pool()
        row = await pool.fetchrow(
            "SELECT messages FROM chat_sessions WHERE id = $1",
            _uuid.UUID(session_id),
        )
        if not row or not row["messages"]:
            return []
        raw = row["messages"]
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        log.warning("orchestrator.session_load_failed", error=str(exc))
        return []


async def _save_session(
    session_id: str,
    engineer_id: str,
    user_message: str,
    assistant_response: str,
    prior_messages: list[dict],
) -> None:
    """Persist the chat exchange to chat_sessions table."""
    try:
        from services.l1l2_agent.main import get_db_pool
        pool = await get_db_pool()

        messages = list(prior_messages)
        messages.append({"role": "user", "content": user_message,
                         "timestamp": datetime.now(timezone.utc).isoformat()})
        messages.append({"role": "assistant", "content": assistant_response,
                         "timestamp": datetime.now(timezone.utc).isoformat()})

        title = user_message[:60] + ("…" if len(user_message) > 60 else "")
        now = datetime.now(timezone.utc)

        await pool.execute(
            """
            INSERT INTO chat_sessions
                (id, engineer_id, title, messages, created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $5)
            ON CONFLICT (id) DO UPDATE SET
                messages   = EXCLUDED.messages,
                updated_at = EXCLUDED.updated_at
            """,
            _uuid.UUID(session_id),
            engineer_id,
            title,
            json.dumps(messages),
            now,
        )
        log.info("orchestrator.session_saved", session_id=session_id,
                 message_count=len(messages))
    except Exception as exc:
        log.error("orchestrator.session_save_failed", error=str(exc))


# ── Streaming generator ────────────────────────────────────────────────────────

async def _process_stream(request: AgentRequest) -> AsyncGenerator[str, None]:
    """Full pipeline: classify → search → stream sources → stream Gemini tokens."""
    # Ensure we always have a session ID — generate one for new chats
    session_id = str(request.session_id) if request.session_id else str(_uuid.uuid4())

    # Load prior conversation history from DB (for multi-turn context)
    prior_messages = await _load_session_messages(session_id)
    has_history = bool(prior_messages)

    try:
        intent = await classify_intent(
            message=request.message,
            context_scope=request.context_scope,
            has_conversation_history=has_history,
        )
    except Exception as exc:
        log.error("orchestrator.classify_error", error=str(exc))
        yield _sse({"type": "error", "message": str(exc)})
        return

    log.info("orchestrator.processing", intent=intent.value, engineer_id=request.engineer_id)

    # ── JIRA direct lookup — no AI needed, instant ─────────────────────────────
    if intent in (IntentType.JIRA_LOOKUP, IntentType.STATUS_CHECK):
        match = JIRA_ID_PATTERN.search(request.message)
        if match:
            jira_id = match.group()
            text: str | None = None

            # 1. Look up in the local DB first — instant, always available
            text = await _lookup_ticket_in_db(jira_id)

            # 2. Not in DB yet — try live JIRA API (real-time data, new tickets)
            if not text:
                try:
                    if intent == IntentType.STATUS_CHECK:
                        from services.l1l2_agent.tools.jira_fetch import check_ticket_status
                        result = await check_ticket_status(jira_id)
                        if result.get("success") and result.get("data"):
                            d = result["data"]
                            text = (
                                f"**{d.get('jira_id')}** is currently **{d.get('status')}**\n"
                                f"Assigned to: {d.get('assignee', 'Unassigned')}\n"
                                f"Last updated: {d.get('last_updated', 'Unknown')}"
                            )
                    else:
                        from services.l1l2_agent.tools.jira_fetch import fetch_jira_ticket
                        result = await fetch_jira_ticket(jira_id)
                        if result.get("success") and result.get("data"):
                            text = _format_ticket_detail(result["data"])
                except Exception as exc:
                    log.warning("orchestrator.jira_api_unavailable", jira_id=jira_id, error=str(exc))

            final_text = text or f"Ticket **{jira_id}** not found."
            for line in final_text.split("\n"):
                yield _sse({"type": "token", "content": line + "\n"})
                await asyncio.sleep(0.03)
            asyncio.ensure_future(
                _save_session(session_id, request.engineer_id,
                              request.message, final_text, prior_messages)
            )
            yield _sse({"type": "done", "session_id": session_id})
            return
        # No JIRA ID found in message — fall through to semantic search
        intent = IntentType.TICKET_SEARCH

    # ── Out of scope ───────────────────────────────────────────────────────────
    if intent == IntentType.OUT_OF_SCOPE:
        msg = (
            "I'm a technical support assistant for the Reservations and Payments "
            "platforms. Please ask a support-related question."
        )
        for line in msg.split("\n"):
            yield _sse({"type": "token", "content": line + "\n"})
            await asyncio.sleep(0.03)
        asyncio.ensure_future(
            _save_session(session_id, request.engineer_id,
                          request.message, msg, prior_messages)
        )
        yield _sse({"type": "done", "session_id": session_id})
        return

    # ── Search phase (embedding + DB) ──────────────────────────────────────────
    results: list[dict] = []
    result_type = "tickets"

    try:
        if intent == IntentType.INCIDENT_SEARCH:
            from services.l3_agent.tools.incident_search import search_incidents
            result = await search_incidents(
                query_text=request.message,
                business_units=request.context_scope.business_units,
                top_k=5,
            )
            results = result.get("data", []) if result.get("success") else []
            result_type = "incidents"

        elif intent == IntentType.CROSS_REF:
            match = JIRA_ID_PATTERN.search(request.message)
            if match:
                from services.l3_agent.tools.cross_ref_tickets import cross_reference_tickets_with_incidents
                result = await cross_reference_tickets_with_incidents(match.group())
                results = result.get("data", []) if result.get("success") else []
                result_type = "mixed"
            if not results:
                intent = IntentType.TICKET_SEARCH

        if intent in (IntentType.TICKET_SEARCH, IntentType.FOLLOW_UP) or not results:
            from services.l1l2_agent.tools.vector_search import search_tickets
            from services.l1l2_agent.tools.rerank import rerank_results
            result = await search_tickets(
                query_text=request.message,
                business_units=request.context_scope.business_units,
                top_k=10,
            )
            results = result.get("data", []) if result.get("success") else []
            if results:
                reranked = rerank_results(query_text=request.message, results=results, top_n=5)
                results = reranked.get("data", results) if reranked.get("success") else results
            result_type = "tickets"

    except Exception as exc:
        log.error("orchestrator.search_error", error=str(exc))
        yield _sse({"type": "error", "message": f"Search failed: {exc}"})
        return

    # ── Send sources immediately ───────────────────────────────────────────────
    if results:
        yield _sse({"type": "sources", "sources": results})

    # ── Phase 1: stream formatted results immediately (fast path) ─────────────
    collected: list[str] = []  # accumulate full response for session saving

    response_text = _format_results_as_text(request.message, results, result_type)
    for line in response_text.split("\n"):
        chunk = line + "\n"
        collected.append(chunk)
        yield _sse({"type": "token", "content": chunk})
        await asyncio.sleep(0.03)

    # ── Phase 2: stream Gemini AI summary (appended after results) ─────────────
    # Results are already visible — Gemini tokens are appended progressively.
    # If Gemini fails the user already has the structured results above.
    if results:
        separator = "\n\n---\n### AI Summary\n"
        collected.append(separator)
        for ch in separator:
            yield _sse({"type": "token", "content": ch})
            await asyncio.sleep(0.01)

        try:
            from services.shared.skills.summarize import stream_search_summary
            async for token in stream_search_summary(
                original_question=request.message,
                search_results=results,
                result_type=result_type,
            ):
                collected.append(token)
                yield _sse({"type": "token", "content": token})
        except Exception as exc:
            log.error("orchestrator.summary_stream_error", error=str(exc))
            note = f"\n_(AI summary unavailable: {exc})_"
            collected.append(note)
            yield _sse({"type": "token", "content": note})

    # ── Save session to DB (fire-and-forget, doesn't block the done event) ─────
    full_response = "".join(collected)
    asyncio.ensure_future(
        _save_session(session_id, request.engineer_id,
                      request.message, full_response, prior_messages)
    )

    yield _sse({"type": "done", "session_id": session_id})


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "orchestrator"}


@app.post("/process")
async def process(request: AgentRequest) -> StreamingResponse:
    """Stream SSE: sources → token chunks → done."""
    return StreamingResponse(
        _process_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=int(os.getenv("ORCHESTRATOR_PORT", "8001")),
        reload=True,
    )
