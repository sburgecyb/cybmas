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
      AND ($3::text IS NULL OR ticket_type = $3)
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
        ticket_type_filter: Optional filter by ticket type e.g. 'Bug', 'Incident'.

    Returns:
        Dictionary with success status and list of matching tickets with scores.
    """
    start = time.time()
    try:
        # Lazy import avoids circular dependency — pool lives on the FastAPI app
        from services.l1l2_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        query_vector = await embed_text(query_text)
        vector_str = _to_vector_str(query_vector)

        clamped_top_k = min(max(1, top_k), 50)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _SEARCH_SQL,
                vector_str,
                business_units,
                ticket_type_filter,
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
