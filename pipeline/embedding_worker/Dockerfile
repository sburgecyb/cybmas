# Build from repository root (same pattern as api-gateway / orchestrator):
#   docker build -f pipeline/embedding_worker/Dockerfile -t embedding-worker .
FROM python:3.11-slim
WORKDIR /app
COPY pipeline/embedding_worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
COPY pipeline/embedding_worker/ ./

CMD ["python", "main.py"]
