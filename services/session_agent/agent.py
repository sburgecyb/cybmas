"""Session & Feedback Agent — ADK LlmAgent definition.

Manages chat session persistence and engineer feedback collection.
All tool functions are plain async callables — no @tool decorator
is required in ADK 1.27.5+.
"""
import os
import sys

import structlog
from dotenv import load_dotenv
from google.adk.agents import LlmAgent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv(".env.local")

from services.session_agent.tools.feedback_store import (  # noqa: E402
    get_feedback_summary,
    save_feedback,
)
from services.session_agent.tools.session_store import (  # noqa: E402
    list_engineer_sessions,
    load_session,
    save_session,
)

log = structlog.get_logger()

# ── Agent ──────────────────────────────────────────────────────────────────────

agent = LlmAgent(
    name="session_feedback_agent",
    model="gemini-2.5-flash",
    description=(
        "Manages chat session persistence and engineer feedback collection"
    ),
    instruction="""\
You manage chat sessions and feedback for the support platform.

Use save_session to persist conversations after each exchange.
Use load_session to resume a previous conversation by ID.
Use list_engineer_sessions to show an engineer their history.
Use save_feedback when an engineer rates a response.
Use get_feedback_summary for admin analytics on response quality.\
""",
    tools=[
        save_session,
        load_session,
        list_engineer_sessions,
        save_feedback,
        get_feedback_summary,
    ],
)

log.info("session_agent.loaded", model="gemini-2.5-flash", tool_count=len(agent.tools))
