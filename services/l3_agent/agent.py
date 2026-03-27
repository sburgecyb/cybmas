"""L3 Resolutions Agent — ADK LlmAgent definition.

This module defines the agent instance that is loaded by the ADK runner.
All tool functions are plain async/sync callables — no @tool decorator
is required in ADK 1.27.5+.
"""
import os
import sys

import structlog
from dotenv import load_dotenv
from google.adk.agents import LlmAgent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(".env.local")

from services.l1l2_agent.tools.jira_fetch import fetch_jira_ticket  # noqa: E402
from services.l3_agent.tools.cross_ref_tickets import (  # noqa: E402
    cross_reference_tickets_with_incidents,
)
from services.l3_agent.tools.incident_search import search_incidents  # noqa: E402
from services.l3_agent.tools.rca_fetch import fetch_incident_rca  # noqa: E402
from services.shared.skills.summarize import summarize_search_results  # noqa: E402

log = structlog.get_logger()

# ── System instruction ─────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION = """You are an L3 technical support specialist for a \
multi-agent agentic platform with deep knowledge of production incidents \
and Root Cause Analyses (RCAs).

When the Incident Management knowledge base is active:

1. Use search_incidents to find relevant past incidents — when business_units \
is provided, scope the search to those BUs; otherwise search all BUs
2. When a specific incident is identified, use fetch_incident_rca to get \
full RCA details including root cause and long-term fix
3. If the engineer wants to cross-reference with tickets, use \
cross_reference_tickets_with_incidents
4. For questions about a specific ticket raised during an incident, \
use fetch_jira_ticket
5. ALWAYS use summarize_search_results to synthesise findings into a \
clear answer — never return raw data directly
6. Highlight in your response:
   - Root cause of the incident
   - Long-term fix that was applied
   - Related tickets that were raised
   - Whether this is a recurring pattern
7. If the engineer asks a follow-up about an incident already discussed, \
use the conversation context — do not search again unless needed
8. If RCA is not documented, say so clearly: \
"RCA not yet documented for this incident"
9. Always cite incident IDs and ticket IDs in your response

You are precise, technical and concise."""

# ── Agent ──────────────────────────────────────────────────────────────────────

agent = LlmAgent(
    name="l3_resolutions_agent",
    model="gemini-2.5-flash",
    description=(
        "Searches historical production incidents and RCAs to help L3 engineers "
        "diagnose and resolve production issues"
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        search_incidents,
        fetch_incident_rca,
        cross_reference_tickets_with_incidents,
        fetch_jira_ticket,
        summarize_search_results,
    ],
)

log.info("l3_agent.loaded", model="gemini-2.5-flash", tool_count=len(agent.tools))
