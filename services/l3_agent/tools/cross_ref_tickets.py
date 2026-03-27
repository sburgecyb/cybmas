"""ADK tool: cross-reference production incidents with their related JIRA tickets.

Two strategies are used in order:
  1. Explicit links — the incident's ``related_tickets`` JSONB field lists known ticket keys.
  2. Semantic fallback — if no explicit links exist, the top-3 most similar tickets
     are found via embedding similarity on the incident title.
"""
import os
import sys

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from pipeline.embedding_worker.embedder import embed_text  # noqa: E402
from services.shared.models import ToolResult  # noqa: E402

log = structlog.get_logger()

# ── SQL ────────────────────────────────────────────────────────────────────────

_FETCH_INCIDENT_SQL = """
    SELECT jira_id, title, related_tickets
    FROM incidents
    WHERE jira_id = $1
"""

_EXPLICIT_TICKETS_SQL = """
    SELECT jira_id, summary, status, business_unit
    FROM tickets
    WHERE jira_id = ANY($1)
      AND business_unit = ANY($2)
"""

_SEMANTIC_TICKETS_SQL = """
    SELECT jira_id, summary, status, business_unit,
           1 - (embedding <=> $1::vector) AS score
    FROM tickets
    WHERE business_unit = ANY($2)
    ORDER BY embedding <=> $1::vector
    LIMIT 3
"""


def _to_vector_str(vector: list[float]) -> str:
    """Format a float list as a pgvector literal ``[v1,v2,...]``."""
    return "[" + ",".join(str(v) for v in vector) + "]"


# ── Tool ───────────────────────────────────────────────────────────────────────


async def cross_reference_tickets_with_incidents(
    incident_ids: list[str],
    business_units: list[str],
) -> dict:
    """Cross-reference incidents with their related JIRA tickets.

    Use this tool when an engineer wants to see which tickets were raised
    during specific incidents, or to find connections between incidents
    and ticket work.

    Args:
        incident_ids: List of incident JIRA IDs to cross-reference.
        business_units: List of BU codes to filter related tickets.

    Returns:
        Dictionary mapping each incident to its linked tickets.
    """
    try:
        from services.l3_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        cross_ref: list[dict] = []

        for incident_id in incident_ids:
            incident = await pool.fetchrow(_FETCH_INCIDENT_SQL, incident_id)

            if not incident:
                log.warning("cross_ref.incident_not_found", incident_id=incident_id)
                continue

            # ── Strategy 1: explicit links from related_tickets JSONB ──────────
            related: list[str] = incident["related_tickets"] or []
            linked_tickets: list[dict] = []

            if related:
                ticket_rows = await pool.fetch(
                    _EXPLICIT_TICKETS_SQL,
                    related,
                    business_units,
                )
                linked_tickets = [
                    {
                        "jira_id": r["jira_id"],
                        "summary": r["summary"],
                        "status": r["status"],
                        "business_unit": r["business_unit"],
                        "link_type": "explicit",
                    }
                    for r in ticket_rows
                ]

            # ── Strategy 2: semantic fallback when no explicit links found ──────
            if not linked_tickets:
                query_vector = await embed_text(incident["title"])
                vector_str = _to_vector_str(query_vector)

                semantic_rows = await pool.fetch(
                    _SEMANTIC_TICKETS_SQL,
                    vector_str,
                    business_units,
                )
                linked_tickets = [
                    {
                        "jira_id": r["jira_id"],
                        "summary": r["summary"],
                        "status": r["status"],
                        "business_unit": r["business_unit"],
                        "link_type": "semantic",
                        "score": float(r["score"]),
                    }
                    for r in semantic_rows
                ]

            cross_ref.append(
                {
                    "incident_id": incident["jira_id"],
                    "incident_title": incident["title"],
                    "linked_tickets": linked_tickets,
                }
            )

        log.info(
            "cross_ref.complete",
            incident_count=len(incident_ids),
            results=len(cross_ref),
        )

        return ToolResult(success=True, data=cross_ref).model_dump()

    except Exception as exc:
        log.error("cross_ref.failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
