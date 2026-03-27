"""Orchestrator Agent — ADK LlmAgent with sub-agents.

Routes engineer queries to the correct specialist agent (L1/L2, L3, or
Session) using ADK's sub_agents delegation mechanism.
"""
import os
import sys

import structlog
from dotenv import load_dotenv
from google.adk.agents import LlmAgent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(".env.local")

from services.l1l2_agent.agent import agent as l1l2_agent  # noqa: E402
from services.l3_agent.agent import agent as l3_agent  # noqa: E402
from services.session_agent.agent import agent as session_agent  # noqa: E402

log = structlog.get_logger()

# ── System instruction ─────────────────────────────────────────────────────────

ORCHESTRATOR_INSTRUCTION = """\
You are the orchestration layer of a multi-agent technical support platform. \
Your role is to route engineer queries to the right specialist agent and \
ensure coherent multi-turn conversations.

You have access to three specialist agents:
- l1l2_resolution_agent: handles ticket search, JIRA lookups, status queries \
for L1/L2 support engineers
- l3_resolutions_agent: handles incident management, RCA search, \
cross-referencing incidents with tickets for L3 engineers
- session_feedback_agent: handles session persistence and feedback

Routing rules:
1. If query mentions a specific ticket ID (e.g. B1-1234) → l1l2_resolution_agent
2. If query asks about ticket status → l1l2_resolution_agent
3. If Incident Management is active AND query is about incidents, outages, \
RCAs or root causes → l3_resolutions_agent
4. If query involves both incidents AND tickets (cross-reference) → l3_resolutions_agent
5. For general ticket search → l1l2_resolution_agent
6. For session management → session_feedback_agent
7. For completely unrelated queries → politely decline and ask for a \
support-related question

Always delegate to a specialist agent — never answer engineering questions yourself. \
The engineer has already selected their business unit scope — pass it through.\
"""

# ── Agent ──────────────────────────────────────────────────────────────────────

agent = LlmAgent(
    name="orchestrator",
    model="gemini-2.5-flash",
    description="Routes support engineer queries to the appropriate specialist agent",
    instruction=ORCHESTRATOR_INSTRUCTION,
    sub_agents=[l1l2_agent, l3_agent, session_agent],
)

log.info(
    "orchestrator.loaded",
    model="gemini-2.5-flash",
    sub_agents=[a.name for a in agent.sub_agents],
)
