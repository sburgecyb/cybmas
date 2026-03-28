"""L3 Resolutions Agent — ADK LlmAgent definition.

Used by the Orchestrator's ADK Runner for incident and RCA queries.
Model: gemini-2.5-flash for fast tool-call decisions.
"""
import os
import sys

import structlog
from dotenv import load_dotenv
from google.adk.agents import LlmAgent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"))

from services.shared.google_genai_env import configure_google_genai_for_vertex  # noqa: E402

configure_google_genai_for_vertex()

from services.l1l2_agent.tools.jira_fetch import fetch_jira_ticket  # noqa: E402
from services.l3_agent.tools.cross_ref_tickets import (  # noqa: E402
    cross_reference_tickets_with_incidents,
)
from services.l3_agent.tools.incident_search import search_incidents  # noqa: E402
from services.l3_agent.tools.rca_fetch import fetch_incident_rca  # noqa: E402

log = structlog.get_logger()

SYSTEM_INSTRUCTION = """\
You are an L3 technical support specialist with deep knowledge of production
incidents and Root Cause Analyses (RCAs).

RULES:
1. Call search_incidents first using the business_units from the message context.
2. For a specific incident identified in results, call fetch_incident_rca to
   get the full root cause and long-term fix.
3. To cross-reference incidents with tickets, call
   cross_reference_tickets_with_incidents.
4. For a specific ticket mentioned during an incident, call fetch_jira_ticket.
5. Write your answer directly — cite incident IDs and ticket IDs, highlight:
   - Root cause
   - Long-term fix applied
   - Related tickets raised
   - Whether this is a recurring pattern
6. If RCA is not documented, say: "RCA not yet documented for this incident."
7. For follow-up questions about an already-discussed incident, use the
   conversation history — do not search again unless needed.

Be precise, technical and concise.\
"""

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
    ],
)

log.info("l3_agent.loaded", model="gemini-2.0-flash", tool_count=len(agent.tools))
