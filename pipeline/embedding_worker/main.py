"""Embedding Worker — Cloud Run Job entry point.

Modes:
  full   — embed every ticket and incident across all configured projects.
  delta  — embed only issues updated since the last successful run
           (timestamp stored in Redis under ``embedding_worker:last_sync``).

Environment variables (loaded from .env.local for local runs):
  SYNC_MODE, DATABASE_URL, REDIS_URL,
  JIRA_PROJECT_KEYS (optional — if unset/empty, sync **all** projects the user can see),
  BU_B1_PROJECTS, BU_B2_PROJECTS (optional project→BU map only; does **not** limit scope),
  JIRA_BUSINESS_UNIT_FIELD_ID (optional custom field, e.g. customfield_10001),
  DEFAULT_BUSINESS_UNIT (optional override before literal Default), INCIDENT_ISSUE_TYPES

  Business unit on each row (never NULL): see ``_resolve_business_unit``.
"""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import redis.asyncio as redis
import structlog
from dotenv import load_dotenv

from embedder import embed_text, shutdown as shutdown_executor
from jira_client import JIRAClient
from processor import normalize_incident, normalize_ticket, prepare_incident_text, prepare_ticket_text
from upsert import upsert_incident, upsert_ticket

# Repo-root .env.local first so `python pipeline/embedding_worker/main.py` works from cybmas root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env.local")
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


def _env_clean(value: str | None) -> str:
    """Strip whitespace and BOM — Secret Manager / .env values often trail ``\\n``."""
    return (value or "").strip().strip("\ufeff")


def _redis_url() -> str:
    """Resolve Redis URL; treat blank env as unset so the localhost default applies."""
    cleaned = _env_clean(os.getenv("REDIS_URL"))
    return cleaned or "redis://127.0.0.1:6379"


def _redis_target_for_log(url: str) -> str:
    """Host/port/db for logs — avoids printing credentials from the URL."""
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    port = f":{parsed.port}" if parsed.port else ""
    db = parsed.path or ""
    return f"{host}{port}{db}"


def _sync_mode() -> str:
    return (_env_clean(os.getenv("SYNC_MODE")) or "delta").lower()


def _parse_stored_sync_time(raw: bytes | str) -> datetime | None:
    """Parse ISO datetime from Redis; return None if invalid."""
    if isinstance(raw, bytes):
        try:
            s = raw.decode()
        except UnicodeError:
            return None
    else:
        s = raw
    s = s.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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


def _parse_project_key_list(raw: str) -> list[str]:
    """Split a comma-separated list of JIRA project keys."""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _get_sync_project_keys() -> list[str]:
    """Project keys to scope JQL (``project in (...)``).

    If ``JIRA_PROJECT_KEYS`` is set and non-empty, only those projects are queried.
    If unset or empty, returns ``[]`` → **no** ``project in`` clause: all issues
    across **all** projects the JIRA user can browse.

    ``BU_B1_PROJECTS`` / ``BU_B2_PROJECTS`` do **not** limit scope; they only
    assign ``business_unit`` per project key (see ``_resolve_business_unit``).

    Returns:
        Sorted list of unique project keys, or ``[]`` for site-wide scope.
    """
    explicit = _parse_project_key_list(os.getenv("JIRA_PROJECT_KEYS", ""))
    return sorted(set(explicit)) if explicit else []


def _business_unit_from_jira_field(fields: dict) -> str | None:
    """If ``JIRA_BUSINESS_UNIT_FIELD_ID`` is set, return BU string from that field, else None."""
    fid = (os.getenv("JIRA_BUSINESS_UNIT_FIELD_ID") or "").strip()
    if not fid:
        return None
    raw = fields.get(fid)
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return s or None
    if isinstance(raw, dict):
        for k in ("value", "name", "key"):
            v = raw.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            for k in ("value", "name", "key"):
                v = first.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
        elif isinstance(first, str) and first.strip():
            return first.strip()
    return None


def _resolve_business_unit(raw_issue: dict, bu_project_map: dict[str, str]) -> str:
    """Resolve ``business_unit`` for DB (always non-empty — FK to ``business_units``).

    BU is **not** required from JIRA or from env: every issue gets a code.

    Precedence (first hit wins):

    1. **JIRA custom field** — if ``JIRA_BUSINESS_UNIT_FIELD_ID`` is set (e.g.
       ``customfield_10100``) and the issue has a non-empty value (string,
       select object, or first list item). Value must match a row in
       ``business_units`` or upsert will fail FK.
    2. **Project map** — ``BU_B1_PROJECTS`` / ``BU_B2_PROJECTS``: if ``project.key``
       is listed, use **B1** / **B2**. Does not limit which issues are synced.
       (If the project is not in the map, use steps 3 / 4.)
    3. **``DEFAULT_BUSINESS_UNIT``** env — if set and non-empty after strip.
    4. **Literal ``Default``** — must exist in ``business_units`` (migration 004).

    Missing or unknown ``project.key`` skips step 2 and uses 3 → 4.
    """
    fields: dict = raw_issue.get("fields") or {}

    from_jira = _business_unit_from_jira_field(fields)
    if from_jira:
        return from_jira

    project_key = ((fields.get("project") or {}).get("key") or "").strip()
    if project_key:
        mapped = bu_project_map.get(project_key)
        if mapped:
            return mapped

    override = (os.getenv("DEFAULT_BUSINESS_UNIT") or "").strip()
    return override or "Default"


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
    raw = await redis_client.get(_REDIS_LAST_SYNC_KEY)
    if raw is None:
        fallback = datetime.now(timezone.utc) - timedelta(hours=_DEFAULT_DELTA_HOURS)
        log.warning(
            "sync.redis_last_sync_miss",
            key=_REDIS_LAST_SYNC_KEY,
            fallback_since=fallback.isoformat(),
            hint="No watermark in Redis — using rolling 24h window. "
            "Confirm REDIS_URL points to one shared instance across runs.",
        )
        return fallback

    parsed = _parse_stored_sync_time(raw)
    if parsed is not None:
        log.info("sync.redis_last_sync_hit", since=parsed.isoformat())
        return parsed

    preview = raw if isinstance(raw, str) else raw[:200]
    fallback = datetime.now(timezone.utc) - timedelta(hours=_DEFAULT_DELTA_HOURS)
    log.warning(
        "sync.redis_last_sync_unparseable",
        key=_REDIS_LAST_SYNC_KEY,
        raw_preview=repr(preview),
        fallback_since=fallback.isoformat(),
    )
    return fallback


async def _set_last_sync_time(redis_client: redis.Redis, dt: datetime) -> None:
    await redis_client.set(_REDIS_LAST_SYNC_KEY, dt.isoformat())
    log.info("sync.redis_last_sync_saved", since=dt.isoformat())


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


async def _try_sync_issue(
    pool: asyncpg.Pool,
    raw: dict,
    *,
    kind: str,
    bu_code: str,
) -> bool:
    """Run ticket or incident pipeline; log begin / success / failure. Returns True if synced."""
    jira_id: str = raw.get("key") or "?"
    fields: dict = raw.get("fields") or {}
    summary: str = (fields.get("summary") or "")[:160]
    issue_type: str = (fields.get("issuetype") or {}).get("name", "")

    log.info(
        "sync.issue_begin",
        jira_id=jira_id,
        kind=kind,
        business_unit=bu_code,
        issue_type=issue_type,
        summary_preview=summary,
    )
    try:
        if kind == "incident":
            await _process_incident(pool, raw, bu_code)
        else:
            await _process_ticket(pool, raw, bu_code)
    except Exception as exc:
        log.error(
            "sync.issue_failed",
            jira_id=jira_id,
            kind=kind,
            business_unit=bu_code,
            issue_type=issue_type,
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return False

    log.info(
        "sync.issue_synced",
        jira_id=jira_id,
        kind=kind,
        business_unit=bu_code,
        issue_type=issue_type,
    )
    return True


async def _log_table_counts(pool: asyncpg.Pool) -> None:
    """After sync, log row counts so Cloud Logging / local runs show DB state."""
    try:
        async with pool.acquire() as conn:
            tickets_n: int = await conn.fetchval("SELECT COUNT(*) FROM tickets") or 0
            incidents_n: int = await conn.fetchval("SELECT COUNT(*) FROM incidents") or 0
        log.info(
            "sync.db_counts",
            tickets_table_rows=int(tickets_n),
            incidents_table_rows=int(incidents_n),
        )
    except Exception as exc:
        log.warning("sync.db_counts_failed", error=str(exc), error_type=type(exc).__name__)


async def _ensure_default_business_unit(pool: asyncpg.Pool) -> None:
    """Ensure ``Default`` exists so ``tickets.business_unit`` / ``incidents`` FK succeeds.

    Matches migration ``004_default_business_unit.sql``. Safe if the row already exists.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO business_units (code, name) VALUES ($1, $2)
            ON CONFLICT (code) DO NOTHING
            """,
            "Default",
            "Unmapped / default",
        )
    log.info("sync.default_business_unit_ready", code="Default")


# ── Main ───────────────────────────────────────────────────────────────────────


async def main() -> None:
    sync_mode: str = _sync_mode()
    database_url: str = os.environ["DATABASE_URL"]
    redis_url: str = _redis_url()

    bu_project_map = _get_bu_project_map()
    incident_types = _get_incident_issue_types()
    all_project_keys = _get_sync_project_keys()

    log.info(
        "sync.started",
        mode=sync_mode,
        redis_target=_redis_target_for_log(redis_url),
        project_scope="all_accessible" if not all_project_keys else "listed",
        project_keys=all_project_keys,
    )
    start_ts = time.monotonic()
    total_processed = 0
    errors = 0

    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn=_build_asyncpg_url(database_url),
        min_size=2,
        max_size=5,
    )
    await _ensure_default_business_unit(pool)

    redis_client: redis.Redis = redis.from_url(redis_url, decode_responses=True)
    try:
        await redis_client.ping()
        log.info("sync.redis_connected")
    except Exception as exc:
        log.error(
            "sync.redis_unavailable",
            error=str(exc),
            redis_target=_redis_target_for_log(redis_url),
        )
        await redis_client.aclose()
        await pool.close()
        raise

    async with JIRAClient() as jira:
        if sync_mode == "full":
            incident_types_jql = _jql_in_list(incident_types)
            projects_jql = _jql_in_list(all_project_keys) if all_project_keys else ""

            # ── Tickets ────────────────────────────────────────────────────────
            raw_tickets = await jira.get_updated_since(
                since=datetime(2000, 1, 1, tzinfo=timezone.utc),
                project_keys=all_project_keys,
            )
            log.info("sync.tickets_fetched", count=len(raw_tickets))

            for raw in raw_tickets:
                bu_code = _resolve_business_unit(raw, bu_project_map)
                if await _try_sync_issue(pool, raw, kind="ticket", bu_code=bu_code):
                    total_processed += 1
                else:
                    errors += 1

            # ── Incidents ──────────────────────────────────────────────────────
            if all_project_keys:
                incident_jql = (
                    f"project in {projects_jql} "
                    f"AND issuetype in {incident_types_jql} "
                    f"ORDER BY created ASC"
                )
            else:
                incident_jql = (
                    f"issuetype in {incident_types_jql} ORDER BY created ASC"
                )
            raw_incidents = await jira.search_tickets(incident_jql, max_results=100)
            incident_issues: list[dict] = raw_incidents.get("issues", [])
            log.info("sync.incidents_fetched", count=len(incident_issues))

            for raw in incident_issues:
                bu_code = _resolve_business_unit(raw, bu_project_map)
                if await _try_sync_issue(pool, raw, kind="incident", bu_code=bu_code):
                    total_processed += 1
                else:
                    errors += 1

            await _set_last_sync_time(redis_client, datetime.now(timezone.utc))

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
                bu_code = _resolve_business_unit(raw, bu_project_map)
                issue_type: str = (fields.get("issuetype") or {}).get("name", "")
                is_incident = issue_type.lower() in incident_types_set

                kind = "incident" if is_incident else "ticket"
                if await _try_sync_issue(pool, raw, kind=kind, bu_code=bu_code):
                    total_processed += 1
                else:
                    errors += 1

            await _set_last_sync_time(redis_client, datetime.now(timezone.utc))

    duration = time.monotonic() - start_ts
    await _log_table_counts(pool)
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
