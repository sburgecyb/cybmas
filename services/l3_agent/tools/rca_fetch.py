"""ADK tool: fetch the full Root Cause Analysis for a specific incident."""
import os
import sys

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.shared.models import ToolResult  # noqa: E402

log = structlog.get_logger()


async def fetch_incident_rca(incident_jira_id: str) -> dict:
    """Fetch the full Root Cause Analysis for a specific incident.

    Use this tool when an engineer wants to understand what caused an incident
    or what the long-term fix was. Requires a specific incident ID.

    Args:
        incident_jira_id: The JIRA ID of the incident e.g. 'INC-001' or 'B2-2004'.

    Returns:
        Dictionary with full RCA details including root_cause, long_term_fix,
        severity, related_tickets and timeline.
    """
    try:
        from services.l3_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()

        row = await pool.fetchrow(
            """
            SELECT jira_id, title, description, root_cause, long_term_fix,
                   related_tickets, severity, resolved_at, created_at,
                   business_unit
            FROM incidents
            WHERE jira_id = $1
            """,
            incident_jira_id,
        )

        if not row:
            return ToolResult(
                success=False,
                error=f"Incident {incident_jira_id} not found in knowledge base",
            ).model_dump()

        result: dict = {
            "jira_id": row["jira_id"],
            "title": row["title"],
            "description": row["description"],
            "root_cause": row["root_cause"] or "RCA not yet documented",
            "long_term_fix": row["long_term_fix"] or "Long-term fix not yet documented",
            "related_tickets": row["related_tickets"] or [],
            "severity": row["severity"],
            "business_unit": row["business_unit"],
            "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
            "created_at": str(row["created_at"]) if row["created_at"] else None,
        }

        log.info("rca_fetch.success", jira_id=incident_jira_id)
        return ToolResult(success=True, data=result).model_dump()

    except Exception as exc:
        log.error("rca_fetch.failed", jira_id=incident_jira_id, error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
