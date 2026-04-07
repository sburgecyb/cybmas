"""ADK tool: semantic ticket search via pgvector cosine similarity.

The query is embedded with Vertex AI text-embedding-004 (768-dim) and compared
against all ticket embeddings using the <=> (cosine distance) operator.
Tickets whose summary/description contain the full query phrase, or contain
**every** significant query word (order-independent), are merged in with a
lexical score floor so paraphrases and reordered titles still match.
Business unit scoping is ALWAYS applied — see .cursorrules constraint.
"""
import json
import os
import sys
import time
from typing import Any

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from pipeline.embedding_worker.embedder import embed_text  # noqa: E402
from services.l1l2_agent.tools.lexical_query import significant_terms  # noqa: E402
from services.l1l2_agent.tools.rerank import apply_keyword_rerank  # noqa: E402
from services.shared.models import SearchResult, ToolResult  # noqa: E402

log = structlog.get_logger()

# ── SQL ────────────────────────────────────────────────────────────────────────

_SEARCH_SQL = """
    SELECT
        jira_id,
        summary,
        description,
        resolution,
        discussion,
        status,
        business_unit,
        ticket_type,
        1 - (embedding <=> $1::vector) AS score
    FROM tickets
    WHERE business_unit = ANY($2)
      AND (
          $3::text IS NULL
          OR UPPER(TRIM(ticket_type)) = UPPER(TRIM($3::text))
      )
    ORDER BY embedding <=> $1::vector
    LIMIT $4
"""

# Phrase match OR enough significant tokens in summary/description/resolution.
# (Requiring *every* token hurt long queries: e.g. "loyalty points redemption"
# tickets missed when the summary lacked words like "functionality" or "expected".)
_LEXICAL_TICKETS_SQL = """
    SELECT
        jira_id,
        summary,
        description,
        resolution,
        discussion,
        status,
        business_unit,
        ticket_type,
        0.68::double precision AS score
    FROM tickets
    WHERE business_unit = ANY($1)
      AND (
          $2::text IS NULL
          OR UPPER(TRIM(ticket_type)) = UPPER(TRIM($2::text))
      )
      AND (
        (
          length(trim($3::text)) >= 8
          AND (
            position(lower(trim($3::text)) in lower(coalesce(summary, ''))) > 0
            OR position(lower(trim($3::text)) in lower(coalesce(description, ''))) > 0
            OR position(lower(trim($3::text)) in lower(coalesce(resolution, ''))) > 0
            OR position(lower(trim($3::text)) in lower(coalesce(discussion::text, ''))) > 0
          )
        )
        OR (
          cardinality($4::text[]) >= 2
          AND (
            SELECT count(*)::int
            FROM unnest($4::text[]) AS kw
            WHERE position(lower(kw) in lower(
              coalesce(summary, '') || ' ' || coalesce(description, '') || ' ' ||
              coalesce(resolution, '') || ' ' || coalesce(discussion::text, '')
            )) > 0
          ) >= $5::int
        )
      )
    LIMIT 40
"""


def _to_vector_str(vector: list[float]) -> str:
    """Format a float list as a pgvector literal ``[v1,v2,...]``."""
    return "[" + ",".join(str(v) for v in vector) + "]"


def _min_lexical_term_hits(term_count: int) -> int:
    """At least 2 significant terms must appear in ticket text (any 2 of N).

    A cap of 3+ hurt domain recall: e.g. query mentions "redemption" but a related
    ticket only shares "loyalty" + "points" (awarding vs redeeming).
    """
    if term_count < 2:
        return 99  # unused: lexical branch needs cardinality >= 2
    return 2


_MAX_RESOLUTION_CHARS = 2000
_MAX_DISC_COMMENT_CHARS = 280
_MAX_DISC_COMMENTS = 5


def _discussion_preview(raw: Any) -> str | None:
    """Flatten last few discussion comments for the LLM (JSONB list of dicts)."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, list) or not raw:
        return None
    parts: list[str] = []
    for c in raw[-_MAX_DISC_COMMENTS :]:
        if not isinstance(c, dict):
            continue
        author = (c.get("author") or "").strip()
        body = (c.get("body") or "").strip()
        if not body:
            continue
        body = body[:_MAX_DISC_COMMENT_CHARS]
        if author:
            parts.append(f"{author}: {body}")
        else:
            parts.append(body)
    if not parts:
        return None
    return "\n".join(parts)


def _ticket_metadata(row: dict) -> dict:
    res = row.get("resolution")
    res_s = (res or "").strip()[:_MAX_RESOLUTION_CHARS] if res else None
    disc = _discussion_preview(row.get("discussion"))
    return {
        "ticket_type": row.get("ticket_type"),
        "resolution": res_s if res_s else None,
        "discussion_preview": disc,
    }


async def ticket_search_with_vector_str(
    pool,
    query_text: str,
    vector_str: str,
    business_units: list[str],
    *,
    top_k: int = 10,
    ticket_type_filter: str | None = None,
) -> list[dict]:
    """Run ticket vector + lexical merge + rerank using a precomputed embedding string."""
    clamped_top_k = min(max(1, top_k), 50)
    type_filter = (ticket_type_filter.strip() if ticket_type_filter else None) or None
    fetch_limit = min(50, max(clamped_top_k * 4, clamped_top_k + 25))

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _SEARCH_SQL,
            vector_str,
            business_units,
            type_filter,
            fetch_limit,
        )
        if not rows and type_filter:
            log.warning(
                "search_tickets.retry_without_type_filter",
                dropped_filter=type_filter,
            )
            rows = await conn.fetch(
                _SEARCH_SQL,
                vector_str,
                business_units,
                None,
                fetch_limit,
            )

        qstrip = query_text.strip()
        terms = significant_terms(query_text)
        lex_min = _min_lexical_term_hits(len(terms))
        lexical_rows: list = []
        if len(qstrip) >= 8 or len(terms) >= 2:
            lexical_rows = await conn.fetch(
                _LEXICAL_TICKETS_SQL,
                business_units,
                type_filter,
                qstrip[:500],
                terms,
                lex_min,
            )
            if not lexical_rows and type_filter:
                lexical_rows = await conn.fetch(
                    _LEXICAL_TICKETS_SQL,
                    business_units,
                    None,
                    qstrip[:500],
                    terms,
                    lex_min,
                )

    by_jira: dict[str, dict] = {}
    for row in rows:
        by_jira[row["jira_id"]] = dict(row)
    for row in lexical_rows:
        jid = row["jira_id"]
        if jid not in by_jira:
            by_jira[jid] = dict(row)
        else:
            prev = float(by_jira[jid]["score"])
            nxt = float(row["score"])
            merged = dict(by_jira[jid])
            merged["score"] = max(prev, nxt)
            by_jira[jid] = merged

    merged_rows = list(by_jira.values())
    results = [
        SearchResult(
            jira_id=row["jira_id"],
            title=row["summary"],
            summary=row["description"][:400] if row["description"] else None,
            score=float(row["score"]),
            result_type="ticket",
            status=row["status"],
            business_unit=row["business_unit"],
            metadata=_ticket_metadata(row),
        ).model_dump()
        for row in merged_rows
    ]
    return apply_keyword_rerank(query_text, results, top_n=clamped_top_k)


# ── Tool ───────────────────────────────────────────────────────────────────────


async def search_tickets(
    query_text: str,
    business_units: list[str],
    top_k: int = 10,
    ticket_type_filter: str | None = None,
) -> dict:
    """Search historical support tickets by semantic similarity.

    Use this tool when an engineer describes a problem and needs to find
    similar past tickets — including alongside search_knowledge_base when the
    user reports broken behavior or wants a resolution. Always provide
    business_units to scope the search.

    Args:
        query_text: Description of the problem to search for.
        business_units: List of business unit codes to search within e.g. ['B1', 'B2'].
        top_k: Number of results to return (default 10, max 50).
        ticket_type_filter: Only set when the user explicitly asks to limit by
            Jira type (Bug, Incident, Task, Story). Omit for general questions
            ("refund issues", "login problems") — those words are not a type filter.
            Matching is case-insensitive (Bug vs BUG).

    Returns:
        Dictionary with success status and list of matching tickets with scores
        (vector similarity plus in-process keyword / status reranking). Each hit
        includes ``metadata.resolution`` and ``metadata.discussion_preview`` when
        present so the model can cite real ticket fixes, not only descriptions.
    """
    start = time.time()
    try:
        # Lazy import avoids circular dependency — pool lives on the FastAPI app
        from services.l1l2_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        query_vector = await embed_text(query_text)
        vector_str = _to_vector_str(query_vector)

        results = await ticket_search_with_vector_str(
            pool,
            query_text,
            vector_str,
            business_units,
            top_k=top_k,
            ticket_type_filter=ticket_type_filter,
        )

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
