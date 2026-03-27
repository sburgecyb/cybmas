"""Feedback routes: save ratings and retrieve admin summary."""
import os
import sys
import uuid
from datetime import datetime, timezone

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.api_gateway.middleware.auth_middleware import get_current_engineer  # noqa: E402
from services.shared.models import FeedbackInput  # noqa: E402

log = structlog.get_logger()

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

_VALID_RATINGS = frozenset({"correct", "can_be_better", "incorrect"})


# ── Shared dependency ──────────────────────────────────────────────────────────


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("")
async def save_feedback(
    body: FeedbackInput,
    caller: dict = Depends(get_current_engineer),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Persist a rating for a specific message in a session.

    The caller must own the session being rated.
    """
    if body.rating.value not in _VALID_RATINGS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"rating must be one of {sorted(_VALID_RATINGS)}",
        )

    # Verify session ownership
    row = await pool.fetchrow(
        "SELECT engineer_id FROM chat_sessions WHERE id = $1",
        body.session_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row["engineer_id"] != caller["engineer_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await pool.execute(
        """
        INSERT INTO engineer_feedback
            (session_id, message_index, rating, comment, created_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        body.session_id,
        body.message_index,
        body.rating.value,
        body.comment,
        datetime.now(timezone.utc),
    )

    log.info(
        "feedback.saved",
        session_id=str(body.session_id),
        rating=body.rating.value,
        engineer_id=caller["engineer_id"],
    )
    return {"saved": True}


@router.get("/summary")
async def feedback_summary(
    days: int = Query(default=7, ge=1, le=90),
    caller: dict = Depends(get_current_engineer),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return aggregate feedback statistics for the past N days.

    Admin role required.
    """
    if caller.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN rating = 'correct'       THEN 1 ELSE 0 END) AS correct,
            SUM(CASE WHEN rating = 'can_be_better' THEN 1 ELSE 0 END) AS can_be_better,
            SUM(CASE WHEN rating = 'incorrect'     THEN 1 ELSE 0 END) AS incorrect
        FROM engineer_feedback
        WHERE created_at >= NOW() - ($1 * INTERVAL '1 day')
        """,
        days,
    )

    total = int(row["total"] or 0)
    correct = int(row["correct"] or 0)
    accuracy = round(correct / total * 100, 1) if total > 0 else 0.0

    return {
        "total": total,
        "correct": correct,
        "can_be_better": int(row["can_be_better"] or 0),
        "incorrect": int(row["incorrect"] or 0),
        "accuracy_pct": accuracy,
        "period_days": days,
    }
