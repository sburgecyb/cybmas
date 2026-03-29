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

EXPOSE 8000

CMD ["uvicorn", "services.api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
