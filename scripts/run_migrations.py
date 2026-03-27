"""Run pending database migrations against DATABASE_URL.

Usage:
    python scripts/run_migrations.py

Loads DATABASE_URL from .env.local (python-dotenv).
Tracks applied versions in the schema_migrations table.
Migrations are read from database/migrations/ ordered by filename.
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Resolve paths relative to the repo root (parent of this script)
REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations"
ENV_FILE = REPO_ROOT / ".env.local"


def load_env() -> None:
    if not ENV_FILE.exists():
        print(f"Warning: {ENV_FILE} not found — falling back to environment variables.")
    else:
        load_dotenv(ENV_FILE)


def ensure_migrations_table(cur: psycopg2.extensions.cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    VARCHAR(50) PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )


def applied_versions(cur: psycopg2.extensions.cursor) -> set[str]:
    cur.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def run_migrations() -> None:
    load_env()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    # asyncpg-style URL uses postgresql+asyncpg:// — psycopg2 needs plain postgresql://
    psycopg2_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = psycopg2.connect(psycopg2_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            ensure_migrations_table(cur)
            conn.commit()

            applied = applied_versions(cur)

            sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            if not sql_files:
                print(f"No migration files found in {MIGRATIONS_DIR}")
                return

            for sql_file in sql_files:
                version = sql_file.name
                if version in applied:
                    print(f"Skipped:  {version} (already applied)")
                    continue

                sql = sql_file.read_text(encoding="utf-8")
                try:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
                    conn.commit()
                    print(f"Applied:  {version}")
                except Exception as exc:
                    conn.rollback()
                    print(f"ERROR applying {version}: {exc}", file=sys.stderr)
                    sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
