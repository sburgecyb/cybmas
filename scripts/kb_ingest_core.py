"""Shared KB → knowledge_articles ingest (embed + upsert).

Used by ``ingest_kb_jsonl.py`` and ``ingest_kb_cloud_sql.py``. Ensures repo root
is on ``sys.path`` so ``pipeline.*`` imports work when this module is loaded.
"""
from __future__ import annotations

import asyncio
import errno
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import asyncpg
import structlog

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pipeline.embedding_worker.embedder import embed_text  # noqa: E402
from pipeline.embedding_worker.processor import prepare_kb_text  # noqa: E402
from pipeline.embedding_worker.upsert import upsert_kb_article  # noqa: E402

log = structlog.get_logger()

_DOC_ID_KEYS = ("doc_id", "id", "kb_id", "article_id", "document_id")


def normalize_postgres_dsn(url: str) -> str:
    """asyncpg accepts ``postgresql://``; strip SQLAlchemy async prefix if present."""
    return url.strip().replace("postgresql+asyncpg://", "postgresql://")


def dsn_targets_unix_socket(dsn: str) -> bool:
    """True if DSN uses a Unix socket (e.g. Cloud Run ``host=/cloudsql/...``).

    asyncio cannot open Unix sockets on Windows → ``NotImplementedError``.
    """
    low = dsn.lower()
    if "/cloudsql/" in low:
        return True
    try:
        u = urlparse(dsn)
        for _key, values in parse_qs(u.query).items():
            if _key.lower() != "host":
                continue
            for raw in values:
                if unquote(raw).startswith("/"):
                    return True
    except Exception:
        pass
    return False


_CONNECT_TIMEOUT_HINT = (
    "TCP to Postgres timed out or never completed. Typical causes: (1) Cloud SQL "
    "*Connections → Networking → Authorized networks* does not list your **current** "
    "public IP (it changes on home ISP / Wi‑Fi); (2) office VPN/firewall blocking "
    "outbound **TCP 5432**; (3) wrong IP or instance has **private IP only**; "
    "(4) typo in host/port. From PowerShell run: "
    "`Test-NetConnection YOUR_CLOUD_SQL_IP -Port 5432` — `TcpTestSucceeded` should be True."
)

_WIN_UNIX_SOCKET_MSG = (
    "This URL uses a Postgres Unix socket (typical Cloud Run secret: "
    "?host=/cloudsql/PROJECT:REGION:INSTANCE). asyncio does not support Unix "
    "sockets on Windows, so asyncpg raises NotImplementedError. "
    "From your PC use a TCP URL instead, e.g. "
    "postgresql://USER:PASSWORD@CLOUD_SQL_PUBLIC_IP:5432/DBNAME "
    "(authorized networks / SSL as required), same as seed_sample_data.py."
)


def resolve_doc_id(rec: dict) -> str | None:
    """Return doc id; mutates ``rec`` to set ``doc_id`` when resolved from an alias."""
    existing = rec.get("doc_id")
    if existing is not None and str(existing).strip():
        return str(existing).strip()
    for key in _DOC_ID_KEYS:
        if key == "doc_id":
            continue
        val = rec.get(key)
        if val is not None and str(val).strip():
            resolved = str(val).strip()
            rec["doc_id"] = resolved
            return resolved
    return None


def load_kb_records(path: Path) -> list[dict]:
    """Load KB objects from ``.jsonl``, JSON array, single object, or ``{documents: [...]}``."""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if path.suffix.lower() == ".jsonl":
        out: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
        return out
    data = json.loads(raw)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("documents", "articles", "items", "records", "data"):
            if key not in data:
                continue
            inner = data[key]
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
        return [data]
    raise ValueError("JSON root must be an object, array, or use .jsonl")


async def ingest_kb_from_path(
    path: Path,
    *,
    database_url: str,
    throttle_seconds: float = 0.0,
) -> tuple[int, int]:
    """Embed each record and upsert into ``knowledge_articles``.

    Returns:
        ``(upserted_count, skipped_count)`` (skipped = missing doc id).
    """
    dsn = normalize_postgres_dsn(database_url)
    if not dsn:
        raise ValueError("database_url is empty")

    if sys.platform == "win32" and dsn_targets_unix_socket(dsn):
        raise ValueError(_WIN_UNIX_SOCKET_MSG)

    records = load_kb_records(path)
    print(f"Parsed {len(records)} KB record(s) from {path.name}.", flush=True)
    if not records:
        raise ValueError(
            "No KB records found in file. Use JSONL (one JSON object per line), a JSON array "
            "of objects, or an object with a non-empty list under documents / articles / "
            "items / records / data. Each object needs doc_id (or id / kb_id / article_id)."
        )

    try:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    except NotImplementedError as exc:
        raise ValueError(_WIN_UNIX_SOCKET_MSG) from exc
    except OSError as exc:
        win = getattr(exc, "winerror", None)
        if win == 121 or exc.errno == errno.ETIMEDOUT:
            hint = _CONNECT_TIMEOUT_HINT
        elif exc.errno == errno.ECONNREFUSED:
            hint = (
                "Connection refused — wrong port, DB not listening on this interface, "
                "or a firewall is rejecting TCP 5432."
            )
        else:
            hint = (
                "Could not connect to Postgres. Check host/port, SSL (?sslmode=require), "
                "password URL-encoding, and authorized networks."
            )
        raise RuntimeError(f"{type(exc).__name__}: {exc or repr(exc)}. {hint}") from exc
    except Exception as exc:
        hint = (
            "Could not connect to Postgres. Check host/port, SSL (add ?sslmode=require "
            "if Cloud SQL requires TLS), password URL-encoding, and authorized networks."
        )
        raise RuntimeError(f"{type(exc).__name__}: {exc or repr(exc)}. {hint}") from exc

    upserted = 0
    skipped = 0
    try:
        for idx, rec in enumerate(records, start=1):
            doc_id = resolve_doc_id(rec)
            if not doc_id:
                log.error(
                    "ingest_kb.skip_missing_doc_id",
                    index=idx,
                    hint="Add doc_id (or id / kb_id / article_id) to each object.",
                )
                skipped += 1
                continue
            text = prepare_kb_text(rec)
            embedding = await embed_text(text)
            if throttle_seconds > 0:
                await asyncio.sleep(throttle_seconds)
            await upsert_kb_article(pool, rec, embedding)
            upserted += 1
            log.info("ingest_kb.done", doc_id=doc_id, index=idx, total=len(records))
            print(f"  [{idx}/{len(records)}] {doc_id}", flush=True)
    finally:
        await pool.close()

    return upserted, skipped
