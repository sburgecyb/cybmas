"""Embedding Worker — Cloud Run Job entry point.

Modes:
  full   — embed every ticket and incident across all configured projects.
  delta  — embed only issues updated since the last successful run
           (timestamp stored in Redis under ``embedding_worker:last_sync``).

Environment variables (loaded from .env.local for local runs):
  SYNC_MODE, DATABASE_URL, REDIS_URL,
  BU_B1_PROJECTS, BU_B2_PROJECTS, INCIDENT_ISSUE_TYPES
"""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import asyncpg
import redis.asyncio as redis
import structlog
from dotenv import load_dotenv

from embedder import embed_text, shutdown as shutdown_executor
from jira_client import JIRAClient
from processor import normalize_incident, normalize_ticket, prepare_incident_text, prepare_ticket_text
from upsert import upsert_incident, upsert_ticket

load_dotenv(".env.local")

# ── Logging ────────────────────────────────────────────────────────────────────


def _configure_logging() -> None:
    processors: list = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    if os.getenv("LOG_FORMAT", "dev") == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()
log = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

_REDIS_LAST_SYNC_KEY = "embedding_worker:last_sync"
_DEFAULT_DELTA_HOURS = 24


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_bu_project_map() -> dict[str, str]:
    """Parse BU_B1_PROJECTS / BU_B2_PROJECTS env vars into project_key → BU code.

    Returns:
        Dict mapping each project key to its BU code, e.g. ``{"PROJECT_A": "B1"}``.
    """
    mapping: dict[str, str] = {}
    for bu_code in ("B1", "B2"):
        raw = os.getenv(f"BU_{bu_code}_PROJECTS", "")
        for key in raw.split(","):
            key = key.strip()
            if key:
                mapping[key] = bu_code
    return mapping


def _get_incident_issue_types() -> list[str]:
    """Parse INCIDENT_ISSUE_TYPES env var into a list of type strings."""
    raw = os.getenv("INCIDENT_ISSUE_TYPES", "Incident,Production Issue")
    return [t.strip() for t in raw.split(",") if t.strip()]


def _build_asyncpg_url(database_url: str) -> str:
    """Strip the SQLAlchemy driver prefix so asyncpg can use the DSN directly."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def _jql_in_list(values: list[str]) -> str:
    """Format a list of values as a JQL ``in (...)`` expression."""
    quoted = ", ".join(f'"{v}"' for v in values)
    return f"({quoted})"


async def _get_last_sync_time(redis_client: redis.Redis) -> datetime:
    """Read the last sync timestamp from Redis, defaulting to 24 hours ago."""
    raw: bytes | None = await redis_client.get(_REDIS_LAST_SYNC_KEY)
    if raw:
        try:
            return datetime.fromisoformat(raw.decode())
        except ValueError:
            pass
    return datetime.now(timezone.utc) - timedelta(hours=_DEFAULT_DELTA_HOURS)


async def _set_last_sync_time(redis_client: redis.Redis, dt: datetime) -> None:
    await redis_client.set(_REDIS_LAST_SYNC_KEY, dt.isoformat())


# ── Processing helpers ─────────────────────────────────────────────────────────


async def _process_ticket(
    pool: asyncpg.Pool,
    raw_issue: dict,
    bu_code: str,
) -> None:
    ticket = normalize_ticket(raw_issue, bu_code)
    text = prepare_ticket_text(ticket)
    embedding = await embed_text(text)
    await upsert_ticket(pool, ticket, embedding)


async def _process_incident(
    pool: asyncpg.Pool,
    raw_issue: dict,
    bu_code: str,
) -> None:
    incident = normalize_incident(raw_issue, bu_code)
    text = prepare_incident_text(incident)
    embedding = await embed_text(text)
    await upsert_incident(pool, incident, embedding)


# ── Main ───────────────────────────────────────────────────────────────────────


async def main() -> None:
    sync_mode: str = os.getenv("SYNC_MODE", "delta")
    database_url: str = os.environ["DATABASE_URL"]
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")

    bu_project_map = _get_bu_project_map()
    incident_types = _get_incident_issue_types()
    all_project_keys = list(bu_project_map.keys())

    log.info("sync.started", mode=sync_mode, projects=all_project_keys)
    start_ts = time.monotonic()
    total_processed = 0
    errors = 0

    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn=_build_asyncpg_url(database_url),
        min_size=2,
        max_size=5,
    )
    redis_client: redis.Redis = redis.from_url(redis_url, decode_responses=False)

    async with JIRAClient() as jira:
        if sync_mode == "full":
            projects_jql = _jql_in_list(all_project_keys)
            incident_types_jql = _jql_in_list(incident_types)

            # ── Tickets ────────────────────────────────────────────────────────
            ticket_jql = f"project in {projects_jql} ORDER BY created ASC"
            raw_tickets = await jira.get_updated_since(
                since=datetime(2000, 1, 1, tzinfo=timezone.utc),
                project_keys=all_project_keys,
            )
            log.info("sync.tickets_fetched", count=len(raw_tickets))

            for raw in raw_tickets:
                project_key: str = (
                    (raw.get("fields") or {}).get("project", {}).get("key", "")
                )
                bu_code = bu_project_map.get(project_key, "")
                try:
                    await _process_ticket(pool, raw, bu_code)
                    total_processed += 1
                except Exception as exc:
                    errors += 1
                    log.error(
                        "sync.ticket_error",
                        jira_id=raw.get("key"),
                        error=str(exc),
                    )

            # ── Incidents ──────────────────────────────────────────────────────
            incident_jql = (
                f"project in {projects_jql} "
                f"AND issuetype in {incident_types_jql} "
                f"ORDER BY created ASC"
            )
            raw_incidents = await jira.search_tickets(incident_jql, max_results=100)
            incident_issues: list[dict] = raw_incidents.get("issues", [])
            log.info("sync.incidents_fetched", count=len(incident_issues))

            for raw in incident_issues:
                project_key = (
                    (raw.get("fields") or {}).get("project", {}).get("key", "")
                )
                bu_code = bu_project_map.get(project_key, "")
                try:
                    await _process_incident(pool, raw, bu_code)
                    total_processed += 1
                except Exception as exc:
                    errors += 1
                    log.error(
                        "sync.incident_error",
                        jira_id=raw.get("key"),
                        error=str(exc),
                    )

        else:  # delta
            last_sync = await _get_last_sync_time(redis_client)
            log.info("sync.delta_since", since=last_sync.isoformat())

            # ── Tickets ────────────────────────────────────────────────────────
            raw_tickets = await jira.get_updated_since(
                since=last_sync,
                project_keys=all_project_keys,
            )
            log.info("sync.tickets_fetched", count=len(raw_tickets))

            incident_types_set = {t.lower() for t in incident_types}

            for raw in raw_tickets:
                fields: dict = raw.get("fields") or {}
                project_key = (fields.get("project") or {}).get("key", "")
                bu_code = bu_project_map.get(project_key, "")
                issue_type: str = (fields.get("issuetype") or {}).get("name", "")
                is_incident = issue_type.lower() in incident_types_set

                try:
                    if is_incident:
                        await _process_incident(pool, raw, bu_code)
                    else:
                        await _process_ticket(pool, raw, bu_code)
                    total_processed += 1
                except Exception as exc:
                    errors += 1
                    log.error(
                        "sync.issue_error",
                        jira_id=raw.get("key"),
                        is_incident=is_incident,
                        error=str(exc),
                    )

            await _set_last_sync_time(redis_client, datetime.now(timezone.utc))

    duration = time.monotonic() - start_ts
    log.info(
        "sync.completed",
        mode=sync_mode,
        total_processed=total_processed,
        errors=errors,
        duration_seconds=round(duration, 2),
    )

    await pool.close()
    await redis_client.aclose()
    shutdown_executor()


if __name__ == "__main__":
    asyncio.run(main())
