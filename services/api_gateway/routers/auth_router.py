"""Authentication routes: login, register, me, logout."""
import os
import sys

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, status

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.api_gateway.auth import (  # noqa: E402
    create_token,
    create_user,
    get_user_by_email,
    hash_password,
    update_last_login,
    verify_password,
)
from services.api_gateway.deps import get_db_pool  # noqa: E402
from services.api_gateway.middleware.auth_middleware import get_current_engineer  # noqa: E402
from services.shared.models import TokenResponse, UserCreate, UserLogin  # noqa: E402

log = structlog.get_logger()

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLogin,
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> TokenResponse:
    user = await get_user_by_email(pool, body.email)

    # Deliberate: same error message for unknown email and wrong password
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account disabled",
        )

    token = create_token(user["email"], user["role"])
    await update_last_login(pool, user["email"])

    log.info("auth.login_success", engineer_id=user["email"])
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        engineer_id=user["email"],
        role=user["role"],
    )


@router.post("/register")
async def register(
    body: UserCreate,
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> dict:
    existing = await get_user_by_email(pool, body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    hashed = hash_password(body.password)
    await create_user(pool, body.email, hashed, body.full_name)

    log.info("auth.register_success", engineer_id=body.email)
    return {"engineer_id": body.email.lower(), "message": "Account created"}


@router.get("/me")
async def get_me(
    current_engineer: dict = Depends(get_current_engineer),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> dict:
    try:
        log.info(
            "get_me_debug",
            engineer_id=current_engineer.get("engineer_id"),
            pool_closed=pool._closed if hasattr(pool, "_closed") else "unknown",
        )

        row = await pool.fetchrow(
            "SELECT email, full_name, role FROM users WHERE email = $1",
            current_engineer["engineer_id"],
        )

        log.info("get_me_query_result", found=row is not None)

        if not row:
            row = await pool.fetchrow(
                "SELECT email, full_name, role FROM users WHERE LOWER(email) = LOWER($1)",
                current_engineer["engineer_id"],
            )

        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        return {
            "engineer_id": row["email"],
            "full_name": row["full_name"],
            "role": row["role"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.error("get_me_error", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.post("/logout")
async def logout(
    caller: dict = Depends(get_current_engineer),
) -> dict:
    log.info("auth.logout", engineer_id=caller.get("engineer_id"))
    return {"message": "Logged out"}
