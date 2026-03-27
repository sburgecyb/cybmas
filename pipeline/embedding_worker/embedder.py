"""Vertex AI text-embedding-004 wrapper.

Initialisation is lazy — vertexai.init() and model loading happen on the
first call to embed_text() or embed_batch(), not at import time.
This means the module can be imported safely in tests and tools without
GCP_PROJECT_ID being set in the environment.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import structlog
import vertexai
from vertexai.language_models import TextEmbeddingModel

log = structlog.get_logger()

_EMBED_TEXT_MAX_CHARS: int = 2000
_BATCH_SIZE: int = 5

# ── Lazy singletons ────────────────────────────────────────────────────────────

_model: TextEmbeddingModel | None = None
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=4)


def _get_model() -> TextEmbeddingModel:
    """Initialise vertexai and load the embedding model on first call."""
    global _model
    if _model is None:
        project = os.environ["GCP_PROJECT_ID"]
        location = os.getenv("VERTEX_AI_LOCATION", "us-central1")
        model_name = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
        vertexai.init(project=project, location=location)
        _model = TextEmbeddingModel.from_pretrained(model_name)
        log.info("embedder.initialised", model=model_name, project=project, location=location)
    return _model

# ── Public API ─────────────────────────────────────────────────────────────────


async def embed_text(text: str) -> list[float]:
    """Embed a single text string using Vertex AI text-embedding-004.

    The SDK call is blocking, so it is dispatched to a thread-pool executor
    to avoid blocking the event loop.

    Args:
        text: Input text. Truncated to 2000 characters if longer.

    Returns:
        768-dimensional embedding vector as a list of floats.
    """
    if len(text) > _EMBED_TEXT_MAX_CHARS:
        text = text[:_EMBED_TEXT_MAX_CHARS]

    model = _get_model()
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(
        _executor,
        lambda: model.get_embeddings([text]),
    )
    result: list[float] = list(embeddings[0].values)

    log.info("embedder.embedding_generated", text_length=len(text), dims=len(result))
    return result


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts in batches of 5 (Vertex AI per-request limit).

    Sleeps 1 second between batches to respect rate limits.

    Args:
        texts: List of input strings. Each is truncated to 2000 chars.

    Returns:
        List of 768-dimensional embedding vectors, in the same order as input.
    """
    model = _get_model()
    truncated = [t[:_EMBED_TEXT_MAX_CHARS] for t in texts]
    total_batches = max(1, (len(truncated) + _BATCH_SIZE - 1) // _BATCH_SIZE)
    all_embeddings: list[list[float]] = []
    loop = asyncio.get_running_loop()

    for batch_num, start in enumerate(range(0, len(truncated), _BATCH_SIZE), start=1):
        batch = truncated[start : start + _BATCH_SIZE]

        embeddings = await loop.run_in_executor(
            _executor,
            lambda b=batch: model.get_embeddings(b),
        )
        all_embeddings.extend(list(e.values) for e in embeddings)

        log.info(
            "embedder.batch_progress",
            batch_num=batch_num,
            total_batches=total_batches,
            embedded_so_far=len(all_embeddings),
        )

        if start + _BATCH_SIZE < len(truncated):
            await asyncio.sleep(1.0)

    return all_embeddings


def shutdown() -> None:
    """Shut down the thread-pool executor cleanly. Call from the entry point on exit."""
    _executor.shutdown(wait=True)
