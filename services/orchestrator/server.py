"""Orchestrator HTTP service — ADK-driven request handler.

Architecture:
  1. Fast keyword/regex intent classifier (no LLM call) routes to the right agent.
  2. ADK Runner.run_async() drives the chosen specialist agent — Gemini decides
     which tools to call, in what order, and writes the final answer.
  3. Tool responses are intercepted mid-stream to send sources to the browser
     before the final answer arrives.
  4. JIRA ID lookups bypass ADK entirely (instant DB lookup, no value in LLM).

Request timeline (gemini-2.5-flash):
  0 ms   — intent classified (keyword rules)
  ~500ms — ADK: LLM decides to call search_tickets
  ~4s    — search_tickets: embed query (Vertex AI) + pgvector search
  ~500ms — ADK: after search_tickets → sources SSE sent (rerank is inline in search)
  ~1-2s  — ADK: LLM streams final answer tokens
  ~6-7s  — done event

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

from services.shared.google_genai_env import configure_google_genai_for_vertex  # noqa: E402

configure_google_genai_for_vertex()

from services.orchestrator.intent_classifier import (  # noqa: E402
    JIRA_ID_PATTERN,
    IntentType,
    classify_intent,
)
from services.shared.models import AgentRequest, ChatMode  # noqa: E402

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

# ── ADK Runner singletons ──────────────────────────────────────────────────────
# Initialised once at startup; reused for every request.

_adk_session_service = None
_l1l2_runner = None
_l3_runner = None


def _get_adk_session_service():
    global _adk_session_service
    if _adk_session_service is None:
        from google.adk.sessions import InMemorySessionService
        _adk_session_service = InMemorySessionService()
    return _adk_session_service


def _get_l1l2_runner():
    global _l1l2_runner
    if _l1l2_runner is None:
        from google.adk.runners import Runner
        from services.l1l2_agent.agent import agent as l1l2_agent
        _l1l2_runner = Runner(
            agent=l1l2_agent,
            app_name="cybmas",
            session_service=_get_adk_session_service(),
        )
        log.info("adk.l1l2_runner_created")
    return _l1l2_runner


def _get_l3_runner():
    global _l3_runner
    if _l3_runner is None:
        from google.adk.runners import Runner
        from services.l3_agent.agent import agent as l3_agent
        _l3_runner = Runner(
            agent=l3_agent,
            app_name="cybmas",
            session_service=_get_adk_session_service(),
        )
        log.info("adk.l3_runner_created")
    return _l3_runner


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up DB pools
    from services.l1l2_agent.main import get_db_pool as l1l2_pool
    from services.l3_agent.main import get_db_pool as l3_pool
    await l1l2_pool()
    await l3_pool()

    # Warm up ADK runners (loads agent modules + initialises Vertex AI)
    _get_l1l2_runner()
    _get_l3_runner()

    log.info("orchestrator.started", mode="adk")
    yield

    from services.l1l2_agent.main import close_db_pool as close_l1l2
    from services.l3_agent.main import close_db_pool as close_l3
    await close_l1l2()
    await close_l3()
    log.info("orchestrator.stopped")


app = FastAPI(title="cybmas Orchestrator", lifespan=lifespan)


# ── SSE helper ─────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _coerce_mapping(obj: object) -> dict:
    """Turn tool response payloads into a plain dict (ADK / genai types vary)."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    md = getattr(obj, "model_dump", None)
    if callable(md):
        try:
            return md()
        except Exception:
            pass
    try:
        return dict(obj)  # type: ignore[arg-type]
    except Exception:
        return {}


def _extract_search_tool_payload(fn_resp) -> list | None:
    """Return result rows from search_tickets / search_incidents, or None."""
    raw = _coerce_mapping(getattr(fn_resp, "response", None))
    if raw.get("success") is False:
        return None
    data = raw.get("data")
    if isinstance(data, list) and len(data) > 0:
        return data
    return None


# ── Ticket detail formatter (JIRA lookup path — no ADK) ───────────────────────

def _format_ticket_detail(d: dict) -> str:
    parts = [
        f"**{d.get('jira_id')}** — {d.get('summary')}",
        f"Status: **{d.get('status', 'Unknown')}** | Type: {d.get('priority', 'Unknown')}",
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
    """Direct DB lookup by JIRA ID — instant, no LLM needed."""
    try:
        from services.l1l2_agent.main import get_db_pool
        pool = await get_db_pool()
        row = await pool.fetchrow(
            """SELECT jira_id, summary, description, status, resolution,
                      discussion, ticket_type, business_unit
               FROM tickets WHERE jira_id = $1""",
            jira_id,
        )
        if not row:
            row = await pool.fetchrow(
                "SELECT jira_id, summary, description, status, resolution, "
                "discussion, ticket_type, business_unit "
                "FROM tickets WHERE UPPER(jira_id) = UPPER($1)",
                jira_id,
            )
        if not row:
            return None

        discussion = row["discussion"] or []
        if isinstance(discussion, str):
            try:
                discussion = json.loads(discussion)
            except Exception:
                discussion = []

        return _format_ticket_detail({
            "jira_id":     row["jira_id"],
            "summary":     row["summary"],
            "description": row["description"],
            "status":      row["status"],
            "resolution":  row["resolution"],
            "priority":    row["ticket_type"],
            "assignee":    None,
            "comments":    discussion[:3],
        })
    except Exception as exc:
        log.error("orchestrator.db_lookup_failed", jira_id=jira_id, error=str(exc))
        return None


# ── Session helpers ────────────────────────────────────────────────────────────

async def _load_session_messages(session_id: str) -> list[dict]:
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
            """INSERT INTO chat_sessions
                   (id, engineer_id, title, messages, created_at, updated_at)
               VALUES ($1, $2, $3, $4::jsonb, $5, $5)
               ON CONFLICT (id) DO UPDATE SET
                   messages = EXCLUDED.messages, updated_at = EXCLUDED.updated_at""",
            _uuid.UUID(session_id), engineer_id, title, json.dumps(messages), now,
        )
        log.info("orchestrator.session_saved", session_id=session_id,
                 message_count=len(messages))
    except Exception as exc:
        log.error("orchestrator.session_save_failed", error=str(exc))


# ── ADK streaming helper ───────────────────────────────────────────────────────

async def _run_adk_agent(
    runner,
    engineer_id: str,
    session_id: str,
    message: str,
    prior_messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Run an ADK agent and yield SSE events.

    - Intercepts tool function_response events to send "sources" SSE as soon
      as the search tool completes (before the final answer is ready).
    - Streams the final LLM answer (SSE mode: incremental chunks; no artificial delay).
    - Collects the full response for session persistence.
    """
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part

    session_svc: InMemorySessionService = _get_adk_session_service()

    # Ensure the ADK in-memory session exists for conversation continuity.
    # In ADK 1.27.5 both get_session and create_session are async coroutines.
    existing = await session_svc.get_session(
        app_name="cybmas", user_id=engineer_id, session_id=session_id
    )
    if not existing:
        await session_svc.create_session(
            app_name="cybmas", user_id=engineer_id, session_id=session_id
        )

    partial_chunks: list[str] = []
    final_answer: str | None = None
    sources_sent = False
    error_suffix = ""

    try:
        async for event in runner.run_async(
            user_id=engineer_id,
            session_id=session_id,
            new_message=Content(role="user", parts=[Part(text=message)]),
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            # ── Intercept tool responses to send sources immediately ───────────
            # ADK emits an event with function_response parts when a tool result
            # is about to be fed back to the LLM. We extract search results here
            # so the browser's sources panel populates before the answer arrives.
            if not sources_sent and event.content and event.content.parts:
                for part in event.content.parts:
                    fn_resp = getattr(part, "function_response", None)
                    if fn_resp and fn_resp.name in ("search_tickets", "search_incidents"):
                        results = _extract_search_tool_payload(fn_resp)
                        if results:
                            yield _sse({"type": "sources", "sources": results})
                            sources_sent = True
                            log.info("adk.sources_sent", count=len(results),
                                     tool=fn_resp.name)

            # Alternate shape: some ADK events expose responses only via helper.
            if not sources_sent:
                get_fn = getattr(event, "get_function_responses", None)
                if callable(get_fn):
                    for fn_resp in get_fn():
                        if fn_resp.name in ("search_tickets", "search_incidents"):
                            results = _extract_search_tool_payload(fn_resp)
                            if results:
                                yield _sse({"type": "sources", "sources": results})
                                sources_sent = True
                                log.info(
                                    "adk.sources_sent",
                                    count=len(results),
                                    tool=fn_resp.name,
                                    via="get_function_responses",
                                )
                                break

            # ── Stream model text (SSE: partial chunks; final = full snapshot) ─
            if not event.content or not event.content.parts:
                continue
            for part in event.content.parts:
                if getattr(part, "function_call", None) or getattr(
                    part, "function_response", None
                ):
                    continue
                text = getattr(part, "text", None) or ""
                if not text:
                    continue
                if event.partial:
                    partial_chunks.append(text)
                    yield _sse({"type": "token", "content": text})
                elif event.is_final_response():
                    final_answer = text
                    # If nothing was streamed incrementally, send the full answer once.
                    if not partial_chunks:
                        yield _sse({"type": "token", "content": text})

    except Exception as exc:
        log.error("adk.runner_error", error=str(exc))
        err = f"\n⚠️ Agent error: {exc}"
        error_suffix = err
        yield _sse({"type": "token", "content": err})

    saved_text = (
        final_answer
        if final_answer is not None
        else "".join(partial_chunks)
    ) + error_suffix
    # Return the collected text via a special internal event so the caller
    # can save the session without a second pass through the generator.
    yield _sse({"type": "_collected", "text": saved_text})


# ── Main streaming generator ───────────────────────────────────────────────────

async def _process_stream(request: AgentRequest) -> AsyncGenerator[str, None]:
    """Full pipeline: classify → (DB lookup | ADK agent) → SSE stream."""
    session_id = str(request.session_id) if request.session_id else str(_uuid.uuid4())
    prior_messages = await _load_session_messages(session_id)
    has_history = bool(prior_messages)

    # ── Non-support modes: other agents are wired later; keep BU/incident UI unchanged
    if request.chat_mode != ChatMode.support_engineer:
        log.info(
            "orchestrator.chat_mode_placeholder",
            chat_mode=request.chat_mode.value,
            engineer_id=request.engineer_id,
        )
        msg = (
            f"This workspace mode is not available yet "
            f"({request.chat_mode.value.replace('_', ' ')}). "
            "Select **Support Engineer** in the chat mode menu for L1/L2/L3 ticket "
            "search, incident KB, and JIRA tools."
        )
        yield _sse({"type": "token", "content": msg})
        asyncio.ensure_future(
            _save_session(
                session_id, request.engineer_id,
                request.message, msg, prior_messages,
            )
        )
        yield _sse({"type": "done", "session_id": session_id})
        return

    # ── Step 1: fast intent classification (no LLM, ~0 ms) ───────────────────
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

    log.info("orchestrator.intent", intent=intent.value,
             engineer_id=request.engineer_id)

    # ── Step 2: JIRA direct lookup — instant, no ADK needed ───────────────────
    if intent in (IntentType.JIRA_LOOKUP, IntentType.STATUS_CHECK):
        match = JIRA_ID_PATTERN.search(request.message)
        if match:
            jira_id = match.group()
            text = await _lookup_ticket_in_db(jira_id)

            if not text:  # not in DB — try live JIRA API
                try:
                    if intent == IntentType.STATUS_CHECK:
                        from services.l1l2_agent.tools.jira_fetch import check_ticket_status
                        r = await check_ticket_status(jira_id)
                        if r.get("success") and r.get("data"):
                            d = r["data"]
                            text = (
                                f"**{d.get('jira_id')}** is currently **{d.get('status')}**\n"
                                f"Assigned to: {d.get('assignee', 'Unassigned')}\n"
                                f"Last updated: {d.get('last_updated', 'Unknown')}"
                            )
                    else:
                        from services.l1l2_agent.tools.jira_fetch import fetch_jira_ticket
                        r = await fetch_jira_ticket(jira_id)
                        if r.get("success") and r.get("data"):
                            text = _format_ticket_detail(r["data"])
                except Exception as exc:
                    log.warning("orchestrator.jira_api_unavailable",
                                jira_id=jira_id, error=str(exc))

            final_text = text or f"Ticket **{jira_id}** not found in the knowledge base."
            yield _sse({"type": "token", "content": final_text})
            asyncio.ensure_future(
                _save_session(session_id, request.engineer_id,
                              request.message, final_text, prior_messages)
            )
            yield _sse({"type": "done", "session_id": session_id})
            return
        intent = IntentType.TICKET_SEARCH  # no ID found, fall to search

    # ── Step 3: out of scope ───────────────────────────────────────────────────
    if intent == IntentType.OUT_OF_SCOPE:
        msg = ("I'm a technical support assistant for the Reservations and "
               "Payments platforms. Please ask a support-related question.")
        yield _sse({"type": "token", "content": msg})
        asyncio.ensure_future(
            _save_session(session_id, request.engineer_id,
                          request.message, msg, prior_messages)
        )
        yield _sse({"type": "done", "session_id": session_id})
        return

    # ── Step 4: ADK agent execution ───────────────────────────────────────────
    # Pick the right specialist agent based on intent, then let ADK drive
    # tool selection, execution order, and final answer generation.
    runner = _get_l3_runner() if intent == IntentType.INCIDENT_SEARCH else _get_l1l2_runner()

    # Augment the message with business unit context so the agent knows
    # which BUs to pass to search_tickets / search_incidents.
    bus = ", ".join(request.context_scope.business_units)
    adk_message = (
        f"{request.message}\n\n"
        f"[Context]\n"
        f"Business units in scope: {bus}\n"
        f"Include incidents: {request.context_scope.include_incidents}"
    )

    collected_text = ""
    async for sse_line in _run_adk_agent(
        runner, request.engineer_id, session_id, adk_message, prior_messages
    ):
        # Intercept the internal _collected event — don't forward to browser
        try:
            payload = json.loads(sse_line.removeprefix("data: ").strip())
            if payload.get("type") == "_collected":
                collected_text = payload.get("text", "")
                continue
        except Exception:
            pass
        yield sse_line

    asyncio.ensure_future(
        _save_session(session_id, request.engineer_id,
                      request.message, collected_text, prior_messages)
    )
    yield _sse({"type": "done", "session_id": session_id})


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "orchestrator", "mode": "adk"}


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
