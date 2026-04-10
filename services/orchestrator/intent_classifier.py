"""Intent classifier for the Orchestrator Agent.

Classifies engineer messages into routing intents using a combination of
fast regex/keyword rules (no LLM call) and a Gemini fallback for ambiguous
messages. Results are cached in Redis for 60 seconds to avoid redundant
LLM calls on repeated or similar messages.

Gemini initialisation is lazy — vertexai.init() and GenerativeModel are
created on the first Gemini fallback call, not at import time.
"""
import asyncio
import hashlib
import os
import re
import sys
from enum import Enum
from pathlib import Path

import structlog
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
from services.shared.models import BusinessUnitScope  # noqa: E402
from services.shared.redis_async import (  # noqa: E402
    async_redis_from_url,
    is_redis_disabled,
    redis_url_from_env,
)

load_dotenv(_ROOT / ".env.local")

log = structlog.get_logger()

# ── Lazy Vertex AI model ───────────────────────────────────────────────────────

_model = None


def _get_model():
    global _model
    if _model is None:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(
            project=os.getenv("GCP_PROJECT_ID"),
            location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        )
        _model = GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
        log.info("intent_classifier.model_initialised")
    return _model

# ── Intent enum ────────────────────────────────────────────────────────────────


class IntentType(str, Enum):
    TICKET_SEARCH  = "ticket_search"
    JIRA_LOOKUP    = "jira_lookup"
    STATUS_CHECK   = "status_check"
    INCIDENT_SEARCH = "incident_search"
    CROSS_REF      = "cross_ref"
    FOLLOW_UP      = "follow_up"
    SESSION_RESUME = "session_resume"
    OUT_OF_SCOPE   = "out_of_scope"


# ── Keyword patterns ───────────────────────────────────────────────────────────

# Case-insensitive so "b1-1001" still routes to JIRA path (uppercase-only pattern missed most pastes).
JIRA_ID_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9]*-\d+\b")


def normalize_message_for_jira_key_scan(message: str) -> str:
    """Normalize text so pasted JIRA keys still match (Unicode dashes, BOM, ZWSP)."""
    s = (
        message.replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
    )
    for bad, good in (
        ("\u2212", "-"),  # minus sign
        ("\u2011", "-"),  # non-breaking hyphen
        ("\u2010", "-"),  # hyphen
        ("\u2013", "-"),  # en dash
        ("\u2014", "-"),  # em dash
    ):
        s = s.replace(bad, good)
    return s

_STATUS_KEYWORDS: list[str] = [
    "status of", "what is the status", "is it resolved", "who is assigned",
]
_INCIDENT_KEYWORDS: list[str] = [
    "incident", "outage", "production issue", "rca", "root cause",
    "p1", "p2", "postmortem",
]
_CROSS_REF_KEYWORDS: list[str] = [
    "cross reference", "cross-reference", "related tickets",
    "tickets raised for", "linked tickets", "incidents and tickets",
]
_SESSION_RESUME_KEYWORDS: list[str] = [
    "resume", "continue our", "go back to", "previous conversation",
    "earlier session",
]

_INTENT_CACHE_TTL = 60  # seconds
_REDIS_CMD_TIMEOUT = 6.0  # seconds — extra guard if Redis is slow or wedged


# ── Lazy singletons ────────────────────────────────────────────────────────────

_redis_client = None


def _get_redis() -> object:
    global _redis_client
    if _redis_client is None:
        _redis_client = async_redis_from_url(
            redis_url_from_env(),
            decode_responses=True,
        )
    return _redis_client


# ── Helpers ────────────────────────────────────────────────────────────────────


def _cache_key(message: str) -> str:
    return "intent:" + hashlib.md5(message.encode()).hexdigest()


def _keyword_match(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


async def _classify_with_gemini(
    message: str,
    context_scope: BusinessUnitScope,
) -> IntentType:
    """Call Gemini via Vertex AI to classify an ambiguous message."""
    prompt = (
        "Classify this support engineer message into one of these intents:\n"
        "ticket_search, jira_lookup, status_check, incident_search, "
        "cross_ref, follow_up, out_of_scope\n\n"
        f"Message: {message}\n"
        f"Has incidents enabled: {context_scope.include_incidents}\n\n"
        "Reply with ONLY the intent name, nothing else."
    )

    loop = asyncio.get_event_loop()
    model = _get_model()
    response = await loop.run_in_executor(
        None,
        lambda: model.generate_content(prompt),
    )
    raw = response.text.strip().lower()

    for intent in IntentType:
        if intent.value in raw:
            return intent

    return IntentType.TICKET_SEARCH


# ── Public API ─────────────────────────────────────────────────────────────────


async def classify_intent(
    message: str,
    context_scope: BusinessUnitScope,
    has_conversation_history: bool = False,
) -> IntentType:
    """Classify the engineer's message into a routing intent.

    Uses fast keyword/regex rules first; falls back to Gemini for ambiguous
    messages. Results are cached in Redis for 60 seconds.

    Args:
        message: The raw engineer message.
        context_scope: Selected BUs and incident-mode flag.
        has_conversation_history: True if a prior turn exists in the session.

    Returns:
        The matching IntentType.
    """
    # ── 0. JIRA ID check — highest priority, no cache needed ──────────────────
    if JIRA_ID_PATTERN.search(normalize_message_for_jira_key_scan(message)):
        log.info(
            "intent_classifier.classified",
            intent=IntentType.JIRA_LOOKUP.value,
            message_length=len(message),
        )
        return IntentType.JIRA_LOOKUP

    # ── 1. Check Redis cache ───────────────────────────────────────────────────
    redis = None
    cache_key = _cache_key(message)
    if not is_redis_disabled():
        redis = _get_redis()
        try:
            cached = await asyncio.wait_for(
                redis.get(cache_key),
                timeout=_REDIS_CMD_TIMEOUT,
            )
            if cached:
                log.info("intent_classifier.cache_hit", intent=cached)
                return IntentType(cached)
        except asyncio.TimeoutError:
            log.warning(
                "intent_classifier.cache_timeout",
                timeout_s=_REDIS_CMD_TIMEOUT,
            )
        except Exception as exc:
            log.warning("intent_classifier.cache_error", error=str(exc))

    # ── 2. Fast rule-based classification ─────────────────────────────────────
    lower = message.lower()

    if _keyword_match(lower, _STATUS_KEYWORDS):
        intent = IntentType.STATUS_CHECK

    elif context_scope.include_incidents and _keyword_match(lower, _INCIDENT_KEYWORDS):
        intent = IntentType.INCIDENT_SEARCH

    elif _keyword_match(lower, _CROSS_REF_KEYWORDS):
        intent = IntentType.CROSS_REF

    elif _keyword_match(lower, _SESSION_RESUME_KEYWORDS):
        intent = IntentType.SESSION_RESUME

    elif has_conversation_history and len(message) < 50:
        intent = IntentType.FOLLOW_UP

    else:
        # ── 3. Default — no Gemini call, ticket search handles everything else ──
        # Calling Gemini here adds 5-10 s to every ambiguous query. The
        # downstream vector search is generic enough to handle all remaining
        # cases (ticket search, general questions). Out-of-scope queries simply
        # return low-scoring results, which is acceptable.
        intent = IntentType.TICKET_SEARCH

    # ── 4. Cache result ────────────────────────────────────────────────────────
    if redis is not None:
        try:
            await asyncio.wait_for(
                redis.setex(cache_key, _INTENT_CACHE_TTL, intent.value),
                timeout=_REDIS_CMD_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning(
                "intent_classifier.cache_write_timeout",
                timeout_s=_REDIS_CMD_TIMEOUT,
            )
        except Exception as exc:
            log.warning("intent_classifier.cache_write_error", error=str(exc))

    log.info(
        "intent_classifier.classified",
        intent=intent.value,
        message_length=len(message),
    )
    return intent
