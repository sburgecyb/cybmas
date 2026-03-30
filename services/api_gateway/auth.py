"""JWT authentication and user management utilities for the API Gateway."""
import os
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import structlog
from jose import jwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

log = structlog.get_logger()

# ── Module-level config ────────────────────────────────────────────────────────

JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_HOURS: int = int(os.getenv("JWT_EXPIRY_HOURS", "8"))


# ── Password utilities ─────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT utilities ──────────────────────────────────────────────────────────────


def create_token(email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
    # python-jose requires JSON-serializable claims; exp must be a Unix timestamp (seconds).
    payload: dict = {"sub": email, "role": role, "exp": int(expire.timestamp())}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])


# ── Database helpers ───────────────────────────────────────────────────────────


async def get_user_by_email(pool: asyncpg.Pool, email: str) -> dict | None:
    row = await pool.fetchrow(
        """
        SELECT id, email, hashed_password, full_name, role, is_active
        FROM users
        WHERE email = $1
        """,
        email.lower(),
    )
    return dict(row) if row else None


async def create_user(
    pool: asyncpg.Pool,
    email: str,
    hashed_password: str,
    full_name: str | None = None,
) -> dict:
    row = await pool.fetchrow(
        """
        INSERT INTO users (email, hashed_password, full_name, role)
        VALUES ($1, $2, $3, 'engineer')
        RETURNING id, email, full_name, role
        """,
        email.lower(),
        hashed_password,
        full_name,
    )
    return dict(row)  # type: ignore[arg-type]


async def update_last_login(pool: asyncpg.Pool, email: str) -> None:
    await pool.execute(
        "UPDATE users SET last_login = NOW() WHERE email = $1",
        email.lower(),
    )
