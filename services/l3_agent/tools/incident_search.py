"""ADK tool: semantic incident search via pgvector cosine similarity.

Unlike ticket search, the business unit filter is OPTIONAL for L3 engineers —
they may legitimately need to search across all BUs when investigating
cross-cutting production issues.
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

_SEARCH_SQL_WITH_BU = """
    SELECT
        jira_id, title, description, root_cause,
        long_term_fix, severity, business_unit,
        resolved_at,
        1 - (embedding <=> $1::vector) AS score
    FROM incidents
    WHERE business_unit = ANY($2)
      AND ($3::text IS NULL OR severity = $3)
    ORDER BY embedding <=> $1::vector
    LIMIT $4
"""

_SEARCH_SQL_ALL_BU = """
    SELECT
        jira_id, title, description, root_cause,
        long_term_fix, severity, business_unit,
        resolved_at,
        1 - (embedding <=> $1::vector) AS score
    FROM incidents
    WHERE ($2::text IS NULL OR severity = $2)
    ORDER BY embedding <=> $1::vector
    LIMIT $3
"""


def _to_vector_str(vector: list[float]) -> str:
    """Format a float list as a pgvector literal ``[v1,v2,...]``."""
    return "[" + ",".join(str(v) for v in vector) + "]"


# ── Tool ───────────────────────────────────────────────────────────────────────


async def search_incidents(
    query_text: str,
    business_units: list[str] | None = None,
    severity_filter: str | None = None,
    top_k: int = 10,
) -> dict:
    """Search historical production incidents and RCAs by semantic similarity.

    Use this tool when an engineer asks about past incidents, outages, or
    production issues. When business_units is None, searches across all BUs.

    Args:
        query_text: Description of the incident or issue to search for.
        business_units: Optional list of BU codes to filter e.g. ['B1', 'B2'].
                        If None, searches all business units.
        severity_filter: Optional severity filter e.g. 'P1', 'P2', 'P3'.
        top_k: Number of results to return (default 10).

    Returns:
        Dictionary with success status and list of matching incidents with scores.
    """
    start = time.time()
    try:
        from services.l3_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        query_vector = await embed_text(query_text)
        vector_str = _to_vector_str(query_vector)

        clamped_top_k = min(max(1, top_k), 50)

        if business_units:
            rows = await pool.fetch(
                _SEARCH_SQL_WITH_BU,
                vector_str,
                business_units,
                severity_filter,
                clamped_top_k,
            )
        else:
            rows = await pool.fetch(
                _SEARCH_SQL_ALL_BU,
                vector_str,
                severity_filter,
                clamped_top_k,
            )

        results = [
            SearchResult(
                jira_id=row["jira_id"],
                title=row["title"],
                summary=row["description"][:200] if row["description"] else None,
                score=float(row["score"]),
                result_type="incident",
                status="Resolved" if row["resolved_at"] else "Open",
                business_unit=row["business_unit"],
                metadata={
                    "root_cause": row["root_cause"],
                    "long_term_fix": row["long_term_fix"],
                    "severity": row["severity"],
                },
            ).model_dump()
            for row in rows
        ]

        latency_ms = round((time.time() - start) * 1000)
        log.info(
            "search_incidents.complete",
            query_length=len(query_text),
            business_units=business_units,
            result_count=len(results),
            latency_ms=latency_ms,
        )

        return ToolResult(success=True, data=results).model_dump()

    except Exception as exc:
        log.error("search_incidents.failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
