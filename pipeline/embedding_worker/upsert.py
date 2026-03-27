"""pgvector upsert operations for tickets and incidents.

asyncpg does not natively understand the pgvector ``vector`` type, so
embeddings are formatted as PostgreSQL array-literal strings and cast
with ``::vector`` inside the SQL statement.

JSONB columns are serialised with ``json.dumps`` and cast with ``::jsonb``.
Timestamps from JIRA ISO strings are parsed to timezone-aware datetimes
so asyncpg can bind them natively.
"""
import json
from datetime import datetime, timezone

import asyncpg
import structlog

log = structlog.get_logger()

# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_vector_str(embedding: list[float]) -> str:
    """Format a float list as a pgvector literal, e.g. ``[0.1,0.2,...]``."""
    return "[" + ",".join(str(v) for v in embedding) + "]"


def _to_json(value: object) -> str | None:
    """Serialise a value to a JSON string for asyncpg JSONB binding.

    Returns None if the value is None so the column stores SQL NULL.
    """
    if value is None:
        return None
    return json.dumps(value, default=str)


def _parse_dt(value: "str | datetime | None") -> datetime | None:
    """Parse a JIRA ISO-8601 timestamp string to a timezone-aware datetime.

    Handles JIRA's ``+0000`` suffix (no colon) which ``fromisoformat``
    requires as ``+00:00`` on Python < 3.11.

    Args:
        value: ISO timestamp string, an existing datetime, or None.

    Returns:
        UTC-aware datetime, or None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    normalised = value.replace("+0000", "+00:00")
    try:
        return datetime.fromisoformat(normalised)
    except ValueError:
        return None


# ── Upserts ────────────────────────────────────────────────────────────────────

_UPSERT_TICKET_SQL = """
INSERT INTO tickets (
    jira_id, business_unit, ticket_type, summary, description,
    status, resolution, discussion, created_at, updated_at,
    embedding, raw_json
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8::jsonb, $9, $10,
    $11::vector, $12::jsonb
)
ON CONFLICT (jira_id) DO UPDATE SET
    business_unit = EXCLUDED.business_unit,
    ticket_type   = EXCLUDED.ticket_type,
    summary       = EXCLUDED.summary,
    description   = EXCLUDED.description,
    status        = EXCLUDED.status,
    resolution    = EXCLUDED.resolution,
    discussion    = EXCLUDED.discussion,
    created_at    = EXCLUDED.created_at,
    updated_at    = EXCLUDED.updated_at,
    embedding     = EXCLUDED.embedding,
    raw_json      = EXCLUDED.raw_json
"""

_UPSERT_INCIDENT_SQL = """
INSERT INTO incidents (
    jira_id, business_unit, title, description, root_cause,
    long_term_fix, related_tickets, severity,
    resolved_at, created_at, updated_at,
    embedding, raw_json
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7::jsonb, $8,
    $9, $10, $11,
    $12::vector, $13::jsonb
)
ON CONFLICT (jira_id) DO UPDATE SET
    business_unit   = EXCLUDED.business_unit,
    title           = EXCLUDED.title,
    description     = EXCLUDED.description,
    root_cause      = EXCLUDED.root_cause,
    long_term_fix   = EXCLUDED.long_term_fix,
    related_tickets = EXCLUDED.related_tickets,
    severity        = EXCLUDED.severity,
    resolved_at     = EXCLUDED.resolved_at,
    created_at      = EXCLUDED.created_at,
    updated_at      = EXCLUDED.updated_at,
    embedding       = EXCLUDED.embedding,
    raw_json        = EXCLUDED.raw_json
"""


async def upsert_ticket(
    pool: asyncpg.Pool,
    ticket_data: dict,
    embedding: list[float],
) -> None:
    """Insert or update a ticket row including its embedding vector.

    Args:
        pool: Active asyncpg connection pool.
        ticket_data: Normalised ticket dict (output of ``processor.normalize_ticket``).
        embedding: 768-dimensional embedding vector.
    """
    jira_id: str = ticket_data["jira_id"]

    async with pool.acquire() as conn:
        await conn.execute(
            _UPSERT_TICKET_SQL,
            jira_id,
            ticket_data.get("business_unit"),
            ticket_data.get("ticket_type"),
            ticket_data.get("summary", ""),
            ticket_data.get("description"),
            ticket_data.get("status"),
            ticket_data.get("resolution"),
            _to_json(ticket_data.get("discussion")),
            _parse_dt(ticket_data.get("created_at")),
            _parse_dt(ticket_data.get("updated_at")),
            _to_vector_str(embedding),
            _to_json(ticket_data.get("raw_json")),
        )

    log.info("upsert.ticket_upserted", jira_id=jira_id)


async def upsert_incident(
    pool: asyncpg.Pool,
    incident_data: dict,
    embedding: list[float],
) -> None:
    """Insert or update an incident row including its embedding vector.

    Args:
        pool: Active asyncpg connection pool.
        incident_data: Normalised incident dict (output of ``processor.normalize_incident``).
        embedding: 768-dimensional embedding vector.
    """
    jira_id: str = incident_data["jira_id"]

    async with pool.acquire() as conn:
        await conn.execute(
            _UPSERT_INCIDENT_SQL,
            jira_id,
            incident_data.get("business_unit"),
            incident_data.get("title", ""),
            incident_data.get("description"),
            incident_data.get("root_cause"),
            incident_data.get("long_term_fix"),
            _to_json(incident_data.get("related_tickets")),
            incident_data.get("severity"),
            _parse_dt(incident_data.get("resolved_at")),
            _parse_dt(incident_data.get("created_at")),
            _parse_dt(incident_data.get("updated_at")),
            _to_vector_str(embedding),
            _to_json(incident_data.get("raw_json")),
        )

    log.info("upsert.incident_upserted", jira_id=jira_id)
