"""ADK tools: fetch full JIRA ticket details and check ticket status.

``fetch_jira_ticket``: Redis → Postgres ``tickets`` (KB / seed) → live JIRA.

``check_ticket_status``: Redis → **live JIRA only** (never the local DB — status
must reflect JIRA, which may differ from the synced snapshot).

TTL: fetch_jira_ticket 5 min; check_ticket_status 2 min.
"""
import json
import os
import sys

import redis.asyncio as redis
import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from pipeline.embedding_worker.jira_client import JIRAClient, JIRAClientError  # noqa: E402
from services.shared.models import ToolResult  # noqa: E402

log = structlog.get_logger()

_REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
_TICKET_CACHE_TTL = 300   # 5 minutes
_STATUS_CACHE_TTL = 120   # 2 minutes


# ── Redis helpers ──────────────────────────────────────────────────────────────


async def _cache_get(redis_client: redis.Redis, key: str) -> dict | None:
    """Return the cached JSON value for ``key``, or None on miss/error."""
    raw: bytes | None = await redis_client.get(key)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


async def _cache_set(redis_client: redis.Redis, key: str, value: dict, ttl: int) -> None:
    await redis_client.setex(key, ttl, json.dumps(value, default=str))


def _iso(dt: object | None) -> str | None:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()  # type: ignore[no-any-return]
    return str(dt)


async def _try_load_ticket_from_db(jira_id: str) -> dict | None:
    """Return fetch_jira_ticket-shaped dict from ``tickets``, or None if not found."""
    try:
        from services.l1l2_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        row = await pool.fetchrow(
            """SELECT jira_id, summary, description, status, resolution,
                      discussion, ticket_type, created_at, updated_at
               FROM tickets WHERE jira_id = $1""",
            jira_id,
        )
        if not row:
            row = await pool.fetchrow(
                """SELECT jira_id, summary, description, status, resolution,
                          discussion, ticket_type, created_at, updated_at
                   FROM tickets WHERE UPPER(jira_id) = UPPER($1)""",
                jira_id,
            )
        if not row:
            return None

        discussion = row["discussion"] or []
        if isinstance(discussion, str):
            try:
                discussion = json.loads(discussion)
            except json.JSONDecodeError:
                discussion = []

        comments: list[dict] = []
        for c in (discussion or [])[-5:]:
            if isinstance(c, dict):
                comments.append(
                    {
                        "author": str(c.get("author") or "Unknown"),
                        "body": str(c.get("body") or "")[:2000],
                        "created": c.get("created"),
                    }
                )

        canonical = row["jira_id"]
        desc = row["description"] or ""
        return {
            "jira_id": canonical,
            "summary": row["summary"],
            "status": row["status"],
            "assignee": None,
            "reporter": None,
            "priority": row["ticket_type"],
            "issue_type": row["ticket_type"],
            "created": _iso(row["created_at"]),
            "updated": _iso(row["updated_at"]),
            "description": desc[:2000] if desc else None,
            "resolution": row["resolution"] or None,
            "comments": comments,
            "_source": "database",
        }
    except Exception as exc:
        log.warning("jira_fetch.db_lookup_failed", jira_id=jira_id, error=str(exc))
        return None


# ── Tools ──────────────────────────────────────────────────────────────────────


async def fetch_jira_ticket(jira_id: str) -> dict:
    """Fetch full details of a specific JIRA ticket by its ID.

    Use this tool when an engineer mentions a specific ticket ID like B1-1234
    or wants to see the full details of a known ticket.

    Args:
        jira_id: The JIRA ticket ID e.g. 'B1-1234'.

    Returns:
        Dictionary with ticket details including summary, status,
        description, resolution and up to 5 recent comments.
        Data may come from the local ``tickets`` table (field ``_source``: ``database``)
        when the issue is not available from live JIRA.
    """
    redis_client = redis.from_url(_REDIS_URL)
    cache_key = f"jira:ticket:{jira_id}"

    try:
        cached = await _cache_get(redis_client, cache_key)
        if cached is not None:
            log.info("jira_fetch.cache_hit", jira_id=jira_id)
            return ToolResult(success=True, data=cached).model_dump()

        db_data = await _try_load_ticket_from_db(jira_id)
        if db_data is not None:
            await _cache_set(redis_client, cache_key, db_data, _TICKET_CACHE_TTL)
            log.info("jira_fetch.success_db", jira_id=jira_id)
            return ToolResult(success=True, data=db_data).model_dump()

        async with JIRAClient() as client:
            issue = await client.get_ticket(jira_id)
            fields: dict = issue.get("fields") or {}

            description = client.extract_plain_text(fields.get("description"))
            resolution_field = fields.get("resolution") or {}
            resolution_text = client.extract_plain_text(
                resolution_field.get("description")
            )

            raw_comments: list[dict] = (
                fields.get("comment", {}).get("comments") or []
            )[-5:]
            comments = [
                {
                    "author": (c.get("author") or {}).get("displayName", "Unknown"),
                    "body": client.extract_plain_text(c.get("body")),
                    "created": c.get("created"),
                }
                for c in raw_comments
            ]

            result: dict = {
                "jira_id": jira_id,
                "summary": fields.get("summary"),
                "status": (fields.get("status") or {}).get("name"),
                "assignee": (fields.get("assignee") or {}).get("displayName"),
                "reporter": (fields.get("reporter") or {}).get("displayName"),
                "priority": (fields.get("priority") or {}).get("name"),
                "issue_type": (fields.get("issuetype") or {}).get("name"),
                "created": fields.get("created"),
                "updated": fields.get("updated"),
                "description": description[:2000] if description else None,
                "resolution": resolution_text or None,
                "comments": comments,
            }

        result["_source"] = "jira"
        await _cache_set(redis_client, cache_key, result, _TICKET_CACHE_TTL)
        log.info("jira_fetch.success", jira_id=jira_id)
        return ToolResult(success=True, data=result).model_dump()

    except JIRAClientError as exc:
        return ToolResult(
            success=False,
            error=f"Ticket {jira_id} not found or inaccessible: {exc}",
        ).model_dump()
    except Exception as exc:
        log.error("jira_fetch.failed", jira_id=jira_id, error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
    finally:
        await redis_client.aclose()


async def check_ticket_status(jira_id: str) -> dict:
    """Check the current status of a JIRA ticket from **live JIRA** (not Postgres).

    Use this tool when an engineer asks about the status of a specific ticket.
    Lighter than fetch_jira_ticket — only returns status, assignee and last update.
    The local ``tickets`` table is not used here because workflow status can change
    in JIRA after the last sync.

    Args:
        jira_id: The JIRA ticket ID e.g. 'B1-1234'.

    Returns:
        Dictionary with status, assignee, priority and last updated date.
    """
    redis_client = redis.from_url(_REDIS_URL)
    cache_key = f"jira:status:{jira_id}"

    try:
        cached = await _cache_get(redis_client, cache_key)
        if cached is not None:
            log.info("jira_status.cache_hit", jira_id=jira_id)
            return ToolResult(success=True, data=cached).model_dump()

        async with JIRAClient() as client:
            issue = await client.get_ticket(jira_id)
            fields: dict = issue.get("fields") or {}

            result: dict = {
                "jira_id": jira_id,
                "status": (fields.get("status") or {}).get("name"),
                "assignee": (fields.get("assignee") or {}).get(
                    "displayName", "Unassigned"
                ),
                "last_updated": fields.get("updated"),
                "priority": (fields.get("priority") or {}).get("name"),
                "_source": "jira",
            }

        await _cache_set(redis_client, cache_key, result, _STATUS_CACHE_TTL)
        log.info("jira_status.success", jira_id=jira_id)
        return ToolResult(success=True, data=result).model_dump()

    except Exception as exc:
        log.error("jira_status.failed", jira_id=jira_id, error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
    finally:
        await redis_client.aclose()
