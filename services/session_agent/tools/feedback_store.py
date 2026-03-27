"""Feedback store tools — persist and aggregate engineer feedback."""
import os
import sys
import uuid
from datetime import datetime, timezone

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.shared.models import FeedbackRating, ToolResult  # noqa: E402

log = structlog.get_logger()

_VALID_RATINGS: set[str] = {"correct", "can_be_better", "incorrect"}

# ── SQL ────────────────────────────────────────────────────────────────────────

_INSERT_FEEDBACK_SQL = """
    INSERT INTO engineer_feedback
        (session_id, message_index, rating, comment, created_at)
    VALUES ($1, $2, $3, $4, $5)
"""

_FEEDBACK_SUMMARY_SQL = """
    SELECT
        COUNT(*)                                                        AS total,
        SUM(CASE WHEN rating = 'correct'       THEN 1 ELSE 0 END)      AS correct,
        SUM(CASE WHEN rating = 'can_be_better' THEN 1 ELSE 0 END)      AS can_be_better,
        SUM(CASE WHEN rating = 'incorrect'     THEN 1 ELSE 0 END)      AS incorrect
    FROM engineer_feedback
    WHERE created_at >= NOW() - ($1 * INTERVAL '1 day')
"""

# ── Tools ──────────────────────────────────────────────────────────────────────


async def save_feedback(
    session_id: str,
    message_index: int,
    rating: str,
    comment: str | None = None,
) -> dict:
    """Save engineer feedback for a specific response.

    Use this tool when an engineer rates a response as correct,
    can_be_better, or incorrect.

    Args:
        session_id: UUID string of the session.
        message_index: Index of the message being rated (0-based).
        rating: One of 'correct', 'can_be_better', 'incorrect'.
        comment: Optional free-text comment from the engineer.

    Returns:
        Dictionary with success status.
    """
    try:
        if rating not in _VALID_RATINGS:
            return ToolResult(
                success=False,
                error=f"Invalid rating '{rating}'. Must be one of: {sorted(_VALID_RATINGS)}",
            ).model_dump()

        from services.session_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        await pool.execute(
            _INSERT_FEEDBACK_SQL,
            uuid.UUID(session_id),
            message_index,
            rating,
            comment,
            datetime.now(timezone.utc),
        )

        log.info(
            "feedback_store.saved",
            session_id=session_id,
            message_index=message_index,
            rating=rating,
        )
        return ToolResult(success=True, data={"saved": True}).model_dump()

    except Exception as exc:
        log.error("feedback_store.save_failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()


async def get_feedback_summary(
    days: int = 7,
    business_unit: str | None = None,
) -> dict:
    """Get aggregated feedback statistics.

    Use this tool to get a summary of how well the AI is performing.
    Admin only.

    Args:
        days: Number of past days to include (default 7).
        business_unit: Reserved for future BU-scoped filtering (currently
                       not applied — engineer_feedback has no direct BU column).

    Returns:
        Dictionary with total, correct, can_be_better, incorrect counts
        and accuracy percentage.
    """
    try:
        from services.session_agent.main import get_db_pool  # type: ignore[import]

        pool = await get_db_pool()
        row = await pool.fetchrow(_FEEDBACK_SUMMARY_SQL, days)

        total = int(row["total"] or 0)
        correct = int(row["correct"] or 0)
        accuracy_pct = round(correct / total * 100, 1) if total > 0 else 0.0

        result: dict = {
            "total": total,
            "correct": correct,
            "can_be_better": int(row["can_be_better"] or 0),
            "incorrect": int(row["incorrect"] or 0),
            "accuracy_pct": accuracy_pct,
            "period_days": days,
        }

        log.info("feedback_store.summary", **result)
        return ToolResult(success=True, data=result).model_dump()

    except Exception as exc:
        log.error("feedback_store.summary_failed", error=str(exc))
        return ToolResult(success=False, error=str(exc)).model_dump()
