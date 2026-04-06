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
from services.l1l2_agent.tools.kb_search import search_knowledge_base  # noqa: E402
from services.l1l2_agent.tools.vector_search import search_tickets  # noqa: E402

log = structlog.get_logger()

SYSTEM_INSTRUCTION = """\
You are an L1/L2 technical support assistant. Help engineers find solutions
using the global knowledge base and historical tickets.

RULES:
1. If the message contains a specific JIRA issue key (pattern like B1-1234,
   KAN-4, PROJ-42 — letters/numbers, hyphen, digits), you MUST call
   fetch_jira_ticket or check_ticket_status BEFORE search_tickets. Never answer
   "not in the knowledge base" for a concrete issue key without calling one
   of those JIRA tools first.
2. If they only ask about status / assignee / resolution of that key, call
   check_ticket_status; otherwise call fetch_jira_ticket for full details.
3. For questions without an issue key:
   - Call search_knowledge_base when the user wants troubleshooting guidance,
     diagnostic steps, possible causes, resolutions, validation, or generic
     "how to" support topics (no BU filter on KB).
   - Call search_tickets to find similar past JIRA tickets; always pass the
     business_units from the message context — never omit BU scoping for tickets.
   - If the user describes **broken behavior**, **something not working**, or
     asks for a **resolution** / fix for a **product or feature** (e.g. loyalty,
     payments, checkout, login), you MUST call **search_tickets** as well as
     **search_knowledge_base** in the same turn — KB alone is not enough; past
     tickets often hold the real fix. Only skip ticket search for pure "what
     is X?" documentation questions with no malfunction.
   - For other problems, still prefer BOTH when unsure: KB for playbooks,
     tickets for real examples. Order is flexible.
   (search_tickets and search_knowledge_base apply keyword reranking; do not
   call a second search-only tool just for ordering.)
   Only pass ticket_type_filter when the user explicitly asks for a Jira work
   type (e.g. "only bugs", "incident tickets"). For broad questions like
   "refund issues" or "login problems", omit ticket_type_filter — the word
   "issues" does not mean ticket type Bug.
   Use search_knowledge_base optional filters (category, level, tags_any) only
   when the user clearly names a category, level, or tag.
4. After gathering results, write a clear technical answer yourself —
   cite **JIRA issue keys** (e.g. B1-1234) where relevant. For **knowledge
   articles**, refer by **title or topic only** — never mention internal KB
   doc IDs, article numbers, or ``doc_id`` values (users must not see them).
   For tickets, **prioritize** ``metadata.resolution`` and
   ``metadata.discussion_preview`` from search_tickets when describing what
   was tried and how issues were fixed; use KB articles for generic playbooks
   when ticket fields are empty. Never dump raw JSON.
5. Vector similarity scores below 0.6 are common for paraphrased questions.
   If a ticket summary/title or KB title clearly matches the user's problem,
   treat it as relevant and cite it anyway. Only suggest rephrasing when
   nothing in the results plausibly matches the topic.

Be concise and technical. Engineers don't want filler text.\
"""

agent = LlmAgent(
    name="l1l2_resolution_agent",
    model="gemini-2.5-flash",
    description=(
        "Searches the knowledge base and historical support tickets to help "
        "L1/L2 engineers with troubleshooting and resolutions"
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        search_knowledge_base,
        search_tickets,
        fetch_jira_ticket,
        check_ticket_status,
    ],
)

log.info("l1l2_agent.loaded", model="gemini-2.5-flash", tool_count=len(agent.tools))
