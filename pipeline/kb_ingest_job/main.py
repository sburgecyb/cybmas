"""Cloud Run Job: download KB JSON/JSONL from GCS → embed → upsert ``knowledge_articles``.

Environment:
  KB_GCS_URI   — required, e.g. ``gs://my-bucket/path/kb.json`` or ``.jsonl``
  DATABASE_URL — Postgres DSN (Unix socket form for Cloud Run + --add-cloudsql-instances)
  GCP_PROJECT_ID, VERTEX_AI_LOCATION — Vertex embeddings (same as embedding worker)

Optional:
  KB_THROTTLE_SECONDS — float, default 0 (sleep after each embed for rate limits)
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

# Image layout: /app/scripts/kb_ingest_core.py, /app/pipeline/kb_ingest_job/main.py
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from google.cloud import storage  # noqa: E402

from scripts.kb_ingest_core import ingest_kb_from_path  # noqa: E402

_GS = re.compile(r"^gs://([^/]+)/(.+)$")


def _parse_gs(uri: str) -> tuple[str, str]:
    m = _GS.match(uri.strip())
    if not m:
        raise ValueError(f"KB_GCS_URI must look like gs://bucket/object, got: {uri!r}")
    return m.group(1), unquote(m.group(2))


def _download_to_temp(bucket: str, blob_path: str) -> Path:
    client = storage.Client()
    bkt = client.bucket(bucket)
    blob = bkt.blob(blob_path)
    if not blob.exists():
        raise FileNotFoundError(f"GCS object not found: gs://{bucket}/{blob_path}")
    suffix = Path(blob_path).suffix or ".json"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="kb_ingest_")
    os.close(fd)
    out = Path(tmp_path)
    blob.download_to_filename(str(out))
    return out


async def _run() -> None:
    uri = os.getenv("KB_GCS_URI", "").strip()
    if not uri:
        raise SystemExit("KB_GCS_URI is not set")

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")

    throttle = float(os.getenv("KB_THROTTLE_SECONDS", "0") or "0")

    bucket, path = _parse_gs(uri)
    local = _download_to_temp(bucket, path)
    size = local.stat().st_size
    print(
        f"Downloaded KB object gs://{bucket}/{path} ({size} bytes) → {local}",
        flush=True,
    )
    try:
        up, skip = await ingest_kb_from_path(
            local,
            database_url=dsn,
            throttle_seconds=throttle,
        )
    finally:
        try:
            local.unlink(missing_ok=True)
        except OSError:
            pass

    print(f"kb_ingest_job complete: {up} upserted, {skip} skipped.", flush=True)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
