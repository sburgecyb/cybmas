# Build from repository root:
#   docker build -f pipeline/seed_sample_job/Dockerfile -t seed-sample-job .
#
# Loads scripts/seed_sample_data.py — demo tickets/incidents + embeddings → Cloud SQL.
FROM python:3.11-slim
WORKDIR /app

COPY pipeline/seed_sample_job/requirements.txt ./seed_job_requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r seed_job_requirements.txt

COPY scripts/seed_sample_data.py ./scripts/seed_sample_data.py
COPY pipeline/embedding_worker/embedder.py ./pipeline/embedding_worker/embedder.py
COPY pipeline/embedding_worker/processor.py ./pipeline/embedding_worker/processor.py
RUN touch ./pipeline/__init__.py ./pipeline/embedding_worker/__init__.py

COPY pipeline/seed_sample_job/main.py ./pipeline/seed_sample_job/main.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "pipeline/seed_sample_job/main.py"]
