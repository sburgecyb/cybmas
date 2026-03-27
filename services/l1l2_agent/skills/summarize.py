"""Skill: summarise a list of tickets into actionable resolution steps."""
from google.adk.tools import tool

@tool
async def summarize_tickets(tickets: list[dict]) -> str:
    """Produce a concise resolution summary from a list of similar past tickets.

    Args:
        tickets: List of ticket dicts with keys: key, summary, resolution.
    """
    # TODO: call Gemini 1.5 Flash via Vertex AI to summarise
    raise NotImplementedError
