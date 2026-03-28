"""ADK tool: lightweight client-side reranking of search results.

Combines the original vector similarity score with a keyword overlap bonus
and a resolved-status bonus so that the most actionable tickets surface first.
No external calls — runs entirely in-process.
"""
import structlog

from services.shared.models import ToolResult  # noqa: E402 (sys.path set by caller)

log = structlog.get_logger()


def _score_result(query_words: set[str], result: dict) -> float:
    """Compute the reranking score for a single search result.

    Args:
        query_words: Lower-cased set of words from the original query.
        result: SearchResult dict as returned by ``search_tickets``.

    Returns:
        Combined float score (higher is better).
    """
    base_score: float = result.get("score", 0.0)

    title = (result.get("title") or "").lower()
    summary = (result.get("summary") or "").lower()
    text_words = set((title + " " + summary).split())
    overlap = len(query_words & text_words)
    keyword_bonus = min(overlap * 0.02, 0.1)

    status_bonus = 0.05 if result.get("status") == "Resolved" else 0.0

    return base_score + keyword_bonus + status_bonus


def apply_keyword_rerank(
    query_text: str,
    results: list[dict],
    top_n: int,
) -> list[dict]:
    """Re-order vector hits by keyword overlap + resolved bonus (in-process).

    Used by ``search_tickets`` so the model does not need a second tool call.
    """
    if not results or top_n <= 0:
        return []
    query_words = set(query_text.lower().split())
    reranked = sorted(
        results,
        key=lambda r: _score_result(query_words, r),
        reverse=True,
    )
    out = reranked[:top_n]
    log.info(
        "apply_keyword_rerank.complete",
        input_count=len(results),
        output_count=len(out),
    )
    return out


def rerank_results(
    query_text: str,
    results: list[dict],
    top_n: int = 5,
) -> dict:
    """Re-rank search results by relevance to the query.

    Use this tool after search_tickets to improve result ordering.
    Combines vector score with keyword overlap and a resolved-ticket bonus.

    Args:
        query_text: The original search query.
        results: List of SearchResult dicts from search_tickets.
        top_n: Number of top results to return after reranking.

    Returns:
        Dictionary with reranked results list.
    """
    try:
        if not results:
            return ToolResult(success=True, data=[]).model_dump()

        reranked = apply_keyword_rerank(query_text, results, top_n)

        log.info(
            "rerank_results.complete",
            input_count=len(results),
            output_count=len(reranked),
        )
        return ToolResult(success=True, data=reranked).model_dump()

    except Exception as exc:
        log.error("rerank_results.failed", error=str(exc))
        # Degrade gracefully — return original ordering rather than an error
        return ToolResult(success=True, data=results[:top_n]).model_dump()
