"""ADK tools: fetch full JIRA ticket details and check ticket status.

Both tools check a Redis cache before hitting the JIRA REST API:
  - fetch_jira_ticket: 5-minute TTL, full issue payload
  - check_ticket_status: 2-minute TTL, status/assignee only
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
    """
    redis_client = redis.from_url(_REDIS_URL)
    cache_key = f"jira:ticket:{jira_id}"

    try:
        cached = await _cache_get(redis_client, cache_key)
        if cached is not None:
            log.info("jira_fetch.cache_hit", jira_id=jira_id)
            return ToolResult(success=True, data=cached).model_dump()

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
    """Check the current status of a JIRA ticket.

    Use this tool when an engineer asks about the status of a specific ticket.
    Lighter than fetch_jira_ticket — only returns status, assignee and last update.

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
            }

        await _cache_set(redis_client, cache_key, result, _STATUS_CACHE_TTL)
        log.info("jira_status.success", jira_id=jira_id)
        return ToolResult(success=True, data=result).model_dump()

    except Exception as exc:
        log.error("jira_status.failed", jira_id=jira_id, error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
    finally:
        await redis_client.aclose()
