"""Ingest knowledge base JSON or JSONL into knowledge_articles (local or any Postgres).

Uses ``DATABASE_URL`` from the environment (e.g. ``.env.local`` at repo root).

Usage:
    python scripts/ingest_kb_jsonl.py path/to/articles.jsonl
    python scripts/ingest_kb_jsonl.py path/to/articles.json

For Cloud SQL with an explicit URL, prefer ``ingest_kb_cloud_sql.py``.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_SCRIPTS))

load_dotenv(_ROOT / ".env.local")

from kb_ingest_core import ingest_kb_from_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest KB JSON/JSONL with embeddings.")
    parser.add_argument("path", type=Path, help="Path to .json or .jsonl file")
    parser.add_argument(
        "--throttle-seconds",
        type=float,
        default=0.0,
        help="Sleep after each embed (rate limits), default 0",
    )
    args = parser.parse_args()
    if not args.path.is_file():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("ERROR: DATABASE_URL not set (e.g. in .env.local)", file=sys.stderr)
        sys.exit(1)

    def _format_exc(exc: BaseException) -> str:
        text = str(exc).strip()
        if text:
            return text
        return f"{type(exc).__name__} (no message — check traceback below)"

    async def _run() -> None:
        try:
            up, skip = await ingest_kb_from_path(
                args.path,
                database_url=dsn,
                throttle_seconds=args.throttle_seconds,
            )
        except ValueError as exc:
            print(f"ERROR: {_format_exc(exc)}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"ERROR: {_format_exc(exc)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        print(f"\nDone: {up} upserted, {skip} skipped (missing id).", flush=True)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
