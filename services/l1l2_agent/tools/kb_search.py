"""ADK tool: semantic search over global knowledge base articles (pgvector).

Uses the same Vertex embedding model as tickets. No business-unit filter.
"""
import os
import sys
import time

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from pipeline.embedding_worker.embedder import embed_text  # noqa: E402
from services.l1l2_agent.tools.lexical_query import significant_terms  # noqa: E402
from services.l1l2_agent.tools.rerank import apply_keyword_rerank  # noqa: E402
from services.shared.models import SearchResult, ToolResult  # noqa: E402

log = structlog.get_logger()

_SEARCH_SQL = """
    SELECT
        doc_id,
        title,
        category,
        level,
        problem_statement,
        symptoms,
        possible_causes,
        diagnostic_steps,
        resolution_steps,
        validation,
        confidence_score,
        last_updated,
        tags,
        1 - (embedding <=> $1::vector) AS score
    FROM knowledge_articles
    WHERE embedding IS NOT NULL
      AND ($2::text IS NULL OR category = $2)
      AND ($3::text IS NULL OR level = $3)
      AND (
          COALESCE(array_length($4::text[], 1), 0) = 0
          OR EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(COALESCE(tags, '[]'::jsonb)) AS elem
              WHERE lower(elem) = ANY($4::text[])
          )
      )
    ORDER BY embedding <=> $1::vector
    LIMIT $5
"""

_LEXICAL_KB_SQL = """
    SELECT
        doc_id,
        title,
        category,
        level,
        problem_statement,
        symptoms,
        possible_causes,
        diagnostic_steps,
        resolution_steps,
        validation,
        confidence_score,
        last_updated,
        tags,
        0.68::double precision AS score
    FROM knowledge_articles
    WHERE embedding IS NOT NULL
      AND ($1::text IS NULL OR category = $1)
      AND ($2::text IS NULL OR level = $2)
      AND (
          COALESCE(array_length($3::text[], 1), 0) = 0
          OR EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(COALESCE(tags, '[]'::jsonb)) AS elem
              WHERE lower(elem) = ANY($3::text[])
          )
      )
      AND (
        (
          length(trim($4::text)) >= 8
          AND (
            position(lower(trim($4::text)) in lower(coalesce(title, ''))) > 0
            OR position(lower(trim($4::text)) in lower(coalesce(problem_statement, ''))) > 0
          )
        )
        OR (
          cardinality($5::text[]) >= 2
          AND NOT EXISTS (
            SELECT 1
            FROM unnest($5::text[]) AS kw
            WHERE position(lower(kw) in lower(
              coalesce(title, '') || ' ' || coalesce(problem_statement, '')
            )) = 0
          )
        )
      )
    LIMIT 25
"""


def _to_vector_str(vector: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vector) + "]"


def _kb_title_for_display(title: str | None, doc_id: str | None) -> str:
    """Drop a leading doc_id from title so the UI/model do not repeat the id."""
    t = (title or "").strip()
    d = (doc_id or "").strip()
    if d and t.startswith(d):
        return t[len(d) :].lstrip(" -–—:\t") or t
    return t


def _row_metadata(row) -> dict:
    return {
        "category": row["category"],
        "level": row["level"],
        "symptoms": row["symptoms"],
        "possible_causes": row["possible_causes"],
        "diagnostic_steps": row["diagnostic_steps"],
        "resolution_steps": row["resolution_steps"],
        "validation": row["validation"],
        "confidence_score": float(row["confidence_score"])
        if row["confidence_score"] is not None
        else None,
        "last_updated": str(row["last_updated"]) if row["last_updated"] else None,
        "tags": row["tags"],
    }


async def search_knowledge_base(
    query_text: str,
    top_k: int = 10,
    category: str | None = None,
    level: str | None = None,
    tags_any: list[str] | None = None,
) -> dict:
    """Search the global support knowledge base by semantic similarity.

    Use for generic troubleshooting guidance: diagnostic steps, resolutions,
    possible causes, and validation checks. Combine with search_tickets when
    the user needs similar past JIRA tickets.

    Args:
        query_text: Problem or topic to find KB articles for.
        top_k: Max results (default 10, max 50).
        category: Optional exact category filter (e.g. Infrastructure).
        level: Optional support level filter (e.g. L1).
        tags_any: Optional list; article matches if any tag equals one of these
            (case-insensitive).

    Returns:
        ToolResult with SearchResult rows (result_type knowledge; ``doc_id``
        is omitted from the payload so the model and UI do not expose internal
        article ids — structured steps remain in metadata).
    """
    start = time.time()
    try:
        from services.l1l2_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        query_vector = await embed_text(query_text)
        vector_str = _to_vector_str(query_vector)

        clamped_top_k = min(max(1, top_k), 50)
        cat = (category.strip() if category else None) or None
        lev = (level.strip() if level else None) or None
        tag_arr: list[str] = []
        if tags_any:
            tag_arr = sorted({t.strip().lower() for t in tags_any if t and t.strip()})

        fetch_limit = min(50, max(clamped_top_k * 4, clamped_top_k + 25))

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _SEARCH_SQL,
                vector_str,
                cat,
                lev,
                tag_arr,
                fetch_limit,
            )

            qstrip = query_text.strip()
            terms = significant_terms(query_text)
            lexical_rows: list = []
            if len(qstrip) >= 8 or len(terms) >= 2:
                lexical_rows = await conn.fetch(
                    _LEXICAL_KB_SQL,
                    cat,
                    lev,
                    tag_arr,
                    qstrip[:500],
                    terms,
                )

        by_doc: dict[str, dict] = {}
        for row in rows:
            by_doc[row["doc_id"]] = dict(row)
        for row in lexical_rows:
            did = row["doc_id"]
            if did not in by_doc:
                by_doc[did] = dict(row)
            else:
                prev = float(by_doc[did]["score"])
                nxt = float(row["score"])
                merged = dict(by_doc[did])
                merged["score"] = max(prev, nxt)
                by_doc[did] = merged

        results = []
        for row in by_doc.values():
            ps = row["problem_statement"] or ""
            did = row["doc_id"]
            results.append(
                SearchResult(
                    doc_id=did,
                    title=_kb_title_for_display(row.get("title"), did),
                    summary=ps[:200] if ps else None,
                    score=float(row["score"]),
                    result_type="knowledge",
                    metadata=_row_metadata(row),
                ).model_dump()
            )

        results = apply_keyword_rerank(query_text, results, top_n=clamped_top_k)
        for r in results:
            r.pop("doc_id", None)

        latency_ms = round((time.time() - start) * 1000)
        log.info(
            "search_knowledge_base.complete",
            query_length=len(query_text),
            result_count=len(results),
            latency_ms=latency_ms,
        )

        return ToolResult(success=True, data=results).model_dump()

    except Exception as exc:
        log.error("search_knowledge_base.failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
