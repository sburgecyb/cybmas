"""Shared summarisation skill — used by both L1/L2 and L3 agents.

Calls Gemini via the Vertex AI SDK.  Authentication is automatic from
GOOGLE_APPLICATION_CREDENTIALS (no API key needed).
"""
import asyncio
import json
import os
import sys

import structlog
import vertexai
from dotenv import load_dotenv
from vertexai.generative_models import GenerativeModel

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _ROOT)
from services.shared.models import ChatMessage, SearchResult, ToolResult  # noqa: E402

load_dotenv(os.path.join(_ROOT, ".env.local"))

log = structlog.get_logger()

vertexai.init(
    project=os.getenv("GCP_PROJECT_ID"),
    location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
)
_model = GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))


# ── Helpers ────────────────────────────────────────────────────────────────────


def _format_results(search_results: list[dict]) -> str:
    """Format up to 5 search results into a structured prompt block."""
    lines: list[str] = []
    for i, r in enumerate(search_results[:5], start=1):
        score_pct = round(r.get("score", 0) * 100)
        rt = r.get("result_type", "ticket")
        if rt == "knowledge":
            header = f"[{i}] KNOWLEDGE"
        else:
            ref = r.get("jira_id") or r.get("doc_id") or "?"
            header = f"[{i}] {str(rt).upper()}: {ref}"
        block = [
            header,
            f"    Title: {r.get('title')}",
            f"    Status: {r.get('status', 'Unknown')} | "
            f"BU: {r.get('business_unit', 'Unknown')} | Match: {score_pct}%",
        ]
        if r.get("summary"):
            block.append(f"    Description: {r['summary'][:300]}")
        metadata: dict = r.get("metadata") or {}
        if metadata.get("root_cause"):
            block.append(f"    Root Cause: {metadata['root_cause'][:300]}")
        if metadata.get("long_term_fix"):
            block.append(f"    Long-term Fix: {metadata['long_term_fix'][:300]}")
        if metadata.get("diagnostic_steps"):
            block.append(f"    Diagnostic steps: {str(metadata['diagnostic_steps'])[:400]}")
        if metadata.get("resolution_steps"):
            block.append(f"    Resolution steps: {str(metadata['resolution_steps'])[:400]}")
        if metadata.get("resolution"):
            block.append(f"    Ticket resolution: {str(metadata['resolution'])[:500]}")
        if metadata.get("discussion_preview"):
            block.append(f"    Discussion: {str(metadata['discussion_preview'])[:500]}")
        lines.append("\n".join(block))
    return "\n\n".join(lines)


def _format_context(follow_up_context: list[dict]) -> str:
    """Format the last 3 conversation turns into a prompt snippet."""
    recent = follow_up_context[-3:]
    parts = [
        f"{msg.get('role', 'user').upper()}: {msg.get('content', '')[:200]}"
        for msg in recent
    ]
    return "\n\nRecent conversation context:\n" + "\n".join(parts)


def _parse_response(response_text: str) -> tuple[str, list[str], list[str]]:
    """Extract SUMMARY, KEY POINTS, and SUGGESTED FOLLOW-UPS sections.

    Returns a (summary, key_points, follow_ups) tuple.
    Falls back to the first 500 chars as summary if parsing fails.
    """
    summary_parts: list[str] = []
    key_points: list[str] = []
    follow_ups: list[str] = []
    current_section: str | None = None

    for raw_line in response_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if "SUMMARY:" in upper:
            current_section = "summary"
        elif "KEY POINTS:" in upper:
            current_section = "key_points"
        elif "SUGGESTED FOLLOW" in upper:
            current_section = "follow_ups"
        elif current_section == "summary":
            summary_parts.append(line)
        elif current_section == "key_points" and line.startswith("-"):
            key_points.append(line[1:].strip())
        elif current_section == "follow_ups" and line.startswith("-"):
            follow_ups.append(line[1:].strip())

    summary = " ".join(summary_parts).strip() or response_text[:500]
    return summary, key_points, follow_ups


_PROMPT_TEMPLATE = """\
You are a technical support knowledge assistant helping a support engineer \
find answers in historical tickets and incident reports.

The engineer asked: {question}

Here are the most relevant {result_type} found:

{results}
{context}
Provide a response with these three sections:

SUMMARY:
A clear, direct answer to the engineer's question based on the retrieved \
records. Be specific and technical. Reference ticket/incident IDs directly.
If this is a follow-up question, take the conversation context into account.

KEY POINTS:
- List 3-5 specific actionable findings or resolution steps
- Each point should reference a specific ticket or incident ID
- Focus on what was done to fix the issue

SUGGESTED FOLLOW-UPS:
- List 2-3 follow-up questions the engineer might want to ask next

Keep the response concise and technical. Do not add generic filler text.\
"""

# ── Streaming skill ───────────────────────────────────────────────────────────


async def stream_search_summary(
    original_question: str,
    search_results: list[dict],
    result_type: str = "tickets",
    follow_up_context: list[dict] | None = None,
) -> asyncio.AsyncGenerator[str, None]:  # type: ignore[override]
    """Stream Gemini summary tokens as an async generator.

    Yields raw text chunks as they arrive from the model so the caller can
    forward them to the client immediately, rather than waiting for the full
    response before sending anything.

    Yields an error message string on failure so the caller always receives
    something readable.
    """
    if not search_results:
        yield "No relevant results found for your query. Try rephrasing or selecting a different business unit."
        return

    results_text = _format_results(search_results)
    context_text = _format_context(follow_up_context) if follow_up_context else ""
    prompt = _PROMPT_TEMPLATE.format(
        question=original_question,
        result_type=result_type,
        results=results_text,
        context=context_text,
    )

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _sync_stream() -> None:
        try:
            responses = _model.generate_content(prompt, stream=True)
            for chunk in responses:
                text: str = getattr(chunk, "text", "") or ""
                if text:
                    loop.call_soon_threadsafe(queue.put_nowait, text)
        except Exception as exc:
            log.error("summarize.stream_failed", error=str(exc))
            loop.call_soon_threadsafe(queue.put_nowait, f"\n\n⚠️ Summary error: {exc}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _sync_stream)

    while True:
        token = await queue.get()
        if token is None:
            break
        yield token


# ── Public skill ───────────────────────────────────────────────────────────────


async def summarize_search_results(
    original_question: str,
    search_results: list[dict],
    result_type: str = "tickets",
    follow_up_context: list[dict] | None = None,
) -> dict:
    """Synthesise search results into a clear answer for the engineer.

    Always use this tool after retrieving search results to provide a
    coherent, actionable answer. Do not return raw search results without
    summarising them first.

    Args:
        original_question: The engineer's original question.
        search_results: List of SearchResult dicts from search or rerank tools.
        result_type: Type of results — 'tickets', 'incidents', or 'mixed'.
        follow_up_context: Optional list of prior ChatMessage dicts for context.

    Returns:
        Dictionary with summary text, key_points list and suggested_follow_ups.
    """
    try:
        if not search_results:
            return ToolResult(
                success=True,
                data={
                    "summary": "No relevant results found for your query.",
                    "key_points": [],
                    "suggested_follow_ups": [
                        "Try rephrasing your question",
                        "Check if you have selected the correct business unit",
                        "Try searching with different keywords",
                    ],
                },
            ).model_dump()

        results_text = _format_results(search_results)
        context_text = _format_context(follow_up_context) if follow_up_context else ""

        prompt = _PROMPT_TEMPLATE.format(
            question=original_question,
            result_type=result_type,
            results=results_text,
            context=context_text,
        )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _model.generate_content(prompt),
        )
        response_text = response.text

        summary, key_points, follow_ups = _parse_response(response_text)

        result: dict = {
            "summary": summary,
            "key_points": key_points or ["See retrieved records above"],
            "suggested_follow_ups": follow_ups or [
                "Ask about a specific ticket ID for more details",
                "Ask about the root cause of a specific issue",
            ],
        }

        log.info(
            "summarize.complete",
            question_length=len(original_question),
            result_count=len(search_results),
            summary_length=len(summary),
        )
        return ToolResult(success=True, data=result).model_dump()

    except Exception as exc:
        log.error("summarize.failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
