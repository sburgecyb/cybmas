"""Ticket and incident data processors for the embedding pipeline.

Provides two responsibilities:
  1. normalize_* — flatten raw JIRA API issue dicts into the schema used by
     the rest of the pipeline (upsert, embedder).
  2. prepare_*_text — build the plain-text string that gets embedded.
"""

# ── ADF helper (local; avoids importing JIRAClient) ───────────────────────────


def _adf_to_text(node: "dict | str | None") -> str:
    """Recursively convert an Atlassian Document Format node to plain text.

    Args:
        node: ADF node dict, a raw string, or None.

    Returns:
        Plain text with block-level newlines preserved.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node

    node_type: str = node.get("type", "")

    if node_type == "text":
        return node.get("text", "")

    if node_type in ("mention", "emoji", "inlineCard"):
        attrs: dict = node.get("attrs", {})
        return attrs.get("text", attrs.get("url", ""))

    if node_type == "hardBreak":
        return "\n"

    parts = [_adf_to_text(child) for child in node.get("content", [])]
    text = "".join(parts)

    if node_type in ("paragraph", "heading", "blockquote", "listItem", "codeBlock", "panel"):
        text = text.rstrip(" ") + "\n"

    return text


def _extract_comments(raw_comments: list[dict]) -> list[dict]:
    """Normalise JIRA comment objects into plain-text dicts.

    Args:
        raw_comments: List of JIRA API comment objects.

    Returns:
        List of ``{"author": str, "body": str, "created": str}`` dicts.
    """
    result: list[dict] = []
    for c in raw_comments:
        result.append(
            {
                "author": (c.get("author") or {}).get("displayName", "Unknown"),
                "body": _adf_to_text(c.get("body")),
                "created": c.get("created", ""),
            }
        )
    return result


# ── Normalisation ──────────────────────────────────────────────────────────────


def normalize_ticket(raw: dict, business_unit: str) -> dict:
    """Flatten a raw JIRA API issue into the pipeline's internal ticket format.

    Args:
        raw: Full JIRA issue dict as returned by the API (with ``fields`` key).
        business_unit: BU code derived from the issue's project key.

    Returns:
        Flat dict compatible with ``prepare_ticket_text`` and ``upsert_ticket``.
    """
    fields: dict = raw.get("fields") or {}
    comments_raw: list[dict] = (fields.get("comment") or {}).get("comments", [])

    return {
        "jira_id": raw.get("key", ""),
        "business_unit": business_unit,
        "ticket_type": (fields.get("issuetype") or {}).get("name", ""),
        "summary": fields.get("summary", ""),
        "description": _adf_to_text(fields.get("description")),
        "status": (fields.get("status") or {}).get("name", ""),
        "resolution": (fields.get("resolution") or {}).get("name", ""),
        "discussion": _extract_comments(comments_raw),
        "created_at": fields.get("created"),
        "updated_at": fields.get("updated"),
        "raw_json": raw,
    }


def normalize_incident(raw: dict, business_unit: str) -> dict:
    """Flatten a raw JIRA incident issue into the pipeline's internal incident format.

    Args:
        raw: Full JIRA issue dict as returned by the API (with ``fields`` key).
        business_unit: BU code derived from the issue's project key.

    Returns:
        Flat dict compatible with ``prepare_incident_text`` and ``upsert_incident``.
    """
    fields: dict = raw.get("fields") or {}

    # Linked tickets: parse from JIRA issue links
    related: list[str] = []
    for link in fields.get("issuelinks", []):
        linked = link.get("outwardIssue") or link.get("inwardIssue") or {}
        if linked.get("key"):
            related.append(linked["key"])

    # Severity: JIRA doesn't have a native severity field; check priority and labels
    priority_name: str = (fields.get("priority") or {}).get("name", "")
    labels: list[str] = fields.get("labels", [])
    severity = priority_name or (labels[0] if labels else "")

    return {
        "jira_id": raw.get("key", ""),
        "business_unit": business_unit,
        "title": fields.get("summary", ""),
        "description": _adf_to_text(fields.get("description")),
        "root_cause": _adf_to_text(fields.get("root_cause")),
        "long_term_fix": _adf_to_text(fields.get("long_term_fix")),
        "related_tickets": related,
        "severity": severity,
        "resolved_at": (fields.get("resolutiondate")),
        "created_at": fields.get("created"),
        "updated_at": fields.get("updated"),
        "raw_json": raw,
    }


# ── Text preparation ───────────────────────────────────────────────────────────

_MAX_OUTPUT_CHARS: int = 3000


def prepare_ticket_text(ticket: dict) -> str:
    """Build the embedding input string for a ticket.

    Args:
        ticket: Normalised ticket dict (output of ``normalize_ticket``).

    Returns:
        Plain text string, truncated to 3000 characters.
    """
    parts: list[str] = [
        f"Issue: {ticket.get('summary', '')}",
        f"Type: {ticket.get('ticket_type', '')} | Status: {ticket.get('status', '')}",
    ]

    description: str = ticket.get("description", "") or ""
    if description.strip():
        parts.append(f"Description: {description[:1500]}")

    resolution: str = ticket.get("resolution", "") or ""
    if resolution.strip():
        parts.append(f"Resolution: {resolution}")

    discussion: list[dict] = ticket.get("discussion") or []
    for comment in discussion[-3:]:
        body: str = (comment.get("body", "") or "")[:300]
        if body.strip():
            parts.append(f"Comment: {body}")

    return "\n\n".join(parts)[:_MAX_OUTPUT_CHARS]


def prepare_incident_text(incident: dict) -> str:
    """Build the embedding input string for an incident.

    Args:
        incident: Normalised incident dict (output of ``normalize_incident``).

    Returns:
        Plain text string, truncated to 3000 characters.
    """
    parts: list[str] = [
        f"Incident: {incident.get('title', '')}",
        f"Severity: {incident.get('severity', '')}",
    ]

    description: str = incident.get("description", "") or ""
    if description.strip():
        parts.append(f"Description: {description[:1000]}")

    root_cause: str = incident.get("root_cause", "") or ""
    if root_cause.strip():
        parts.append(f"Root Cause: {root_cause}")

    long_term_fix: str = incident.get("long_term_fix", "") or ""
    if long_term_fix.strip():
        parts.append(f"Long-term Fix: {long_term_fix}")

    return "\n\n".join(parts)[:_MAX_OUTPUT_CHARS]
