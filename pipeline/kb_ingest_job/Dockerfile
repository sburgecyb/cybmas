# Build from repository root:
#   docker build -f pipeline/kb_ingest_job/Dockerfile -t kb-ingest-job .
#
# Image runs: download KB_GCS_URI → embed → upsert knowledge_articles (Linux/Cloud Run).
FROM python:3.11-slim
WORKDIR /app

COPY pipeline/kb_ingest_job/requirements.txt ./kb_ingest_requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r kb_ingest_requirements.txt

# Minimal tree for imports: scripts.kb_ingest_core → pipeline.embedding_worker.*
COPY scripts/kb_ingest_core.py ./scripts/kb_ingest_core.py
COPY pipeline/embedding_worker/embedder.py ./pipeline/embedding_worker/embedder.py
COPY pipeline/embedding_worker/processor.py ./pipeline/embedding_worker/processor.py
COPY pipeline/embedding_worker/upsert.py ./pipeline/embedding_worker/upsert.py
RUN touch ./pipeline/__init__.py ./pipeline/embedding_worker/__init__.py

COPY pipeline/kb_ingest_job/main.py ./pipeline/kb_ingest_job/main.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "pipeline/kb_ingest_job/main.py"]
