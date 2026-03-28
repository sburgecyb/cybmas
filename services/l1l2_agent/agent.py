"""L1/L2 Resolution Agent — ADK LlmAgent definition.

Used by the Orchestrator's ADK Runner. All tools are plain async functions;
ADK reads their name and docstring to decide when to call them.

Model: gemini-2.5-flash — 3× faster tool-call decisions than 2.5-flash.
summarize_search_results is intentionally NOT in the tools list; ADK
generates the final answer natively so a separate summarise call is redundant.
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

from services.l1l2_agent.tools.jira_fetch import (  # noqa: E402
    check_ticket_status,
    fetch_jira_ticket,
)
from services.l1l2_agent.tools.vector_search import search_tickets  # noqa: E402

log = structlog.get_logger()

SYSTEM_INSTRUCTION = """\
You are an L1/L2 technical support assistant. Help engineers find solutions
by searching historical tickets.

RULES:
1. Always call search_tickets first. Use the business_units provided in the
   message context — never search without scoping to a business unit.
   (search_tickets already applies keyword reranking; do not call a second
   search-only tool for ordering.)
   Only pass ticket_type_filter when the user explicitly asks for a Jira work
   type (e.g. "only bugs", "incident tickets"). For broad questions like
   "refund issues" or "login problems", omit ticket_type_filter — the word
   "issues" does not mean ticket type Bug.
2. If the engineer mentions a specific ticket ID (e.g. B1-1234), call
   fetch_jira_ticket directly — do not search.
3. If they only ask about status, call check_ticket_status.
4. After gathering results, write a clear technical answer yourself —
   cite specific ticket IDs, explain what was done to fix similar issues,
   and suggest next steps. Never dump raw JSON.
5. If results have low relevance (score < 0.6), mention this and suggest
   rephrasing or checking the business unit selection.

Be concise and technical. Engineers don't want filler text.\
"""

agent = LlmAgent(
    name="l1l2_resolution_agent",
    model="gemini-2.5-flash",
    description=(
        "Searches historical support tickets to help L1/L2 engineers "
        "find solutions to technical issues"
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        search_tickets,
        fetch_jira_ticket,
        check_ticket_status,
    ],
)

log.info("l1l2_agent.loaded", model="gemini-2.5-flash", tool_count=len(agent.tools))
