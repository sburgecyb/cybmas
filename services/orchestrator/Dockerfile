# cybmas Orchestrator — ADK + FastAPI (/process SSE).
#
# Build from the REPOSITORY ROOT (monorepo imports: services.*, pipeline.*):
#   docker build -f services/orchestrator/Dockerfile -t cybmas-orchestrator .
#
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY services/orchestrator/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Paths must match sys.path / Path(__file__) layout (repo root = /app).
COPY services /app/services
COPY pipeline /app/pipeline

# Cloud Run sets PORT (usually 8080). For local: docker run -e PORT=8001 -p 8001:8001 ...
EXPOSE 8080

CMD exec uvicorn services.orchestrator.server:app --host 0.0.0.0 --port "${PORT:-8080}"
