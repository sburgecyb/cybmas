"""ADK tool: semantic ticket search via pgvector cosine similarity.

The query is embedded with Vertex AI text-embedding-004 (768-dim) and compared
against all ticket embeddings using the <=> (cosine distance) operator.
Business unit scoping is ALWAYS applied — see .cursorrules constraint.
"""
import os
import sys
import time

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from pipeline.embedding_worker.embedder import embed_text  # noqa: E402
from services.l1l2_agent.tools.rerank import apply_keyword_rerank  # noqa: E402
from services.shared.models import SearchResult, ToolResult  # noqa: E402

log = structlog.get_logger()

# ── SQL ────────────────────────────────────────────────────────────────────────

_SEARCH_SQL = """
    SELECT
        jira_id,
        summary,
        description,
        resolution,
        status,
        business_unit,
        ticket_type,
        1 - (embedding <=> $1::vector) AS score
    FROM tickets
    WHERE business_unit = ANY($2)
      AND (
          $3::text IS NULL
          OR UPPER(TRIM(ticket_type)) = UPPER(TRIM($3::text))
      )
    ORDER BY embedding <=> $1::vector
    LIMIT $4
"""


def _to_vector_str(vector: list[float]) -> str:
    """Format a float list as a pgvector literal ``[v1,v2,...]``."""
    return "[" + ",".join(str(v) for v in vector) + "]"


# ── Tool ───────────────────────────────────────────────────────────────────────


async def search_tickets(
    query_text: str,
    business_units: list[str],
    top_k: int = 10,
    ticket_type_filter: str | None = None,
) -> dict:
    """Search historical support tickets by semantic similarity.

    Use this tool when an engineer describes a problem and needs to find
    similar past tickets. Always provide business_units to scope the search.

    Args:
        query_text: Description of the problem to search for.
        business_units: List of business unit codes to search within e.g. ['B1', 'B2'].
        top_k: Number of results to return (default 10, max 50).
        ticket_type_filter: Only set when the user explicitly asks to limit by
            Jira type (Bug, Incident, Task, Story). Omit for general questions
            ("refund issues", "login problems") — those words are not a type filter.
            Matching is case-insensitive (Bug vs BUG).

    Returns:
        Dictionary with success status and list of matching tickets with scores
        (vector similarity plus in-process keyword / status reranking).
    """
    start = time.time()
    try:
        # Lazy import avoids circular dependency — pool lives on the FastAPI app
        from services.l1l2_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        query_vector = await embed_text(query_text)
        vector_str = _to_vector_str(query_vector)

        clamped_top_k = min(max(1, top_k), 50)
        type_filter = (ticket_type_filter.strip() if ticket_type_filter else None) or None

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _SEARCH_SQL,
                vector_str,
                business_units,
                type_filter,
                clamped_top_k,
            )
            # Model often passes a type filter for vague "issues" queries; if
            # nothing matches, retry once without a type filter.
            if not rows and type_filter:
                log.warning(
                    "search_tickets.retry_without_type_filter",
                    dropped_filter=type_filter,
                )
                rows = await conn.fetch(
                    _SEARCH_SQL,
                    vector_str,
                    business_units,
                    None,
                    clamped_top_k,
                )

        results = [
            SearchResult(
                jira_id=row["jira_id"],
                title=row["summary"],
                summary=row["description"][:200] if row["description"] else None,
                score=float(row["score"]),
                result_type="ticket",
                status=row["status"],
                business_unit=row["business_unit"],
                metadata={"ticket_type": row["ticket_type"]},
            ).model_dump()
            for row in rows
        ]

        # Keyword rerank in-process (avoids a separate Gemini tool round-trip).
        results = apply_keyword_rerank(query_text, results, top_n=clamped_top_k)

        latency_ms = round((time.time() - start) * 1000)
        log.info(
            "search_tickets.complete",
            query_length=len(query_text),
            business_units=business_units,
            result_count=len(results),
            latency_ms=latency_ms,
        )

        return ToolResult(success=True, data=results).model_dump()

    except Exception as exc:
        log.error("search_tickets.failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
