"""Cloud Run Job: seed demo tickets/incidents into Postgres (Vertex embeddings).

Runs the same logic as ``python scripts/seed_sample_data.py`` against Cloud SQL.

Environment:
  DATABASE_URL       — Postgres DSN (Unix socket form for Cloud Run + Cloud SQL attachment)
  GCP_PROJECT_ID     — Vertex project
  VERTEX_AI_LOCATION — optional, default us-central1

Prereq: migrations applied on the target DB. Idempotent (ON CONFLICT DO UPDATE).
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def _load_seed_module():
    path = _REPO_ROOT / "scripts" / "seed_sample_data.py"
    spec = importlib.util.spec_from_file_location("seed_sample_data", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    if not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL is not set")
    if not os.getenv("GCP_PROJECT_ID", "").strip():
        raise SystemExit("GCP_PROJECT_ID is not set (required for Vertex embeddings)")

    mod = _load_seed_module()
    asyncio.run(mod.main())


if __name__ == "__main__":
    main()
