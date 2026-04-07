"""ADK tool: single Vertex embed + parallel KB and ticket search (latency).

Avoids two sequential tool rounds and two ``embed_text`` calls when both corpora
are needed. Prefer this for generic troubleshooting; use ``search_knowledge_base``
/ ``search_tickets`` alone when filters apply to only one side.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from pipeline.embedding_worker.embedder import embed_text  # noqa: E402
from services.l1l2_agent.tools.kb_search import (  # noqa: E402
    _to_vector_str,
    kb_search_with_vector_str,
)
from services.l1l2_agent.tools.vector_search import ticket_search_with_vector_str  # noqa: E402
from services.shared.models import ToolResult  # noqa: E402

log = structlog.get_logger()


async def search_kb_and_tickets(
    query_text: str,
    business_units: list[str],
    top_k: int = 10,
    category: str | None = None,
    level: str | None = None,
    tags_any: list[str] | None = None,
    ticket_type_filter: str | None = None,
) -> dict:
    """Search knowledge base and scoped tickets with **one** query embedding.

    Runs KB and ticket SQL phases in parallel (separate pool connections).

    Args:
        query_text: User problem or topic.
        business_units: BU codes for ticket search (from message context).
        top_k: Max results per corpus (default 10, max 50 each).
        category: Optional KB category filter (omit unless user named it).
        level: Optional KB level filter.
        tags_any: Optional KB tag filter.
        ticket_type_filter: Only when user asked for a Jira type (Bug, etc.).

    Returns:
        ToolResult with ``data``: ``{"knowledge": [...], "tickets": [...]}``.
    """
    t0 = time.time()
    try:
        from services.l1l2_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        t_embed_start = time.time()
        query_vector = await embed_text(query_text)
        embed_ms = round((time.time() - t_embed_start) * 1000)
        vector_str = _to_vector_str(query_vector)

        t_db_start = time.time()
        knowledge, tickets = await asyncio.gather(
            kb_search_with_vector_str(
                pool,
                query_text,
                vector_str,
                top_k=top_k,
                category=category,
                level=level,
                tags_any=tags_any,
            ),
            ticket_search_with_vector_str(
                pool,
                query_text,
                vector_str,
                business_units,
                top_k=top_k,
                ticket_type_filter=ticket_type_filter,
            ),
        )
        db_ms = round((time.time() - t_db_start) * 1000)
        total_ms = round((time.time() - t0) * 1000)

        log.info(
            "search_kb_and_tickets.complete",
            query_length=len(query_text),
            knowledge_count=len(knowledge),
            tickets_count=len(tickets),
            embed_ms=embed_ms,
            db_parallel_ms=db_ms,
            total_ms=total_ms,
        )

        return ToolResult(
            success=True,
            data={"knowledge": knowledge, "tickets": tickets},
        ).model_dump()

    except Exception as exc:
        log.error("search_kb_and_tickets.failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
