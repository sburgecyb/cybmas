"""L1/L2 Resolution Agent — ADK LlmAgent definition.

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

from services.l1l2_agent.tools.jira_fetch import (  # noqa: E402
    check_ticket_status,
    fetch_jira_ticket,
)
from services.l1l2_agent.tools.rerank import rerank_results  # noqa: E402
from services.l1l2_agent.tools.vector_search import search_tickets  # noqa: E402
from services.shared.skills.summarize import summarize_search_results  # noqa: E402

log = structlog.get_logger()

# ── System instruction ─────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION = """You are an L1/L2 technical support assistant for a \
multi-agent agentic platform. Your role is to help support engineers find \
solutions to technical issues by searching historical tickets.

When an engineer asks a question:

1. ALWAYS use search_tickets first with the provided business_units scope
2. After searching, use rerank_results to improve result ordering
3. If the engineer mentions a specific ticket ID (pattern like B1-1234 or \
INC-001), use fetch_jira_ticket directly instead of searching
4. If they ask about ticket status only, use check_ticket_status
5. ALWAYS use summarize_search_results after retrieving results to provide \
a coherent answer — never return raw results directly
6. If search returns low relevance results (score < 0.6), try a rephrased query
7. Always cite ticket IDs in your response e.g. "See B1-1008 for reference"
8. If no relevant results found, say so clearly and suggest:
   - Try different keywords
   - Check if the correct business unit is selected
   - The issue may not have been seen before

You are precise, technical and concise. Engineers don't want filler text."""

# ── Agent ──────────────────────────────────────────────────────────────────────

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
        rerank_results,
        fetch_jira_ticket,
        check_ticket_status,
        summarize_search_results,
    ],
)

log.info("l1l2_agent.loaded", model="gemini-2.5-flash", tool_count=len(agent.tools))
