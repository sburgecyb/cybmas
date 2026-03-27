"""Route a classified intent to the appropriate agent service endpoint."""
import os
import sys

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from services.orchestrator.intent_classifier import IntentType  # noqa: E402
from services.shared.models import BusinessUnitScope  # noqa: E402

log = structlog.get_logger()

# ── Endpoint env vars ──────────────────────────────────────────────────────────

_L1L2_ENDPOINT  = os.getenv("L1L2_AGENT_ENDPOINT",  "http://localhost:8002")
_L3_ENDPOINT    = os.getenv("L3_AGENT_ENDPOINT",    "http://localhost:8003")
_SESSION_ENDPOINT = os.getenv("SESSION_AGENT_ENDPOINT", "http://localhost:8004")

# ── Routing table ──────────────────────────────────────────────────────────────

_INTENT_ROUTES: dict[IntentType, str | None] = {
    IntentType.TICKET_SEARCH:   _L1L2_ENDPOINT,
    IntentType.JIRA_LOOKUP:     _L1L2_ENDPOINT,
    IntentType.STATUS_CHECK:    _L1L2_ENDPOINT,
    IntentType.INCIDENT_SEARCH: _L3_ENDPOINT,
    IntentType.CROSS_REF:       _L3_ENDPOINT,
    IntentType.SESSION_RESUME:  _SESSION_ENDPOINT,
    IntentType.FOLLOW_UP:       None,  # resolved dynamically via last_agent
    IntentType.OUT_OF_SCOPE:    None,  # handled directly by orchestrator
}


def route_to_agent(
    intent: IntentType,
    context_scope: BusinessUnitScope,
    last_agent: str | None = None,
) -> str | None:
    """Return the service endpoint URL for the given intent.

    Args:
        intent: Classified intent from classify_intent().
        context_scope: Active BU scope and incident-mode flag (reserved for
                       future policy overrides, e.g. forcing L3 when BU has
                       no tickets).
        last_agent: Endpoint of the agent used in the previous turn, used to
                    keep FOLLOW_UP queries on the same agent.

    Returns:
        Absolute URL string of the target agent, or None for OUT_OF_SCOPE
        (orchestrator replies directly) and unresolvable FOLLOW_UP.
    """
    if intent == IntentType.FOLLOW_UP:
        endpoint = last_agent or _L1L2_ENDPOINT
    else:
        endpoint = _INTENT_ROUTES.get(intent)

    log.info(
        "router.routing_decision",
        intent=intent.value,
        endpoint=endpoint,
    )
    return endpoint
