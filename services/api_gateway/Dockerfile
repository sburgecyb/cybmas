# cybmas API Gateway — FastAPI + JWT + chat SSE proxy to orchestrator.
#
# Build from the REPOSITORY ROOT:
#   docker build -f services/api_gateway/Dockerfile -t cybmas-api .
#
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY services/api_gateway/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services /app/services

# Cloud Run sets PORT (usually 8080). For local: docker run -e PORT=8000 -p 8000:8000 ...
EXPOSE 8080

CMD exec uvicorn services.api_gateway.main:app --host 0.0.0.0 --port "${PORT:-8080}"
