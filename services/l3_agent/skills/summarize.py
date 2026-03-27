"""Skill: summarise incident details and RCA into a structured brief."""
from google.adk.tools import tool

@tool
async def summarize_incident(incident: dict, rca: dict) -> str:
    """Produce a concise incident brief combining incident details and RCA.

    Args:
        incident: Incident dict with keys: id, title, severity, timeline.
        rca: RCA dict with keys: root_cause, contributing_factors, remediation.
    """
    # TODO: call Gemini 1.5 Flash via Vertex AI
    raise NotImplementedError
