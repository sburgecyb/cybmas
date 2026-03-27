"""Tool: check the current status of a JIRA ticket."""
from google.adk.tools import tool

@tool
async def ticket_status(ticket_key: str) -> dict:
    """Return the current status, assignee, and priority of a JIRA ticket.

    Args:
        ticket_key: The JIRA issue key.
    """
    # TODO: lightweight JIRA status fetch
    raise NotImplementedError
