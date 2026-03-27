"""JIRA Webhook Receiver — Cloud Run service.

Receives JIRA webhook POST events, validates HMAC-SHA256 signature,
and publishes a normalised event payload to Cloud Pub/Sub.
"""
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from google.cloud import pubsub_v1

load_dotenv(".env.local")

# ── Logging ────────────────────────────────────────────────────────────────────


def _configure_logging() -> None:
    shared_processors: list = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if os.getenv("LOG_FORMAT", "dev") == "json":
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()
log = structlog.get_logger()

# ── Config ─────────────────────────────────────────────────────────────────────

JIRA_WEBHOOK_SECRET: str = os.getenv("JIRA_WEBHOOK_SECRET", "")
PUBSUB_TOPIC: str = os.getenv("PUBSUB_TOPIC", "jira-events")
GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")

# ── Pub/Sub client (initialised at startup) ────────────────────────────────────

_publisher: pubsub_v1.PublisherClient | None = None
_topic_path: str = ""
_pubsub_available: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _publisher, _topic_path, _pubsub_available

    _publisher = None
    _pubsub_available = False

    try:
        _publisher = pubsub_v1.PublisherClient()
        _topic_path = _publisher.topic_path(GCP_PROJECT_ID, PUBSUB_TOPIC)
        _pubsub_available = True
        log.info("webhook_receiver.startup", topic=_topic_path, project=GCP_PROJECT_ID)
    except Exception as exc:
        log.warning(
            "pubsub_unavailable",
            error=str(exc),
            message="Running without Pub/Sub - local dev mode",
        )
        log.info("webhook_receiver.startup", pubsub=False, project=GCP_PROJECT_ID)

    yield
    log.info("webhook_receiver.shutdown")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="JIRA Webhook Receiver", lifespan=lifespan)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    """Validate the JIRA webhook HMAC-SHA256 signature.

    JIRA sends the signature as: X-Hub-Signature: sha256=<hex-digest>

    Raises:
        HTTPException 401 if the header is absent or the digest does not match.
    """
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature header")

    expected = "sha256=" + hmac.new(
        JIRA_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "jira-webhook-receiver"}


@app.post("/webhook/jira")
async def receive_jira_webhook(request: Request) -> dict[str, str]:
    body = await request.body()

    _verify_signature(body, request.headers.get("X-Hub-Signature"))

    try:
        payload: dict = json.loads(body)
    except json.JSONDecodeError as exc:
        log.warning("webhook_receiver.parse_error", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    issue_key: str = payload.get("issue", {}).get("key", "UNKNOWN")
    event_type: str = payload.get("webhookEvent", "unknown")
    project_key: str = (
        payload.get("issue", {})
        .get("fields", {})
        .get("project", {})
        .get("key", "UNKNOWN")
    )
    timestamp: str = datetime.now(timezone.utc).isoformat()

    log.info(
        "webhook_receiver.received",
        jira_id=issue_key,
        event_type=event_type,
        project_key=project_key,
    )

    message = json.dumps(
        {
            "jira_id": issue_key,
            "event_type": event_type,
            "project_key": project_key,
            "timestamp": timestamp,
        }
    ).encode()

    if _pubsub_available and _publisher is not None:
        try:
            future = _publisher.publish(_topic_path, message, event_type=event_type)
            future.result()
        except Exception as exc:
            log.error(
                "webhook_receiver.pubsub_error",
                error=str(exc),
                jira_id=issue_key,
                topic=_topic_path,
            )
            raise HTTPException(status_code=500, detail="Failed to publish event to Pub/Sub")
    else:
        log.info("pubsub_skipped_local_dev", jira_id=issue_key)

    return {"status": "received", "jira_id": issue_key}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=True)
