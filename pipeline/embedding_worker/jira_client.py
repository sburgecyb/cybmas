"""JIRA REST API v3 client for the embedding pipeline.

Uses httpx.AsyncClient with Basic auth (email + API token).
All methods raise JIRAClientError on non-2xx responses.
"""
import os
from datetime import datetime
from pathlib import Path
from types import TracebackType
from urllib.parse import urlparse

import httpx
import structlog
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env.local")
load_dotenv(".env.local")

log = structlog.get_logger()


def _env_clean(value: str) -> str:
    """Strip whitespace and BOM — Secret Manager values often end with \\n."""
    return (value or "").strip().strip("\ufeff")


# Fields requested on every issue fetch — keeps payloads small
_ISSUE_FIELDS = (
    "summary,description,status,resolution,"
    "comment,issuetype,priority,created,updated,labels,project"
)


def _issue_field_names() -> list[str]:
    """Field ids for /rest/api/3/search/jql ``fields`` array."""
    names = [f.strip() for f in _ISSUE_FIELDS.replace("\n", "").split(",") if f.strip()]
    extra = (os.getenv("JIRA_BUSINESS_UNIT_FIELD_ID") or "").strip()
    if extra and extra not in names:
        names.append(extra)
    return names


# ── Exception ──────────────────────────────────────────────────────────────────


class JIRAClientError(Exception):
    """Raised when a JIRA API call fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code:
            return f"[HTTP {self.status_code}] {super().__str__()}"
        return super().__str__()


# ── Client ─────────────────────────────────────────────────────────────────────


class JIRAClient:
    """Async JIRA REST API v3 client.

    Usage (preferred — ensures the underlying httpx client is always closed):

        async with JIRAClient() as client:
            ticket = await client.get_ticket("PROJ-123")
    """

    def __init__(self) -> None:
        required = ("JIRA_BASE_URL", "JIRA_API_TOKEN", "JIRA_USER_EMAIL")
        missing = [k for k in required if not _env_clean(os.getenv(k, ""))]
        if missing:
            raise JIRAClientError(
                "Missing environment variables: "
                + ", ".join(missing)
                + " (set on Cloud Run orchestrator — deploy/README.md § JIRA live API)",
            )
        base_url: str = _env_clean(os.environ["JIRA_BASE_URL"]).rstrip("/")
        api_token: str = _env_clean(os.environ["JIRA_API_TOKEN"])
        user_email: str = _env_clean(os.environ["JIRA_USER_EMAIL"])

        self._client = httpx.AsyncClient(
            base_url=base_url,
            auth=(user_email, api_token),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._log = log.bind(service="jira_client")

        parsed = urlparse(base_url)
        self._log.info(
            "jira_client.initialized",
            api_host=parsed.netloc or "?",
            scheme=parsed.scheme or "?",
            email_domain=user_email.split("@", 1)[-1] if "@" in user_email else "?",
        )

        # Cloud expects https://yourcompany.atlassian.net — not .../jira or a board URL.
        low = base_url.lower()
        if "atlassian.net" in low and ("/jira" in low or low.endswith("jira")):
            self._log.warning(
                "jira_client.base_url_suspicious",
                base_url=base_url,
                hint="Use site root only, e.g. https://yourcompany.atlassian.net",
            )

    # ── Context manager support ────────────────────────────────────────────────

    async def __aenter__(self) -> "JIRAClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Execute a GET request and return the parsed JSON body.

        Raises:
            JIRAClientError: on any non-2xx response.
        """
        try:
            response = await self._client.get(path, params=params)
        except httpx.RequestError as exc:
            raise JIRAClientError(f"Network error calling {path}: {exc}") from exc

        if response.status_code == 404:
            raise JIRAClientError(f"Not found: {path}", status_code=404)

        if response.is_error:
            raise JIRAClientError(
                f"JIRA API error on {path}: {response.text}",
                status_code=response.status_code,
            )

        return response.json()  # type: ignore[return-value]

    async def _post_json(self, path: str, body: dict) -> dict:
        """Execute a POST with JSON body and return the parsed JSON body."""
        try:
            response = await self._client.post(path, json=body)
        except httpx.RequestError as exc:
            raise JIRAClientError(f"Network error calling {path}: {exc}") from exc

        if response.status_code == 404:
            raise JIRAClientError(f"Not found: {path}", status_code=404)

        if response.is_error:
            raise JIRAClientError(
                f"JIRA API error on {path}: {response.text}",
                status_code=response.status_code,
            )

        return response.json()  # type: ignore[return-value]

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_ticket(self, jira_id: str) -> dict:
        """Fetch a single JIRA issue by its key.

        Args:
            jira_id: JIRA issue key, e.g. ``"PROJ-123"``.

        Returns:
            Full JIRA issue dict as returned by the API.

        Raises:
            JIRAClientError: if the issue is not found (404) or the request fails.
        """
        self._log.info("jira_client.get_ticket", jira_id=jira_id)
        path = f"/rest/api/3/issue/{jira_id}"
        try:
            return await self._get(path, params={"fields": _ISSUE_FIELDS})
        except JIRAClientError as exc:
            if exc.status_code != 404:
                raise
            site = str(self._client.base_url).rstrip("/")
            raise JIRAClientError(
                f"Issue {jira_id!r} not found at {site}. "
                "Verify: (1) JIRA_BASE_URL is exactly the site root you use in the browser "
                "(e.g. https://yourcompany.atlassian.net with no /jira path); "
                "(2) the issue key exists on that site; "
                "(3) the Atlassian account for JIRA_USER_EMAIL can open this issue — "
                "JIRA Cloud often returns 404 (not 403) when the user cannot browse the issue.",
                status_code=404,
            ) from exc

    async def search_tickets(
        self,
        jql: str,
        start_at: int = 0,
        max_results: int = 100,
    ) -> dict:
        """Search JIRA issues using JQL (paginates until all results are read).

        Uses ``POST /rest/api/3/search/jql`` — the legacy ``GET /rest/api/3/search``
        endpoint returns HTTP 410 on Jira Cloud.

        Args:
            jql: JQL query string.
            start_at: Ignored (legacy offset pagination; new API uses page tokens).
            max_results: Page size per request (capped at 100).

        Returns:
            Dict with keys ``issues`` (list), ``total`` (int), ``startAt`` (always 0).
        """
        self._log.info(
            "jira_client.search_tickets",
            jql=jql,
            start_at=start_at,
            max_results=max_results,
        )
        page_size = min(max(1, max_results), 100)
        all_issues: list[dict] = []
        next_token: str | None = None

        while True:
            payload: dict = {
                "jql": jql,
                "maxResults": page_size,
                "fields": _issue_field_names(),
            }
            if next_token:
                payload["nextPageToken"] = next_token

            data = await self._post_json("/rest/api/3/search/jql", payload)
            batch: list[dict] = data.get("issues") or []
            all_issues.extend(batch)

            if data.get("isLast") or not batch:
                break
            next_token = data.get("nextPageToken")
            if not next_token:
                break

        return {
            "issues": all_issues,
            "total": len(all_issues),
            "startAt": 0,
        }

    async def get_updated_since(
        self,
        since: datetime,
        project_keys: list[str],
    ) -> list[dict]:
        """Fetch all issues from the given projects updated on or after ``since``.

        Paginates automatically until all matching issues are retrieved.

        Args:
            since: Only return issues updated at or after this datetime (UTC).
            project_keys: JIRA project keys to scope the query. If empty, every
                project the authenticated user can browse is included (no
                ``project in (...)`` clause).

        Returns:
            Flat list of all matching JIRA issue dicts.
        """
        since_str = since.strftime("%Y-%m-%d %H:%M")
        if project_keys:
            keys_jql = ", ".join(project_keys)
            jql = (
                f'project in ({keys_jql}) AND updated >= "{since_str}" '
                f"ORDER BY updated ASC"
            )
        else:
            jql = f'updated >= "{since_str}" ORDER BY updated ASC'

        page = await self.search_tickets(jql, max_results=100)
        all_issues: list[dict] = page.get("issues", [])
        self._log.info(
            "jira_client.paginate",
            fetched=len(all_issues),
            total=page.get("total", 0),
        )
        return all_issues

    async def get_issue_comments(self, jira_id: str) -> list[dict]:
        """Fetch the comments for a JIRA issue.

        Args:
            jira_id: JIRA issue key, e.g. ``"PROJ-123"``.

        Returns:
            List of dicts with keys ``author`` (str), ``body`` (str, plain text),
            ``created`` (str ISO-8601).
        """
        self._log.info("jira_client.get_comments", jira_id=jira_id)
        data = await self._get(f"/rest/api/3/issue/{jira_id}/comment")
        comments: list[dict] = data.get("comments", [])

        return [
            {
                "author": comment.get("author", {}).get("displayName", "Unknown"),
                "body": self.extract_plain_text(comment.get("body")),
                "created": comment.get("created", ""),
            }
            for comment in comments
        ]

    # ── ADF → plain text ───────────────────────────────────────────────────────

    def extract_plain_text(self, node: "dict | str | None") -> str:
        """Recursively convert a JIRA Atlassian Document Format (ADF) node to plain text.

        JIRA description and comment bodies are returned as ADF (nested JSON).
        This method walks the tree and concatenates all text content.

        Args:
            node: An ADF node dict, a raw string, or ``None``.

        Returns:
            Plain text string with basic whitespace formatting preserved.
        """
        if node is None:
            return ""
        if isinstance(node, str):
            return node

        node_type: str = node.get("type", "")
        parts: list[str] = []

        # Leaf text node
        if node_type == "text":
            return node.get("text", "")

        # Inline nodes with text in attrs
        if node_type in ("mention", "emoji", "inlineCard"):
            attrs = node.get("attrs", {})
            return attrs.get("text", attrs.get("url", ""))

        # Hard break
        if node_type == "hardBreak":
            return "\n"

        # Recurse into content children
        for child in node.get("content", []):
            parts.append(self.extract_plain_text(child))

        text = "".join(parts)

        # Add trailing newline for block-level nodes to preserve readability
        if node_type in (
            "paragraph",
            "heading",
            "blockquote",
            "listItem",
            "codeBlock",
            "panel",
        ):
            text = text.rstrip(" ") + "\n"

        return text
