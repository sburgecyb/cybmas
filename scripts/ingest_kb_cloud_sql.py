"""Ingest knowledge base files into **Google Cloud SQL** (Postgres + pgvector).

This script does **not** call the ``gcloud`` CLI. It only opens a normal Postgres
connection (``asyncpg``) and calls Vertex for embeddings.

**Database URL** — use ``--database-url`` or ``DATABASE_URL``. You can reach Cloud SQL
without installing ``gcloud`` in any of these ways:

1. **Public IP** — In Cloud Console, enable a public IP on the instance, add your
   client IP under *Authorized networks*, then use::

       postgresql://USER:PASSWORD@CLOUD_SQL_PUBLIC_IP:5432/DBNAME

2. **Cloud SQL Auth Proxy (standalone binary)** — Download the proxy from Google’s
   release page (no ``gcloud`` required). Run e.g.::

       cloud-sql-proxy --port 5432 --credentials-file=path/to/sa.json PROJECT:REGION:INSTANCE

   Then ``--database-url postgresql://USER:PASSWORD@127.0.0.1:5432/DBNAME``.

3. **Private / VPC** — Run this script from a machine that already has network
   path to the instance (GCE VM, Cloud Run Job, VPN, etc.) and use the private
   host in the URL.

**Embeddings (Vertex)** — Set ``GCP_PROJECT_ID``, ``VERTEX_AI_LOCATION``, and
authentication via ``GOOGLE_APPLICATION_CREDENTIALS`` (service account JSON).
That also does not require the ``gcloud`` CLI.

Password characters like ``@`` must be URL-encoded in the URL.

Input shapes: ``.jsonl``, JSON array, single object, or ``{"documents": [...]}``.
Document ids: ``doc_id`` or ``id`` / ``kb_id`` / etc.

Prerequisites: migration ``005_knowledge_articles.sql`` applied against this DB
(``python scripts/run_migrations.py`` with the same ``DATABASE_URL``).
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upsert KB JSON/JSONL into Cloud SQL knowledge_articles with embeddings.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to .json or .jsonl KB export",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        type=str,
        default=None,
        metavar="URL",
        help=(
            "Postgres URL (public IP, proxy on 127.0.0.1, or private host). "
            "Example: postgresql://user:pass@127.0.0.1:5432/dbname. "
            "If omitted, uses DATABASE_URL from the environment (.env.local after load)."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Dotenv file for Vertex/GCP vars (default: repo .env.local)",
    )
    parser.add_argument(
        "--throttle-seconds",
        type=float,
        default=0.0,
        help="Sleep after each embedding call (rate limits), default 0",
    )
    args = parser.parse_args()

    env_path = args.env_file if args.env_file is not None else _ROOT / ".env.local"
    if env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()

    if not args.path.is_file():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    # CLI must win over .env: load_dotenv may set DATABASE_URL, but an explicit
    # --database-url should always be used when provided (non-empty).
    cli_url = (args.database_url or "").strip() if args.database_url is not None else ""
    if cli_url:
        dsn = cli_url
        print("Using database URL from --database-url (not DATABASE_URL from env).", flush=True)
    else:
        dsn = os.getenv("DATABASE_URL", "").strip()
        if dsn:
            print("Using DATABASE_URL from environment / .env.local.", flush=True)

    if not dsn:
        print(
            "ERROR: pass a non-empty --database-url or set DATABASE_URL.",
            file=sys.stderr,
        )
        sys.exit(1)

    from kb_ingest_core import ingest_kb_from_path  # noqa: E402

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
        print(f"\nCloud SQL ingest complete: {up} upserted, {skip} skipped.", flush=True)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
