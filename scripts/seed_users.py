"""Seed default user accounts into the users table.

Skips any email that already exists (ON CONFLICT DO NOTHING).
Passwords are hashed with bcrypt before insertion.

Usage:
    python scripts/seed_users.py
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import bcrypt
import structlog
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env.local")

log = structlog.get_logger()

# ── Default accounts ───────────────────────────────────────────────────────────

_USERS: list[dict] = [
    {
        "email": "admin@company.com",
        "password": "Admin@1234",
        "full_name": "System Admin",
        "role": "admin",
    },
    {
        "email": "l1engineer@company.com",
        "password": "Engineer@1234",
        "full_name": "L1/L2 Support Engineer",
        "role": "engineer",
    },
    {
        "email": "l3engineer@company.com",
        "password": "Engineer@1234",
        "full_name": "L3 Support Engineer",
        "role": "engineer",
    },
]


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def seed() -> None:
    dsn = os.getenv("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if not dsn:
        print("ERROR: DATABASE_URL not set in .env.local", file=sys.stderr)
        sys.exit(1)

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)

    try:
        for user in _USERS:
            result = await pool.execute(
                """
                INSERT INTO users (email, hashed_password, full_name, role)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (email) DO NOTHING
                """,
                user["email"],
                _hash(user["password"]),
                user["full_name"],
                user["role"],
            )
            # asyncpg returns "INSERT 0 N" — N=0 means skipped
            inserted = result.split()[-1] == "1"
            status = "inserted" if inserted else "skipped (already exists)"
            log.info("seed_user", email=user["email"], status=status)
    finally:
        await pool.close()

    divider = "─" * 45
    print(f"\n✅ Users seeded")
    print(divider)
    for user in _USERS:
        print(
            f"  {user['email']:<26} / {user['password']:<14} ({user['role']})"
        )
    print(divider)


if __name__ == "__main__":
    asyncio.run(seed())
