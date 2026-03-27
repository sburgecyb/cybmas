# Cursor Build Prompts — Phase 2: Agent Services

---
## prompt 2.1 by claude
Refer to .cursorrules for all conventions. Create the ADK tools for the L1/L2 
Resolution Agent.

Create these files:

1. services/l1l2-agent/__init__.py (empty)
2. services/l1l2-agent/tools/__init__.py (empty)

3. services/l1l2-agent/tools/vector_search.py

Imports:
- google.adk.tools tool decorator
- asyncpg
- structlog
- time
- sys, os
sys.path.insert(0, '.')
from pipeline.embedding_worker.embedder import embed_text
from services.shared.models import ToolResult, SearchResult

Module-level:
- Initialise structlog logger

@tool
async def search_tickets(
    query_text: str,
    business_units: list[str],
    top_k: int = 10,
    ticket_type_filter: str = None
) -> dict:
    """Search historical support tickets by semantic similarity.

    Use this tool when an engineer describes a problem and needs to find
    similar past tickets. Always provide business_units to scope the search.

    Args:
        query_text: Description of the problem to search for
        business_units: List of business unit codes to search within e.g. ['B1', 'B2']
        top_k: Number of results to return (default 10, max 50)
        ticket_type_filter: Optional filter by ticket type e.g. 'BUG', 'INCIDENT'

    Returns:
        Dictionary with success status and list of matching tickets with scores
    """
    start = time.time()
    try:
        # Get DB pool from app state
        from services.l1l2_agent.main import get_db_pool
        pool = await get_db_pool()

        # Generate query embedding
        query_vector = await embed_text(query_text)

        # Build SQL query
        sql = """
            SELECT 
                jira_id, summary, description, resolution, 
                status, business_unit, ticket_type,
                1 - (embedding <=> $1::vector) AS score
            FROM tickets
            WHERE business_unit = ANY($2)
            AND ($3::text IS NULL OR ticket_type = $3)
            ORDER BY embedding <=> $1::vector
            LIMIT $4
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                sql,
                str(query_vector),
                business_units,
                ticket_type_filter,
                top_k
            )

        results = [
            SearchResult(
                jira_id=row['jira_id'],
                title=row['summary'],
                summary=row['description'][:200] if row['description'] else None,
                score=float(row['score']),
                result_type='ticket',
                status=row['status'],
                business_unit=row['business_unit']
            ).model_dump()
            for row in rows
        ]

        latency = round((time.time() - start) * 1000)
        logger.info("search_tickets_complete",
                    query_length=len(query_text),
                    business_units=business_units,
                    result_count=len(results),
                    latency_ms=latency)

        return ToolResult(success=True, data=results).model_dump()

    except Exception as e:
        logger.error("search_tickets_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


4. services/l1l2-agent/tools/rerank.py

Imports:
- google.adk.tools tool decorator
- structlog
from services.shared.models import ToolResult, SearchResult

@tool
def rerank_results(
    query_text: str,
    results: list[dict],
    top_n: int = 5
) -> dict:
    """Re-rank search results by relevance to the query.

    Use this tool after search_tickets to improve result ordering.
    Combines vector score with keyword overlap and recency.

    Args:
        query_text: The original search query
        results: List of SearchResult dicts from search_tickets
        top_n: Number of top results to return after reranking

    Returns:
        Dictionary with reranked results list
    """
    try:
        if not results:
            return ToolResult(success=True, data=[]).model_dump()

        query_words = set(query_text.lower().split())

        def score_result(r: dict) -> float:
            # Base vector score (0-1)
            base_score = r.get('score', 0)

            # Keyword overlap bonus
            title = (r.get('title') or '').lower()
            summary = (r.get('summary') or '').lower()
            text = title + ' ' + summary
            text_words = set(text.split())
            overlap = len(query_words & text_words)
            keyword_bonus = min(overlap * 0.02, 0.1)

            # Resolved ticket bonus
            status_bonus = 0.05 if r.get('status') == 'Resolved' else 0

            return base_score + keyword_bonus + status_bonus

        reranked = sorted(results, key=score_result, reverse=True)
        return ToolResult(success=True, data=reranked[:top_n]).model_dump()

    except Exception as e:
        logger.error("rerank_failed", error=str(e))
        return ToolResult(success=True, data=results[:top_n]).model_dump()


5. services/l1l2-agent/tools/jira_fetch.py

Imports:
- google.adk.tools tool decorator
- asyncio, json, os
- redis.asyncio as redis
- structlog
sys.path.insert(0, '.')
from pipeline.embedding_worker.jira_client import JIRAClient, JIRAClientError
from services.shared.models import ToolResult

@tool
async def fetch_jira_ticket(jira_id: str) -> dict:
    """Fetch full details of a specific JIRA ticket by its ID.

    Use this tool when an engineer mentions a specific ticket ID like B1-1234
    or wants to see the full details of a known ticket.

    Args:
        jira_id: The JIRA ticket ID e.g. 'B1-1234'

    Returns:
        Dictionary with ticket details including summary, status, 
        description, resolution and recent comments
    """
    try:
        # Check Redis cache first
        redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://127.0.0.1:6379'))
        cache_key = f"jira:ticket:{jira_id}"
        cached = await redis_client.get(cache_key)

        if cached:
            logger.info("jira_fetch_cache_hit", jira_id=jira_id)
            await redis_client.aclose()
            return ToolResult(success=True, data=json.loads(cached)).model_dump()

        async with JIRAClient() as client:
            issue = await client.get_ticket(jira_id)
            fields = issue.get('fields', {})

            # Extract plain text from ADF description
            description = client.extract_plain_text(fields.get('description'))

            # Get last 5 comments
            comments_data = fields.get('comment', {}).get('comments', [])[-5:]
            comments = [
                {
                    'author': c.get('author', {}).get('displayName', 'Unknown'),
                    'body': client.extract_plain_text(c.get('body')),
                    'created': c.get('created')
                }
                for c in comments_data
            ]

            result = {
                'jira_id': jira_id,
                'summary': fields.get('summary'),
                'status': fields.get('status', {}).get('name'),
                'assignee': fields.get('assignee', {}).get('displayName') if fields.get('assignee') else None,
                'reporter': fields.get('reporter', {}).get('displayName') if fields.get('reporter') else None,
                'priority': fields.get('priority', {}).get('name') if fields.get('priority') else None,
                'issue_type': fields.get('issuetype', {}).get('name') if fields.get('issuetype') else None,
                'created': fields.get('created'),
                'updated': fields.get('updated'),
                'description': description[:2000] if description else None,
                'resolution': client.extract_plain_text(fields.get('resolution', {}).get('description') if fields.get('resolution') else None),
                'comments': comments
            }

            # Cache for 5 minutes
            await redis_client.setex(cache_key, 300, json.dumps(result))
            await redis_client.aclose()

            logger.info("jira_fetch_success", jira_id=jira_id)
            return ToolResult(success=True, data=result).model_dump()

    except JIRAClientError as e:
        return ToolResult(
            success=False,
            error=f"Ticket {jira_id} not found or inaccessible: {str(e)}"
        ).model_dump()
    except Exception as e:
        logger.error("jira_fetch_failed", jira_id=jira_id, error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


@tool
async def check_ticket_status(jira_id: str) -> dict:
    """Check the current status of a JIRA ticket.

    Use this tool when an engineer asks about the status of a specific ticket.
    Lighter than fetch_jira_ticket - only returns status, assignee and last update.

    Args:
        jira_id: The JIRA ticket ID e.g. 'B1-1234'

    Returns:
        Dictionary with status, assignee and last updated date
    """
    try:
        redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://127.0.0.1:6379'))
        cache_key = f"jira:status:{jira_id}"
        cached = await redis_client.get(cache_key)

        if cached:
            await redis_client.aclose()
            return ToolResult(success=True, data=json.loads(cached)).model_dump()

        async with JIRAClient() as client:
            issue = await client.get_ticket(jira_id)
            fields = issue.get('fields', {})

            result = {
                'jira_id': jira_id,
                'status': fields.get('status', {}).get('name'),
                'assignee': fields.get('assignee', {}).get('displayName') if fields.get('assignee') else 'Unassigned',
                'last_updated': fields.get('updated'),
                'priority': fields.get('priority', {}).get('name') if fields.get('priority') else None
            }

            # Cache for 2 minutes
            await redis_client.setex(cache_key, 120, json.dumps(result))
            await redis_client.aclose()

            return ToolResult(success=True, data=result).model_dump()

    except Exception as e:
        return ToolResult(success=False, error=str(e)).model_dump()
		
In ADK 1.27.5, tools are plain Python functions — there is no @tool decorator. 
Remove all @tool decorator imports and usages from these files:

- services/l1l2_agent/tools/vector_search.py
- services/l1l2_agent/tools/rerank.py  
- services/l1l2_agent/tools/jira_fetch.py

Specifically:
1. Remove the line: from google.adk.tools import tool
2. Remove the @tool decorator above each function definition
3. Keep everything else exactly the same — function signatures, 
   docstrings, and implementation unchanged

The functions are passed directly to LlmAgent(tools=[search_tickets, rerank_results, ...])
ADK reads the function name and docstring automatically.
---

## PROMPT 2.1 — ADK Tools: Vector Search & JIRA Fetch

```
Create the shared ADK tools used by both L1/L2 and L3 agents.

Create services/l1l2-agent/tools/vector_search.py:

Tool: search_tickets
- Input model: SearchTicketsInput
  - query_text: str
  - business_units: list[str]  # required — never search all BUs
  - top_k: int = 10
  - ticket_type_filter: str | None  # BUG, INCIDENT, TASK etc.
- Output: ToolResult with data = list[SearchResult]
- Implementation:
  1. Generate query embedding via embed_text() from embedder.py (Vertex AI text-embedding-004, 768-dim)
  2. pgvector cosine similarity search:
     SELECT jira_id, summary, description, resolution, status, business_unit,
            1 - (embedding <=> $1::vector) AS score
     FROM tickets
     WHERE business_unit = ANY($2)
       AND ($3 IS NULL OR ticket_type = $3)
     ORDER BY embedding <=> $1::vector
     LIMIT $4
  3. Return top_k results as SearchResult list with score
- Use asyncpg connection from pool
- Log query, BU filter, result count, latency

Create services/l1l2-agent/tools/rerank.py:

Tool: rerank_results
- Input model: RerankInput
  - query_text: str
  - results: list[SearchResult]
  - top_n: int = 5
- Re-ranks the top-k vector search results by relevance to the query
- Implementation: score each result by computing keyword overlap + recency bonus
  (simple custom reranker — no external service needed for local dev)
  Production option: swap in Cohere Rerank API if RERANK_PROVIDER=cohere
- Returns top_n results re-ordered by combined score
- Falls back to original order if reranking fails (graceful degradation)

Create services/l1l2-agent/tools/jira_fetch.py:

Tool: fetch_jira_ticket
- Input model: FetchJiraInput
  - jira_id: str
- Output: ToolResult with full ticket data
- Calls JIRA REST API /rest/api/3/issue/{jira_id}
- Formats response: summary, status, assignee, reporter, priority, created, updated, description (plain text), comments (last 5)
- Cache response in Redis for 5 minutes (key: jira:ticket:{jira_id})

Tool: check_ticket_status
- Input: jira_id: str
- Output: ToolResult with status, assignee, last_updated
- Lightweight — only fetches status fields, no description
- Cache in Redis for 2 minutes
```

---
## prompt 2.3 by claude
Refer to .cursorrules for all conventions. Create the ADK tools for the L3 
Resolutions Agent.

Create these files:

1. services/l3_agent/__init__.py (empty)
2. services/l3_agent/tools/__init__.py (empty)

3. services/l3_agent/tools/incident_search.py

Imports:
- asyncpg, structlog, time, sys, os
- sys.path.insert(0, '.')
- from pipeline.embedding_worker.embedder import embed_text
- from services.shared.models import ToolResult, SearchResult

No decorator needed — plain async function.

async def search_incidents(
    query_text: str,
    business_units: list[str] = None,
    severity_filter: str = None,
    top_k: int = 10
) -> dict:
    """Search historical production incidents and RCAs by semantic similarity.

    Use this tool when an engineer asks about past incidents, outages, or 
    production issues. When business_units is None, searches across all BUs.

    Args:
        query_text: Description of the incident or issue to search for
        business_units: Optional list of BU codes to filter e.g. ['B1', 'B2'].
                       If None, searches all business units.
        severity_filter: Optional severity filter e.g. 'P1', 'P2', 'P3'
        top_k: Number of results to return (default 10)

    Returns:
        Dictionary with success status and list of matching incidents with scores
    """
    start = time.time()
    try:
        from services.l3_agent.main import get_db_pool
        pool = await get_db_pool()

        query_vector = await embed_text(query_text)

        # Build SQL — BU filter is optional for L3
        if business_units:
            sql = """
                SELECT 
                    jira_id, title, description, root_cause,
                    long_term_fix, severity, business_unit,
                    resolved_at,
                    1 - (embedding <=> $1::vector) AS score
                FROM incidents
                WHERE business_unit = ANY($2)
                AND ($3::text IS NULL OR severity = $3)
                ORDER BY embedding <=> $1::vector
                LIMIT $4
            """
            rows = await pool.fetch(sql, str(query_vector), 
                                   business_units, severity_filter, top_k)
        else:
            sql = """
                SELECT 
                    jira_id, title, description, root_cause,
                    long_term_fix, severity, business_unit,
                    resolved_at,
                    1 - (embedding <=> $1::vector) AS score
                FROM incidents
                WHERE ($2::text IS NULL OR severity = $2)
                ORDER BY embedding <=> $1::vector
                LIMIT $3
            """
            rows = await pool.fetch(sql, str(query_vector), 
                                   severity_filter, top_k)

        results = [
            SearchResult(
                jira_id=row['jira_id'],
                title=row['title'],
                summary=row['description'][:200] if row['description'] else None,
                score=float(row['score']),
                result_type='incident',
                status='Resolved' if row['resolved_at'] else 'Open',
                business_unit=row['business_unit'],
                metadata={
                    'root_cause': row['root_cause'],
                    'long_term_fix': row['long_term_fix'],
                    'severity': row['severity']
                }
            ).model_dump()
            for row in rows
        ]

        latency = round((time.time() - start) * 1000)
        logger.info("search_incidents_complete",
                    query_length=len(query_text),
                    business_units=business_units,
                    result_count=len(results),
                    latency_ms=latency)

        return ToolResult(success=True, data=results).model_dump()

    except Exception as e:
        logger.error("search_incidents_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


4. services/l3_agent/tools/rca_fetch.py

Imports:
- asyncpg, structlog, sys, os
- sys.path.insert(0, '.')
- from services.shared.models import ToolResult

async def fetch_incident_rca(incident_jira_id: str) -> dict:
    """Fetch the full Root Cause Analysis for a specific incident.

    Use this tool when an engineer wants to understand what caused an incident
    or what the long-term fix was. Requires a specific incident ID.

    Args:
        incident_jira_id: The JIRA ID of the incident e.g. 'INC-001' or 'B2-2004'

    Returns:
        Dictionary with full RCA details including root_cause, long_term_fix,
        severity, related_tickets and timeline
    """
    try:
        from services.l3_agent.main import get_db_pool
        pool = await get_db_pool()

        row = await pool.fetchrow(
            """
            SELECT jira_id, title, description, root_cause, long_term_fix,
                   related_tickets, severity, resolved_at, created_at,
                   business_unit
            FROM incidents
            WHERE jira_id = $1
            """,
            incident_jira_id
        )

        if not row:
            return ToolResult(
                success=False,
                error=f"Incident {incident_jira_id} not found in knowledge base"
            ).model_dump()

        result = {
            'jira_id': row['jira_id'],
            'title': row['title'],
            'description': row['description'],
            'root_cause': row['root_cause'] or 'RCA not yet documented',
            'long_term_fix': row['long_term_fix'] or 'Long-term fix not yet documented',
            'related_tickets': row['related_tickets'] or [],
            'severity': row['severity'],
            'business_unit': row['business_unit'],
            'resolved_at': str(row['resolved_at']) if row['resolved_at'] else None,
            'created_at': str(row['created_at']) if row['created_at'] else None
        }

        logger.info("rca_fetch_success", jira_id=incident_jira_id)
        return ToolResult(success=True, data=result).model_dump()

    except Exception as e:
        logger.error("rca_fetch_failed", jira_id=incident_jira_id, error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


5. services/l3_agent/tools/cross_ref_tickets.py

Imports:
- asyncpg, structlog, sys, os, json
- sys.path.insert(0, '.')
- from pipeline.embedding_worker.embedder import embed_text
- from services.shared.models import ToolResult

async def cross_reference_tickets_with_incidents(
    incident_ids: list[str],
    business_units: list[str]
) -> dict:
    """Cross-reference incidents with their related JIRA tickets.

    Use this tool when an engineer wants to see which tickets were raised
    during specific incidents, or to find connections between incidents
    and ticket work.

    Args:
        incident_ids: List of incident JIRA IDs to cross-reference
        business_units: List of BU codes to filter related tickets

    Returns:
        Dictionary mapping each incident to its linked tickets
    """
    try:
        from services.l3_agent.main import get_db_pool
        pool = await get_db_pool()

        cross_ref = []

        for incident_id in incident_ids:
            # Fetch incident with related_tickets
            incident = await pool.fetchrow(
                "SELECT jira_id, title, related_tickets FROM incidents WHERE jira_id = $1",
                incident_id
            )

            if not incident:
                continue

            linked_tickets = []

            # Get explicitly linked tickets from related_tickets JSONB field
            related = incident['related_tickets'] or []
            if related:
                ticket_rows = await pool.fetch(
                    """
                    SELECT jira_id, summary, status, business_unit
                    FROM tickets
                    WHERE jira_id = ANY($1)
                    AND business_unit = ANY($2)
                    """,
                    related, business_units
                )
                linked_tickets = [
                    {
                        'jira_id': r['jira_id'],
                        'summary': r['summary'],
                        'status': r['status'],
                        'business_unit': r['business_unit'],
                        'link_type': 'explicit'
                    }
                    for r in ticket_rows
                ]

            # Semantic fallback if no explicit links found
            if not linked_tickets:
                query_vector = await embed_text(incident['title'])
                semantic_rows = await pool.fetch(
                    """
                    SELECT jira_id, summary, status, business_unit,
                           1 - (embedding <=> $1::vector) AS score
                    FROM tickets
                    WHERE business_unit = ANY($2)
                    ORDER BY embedding <=> $1::vector
                    LIMIT 3
                    """,
                    str(query_vector), business_units
                )
                linked_tickets = [
                    {
                        'jira_id': r['jira_id'],
                        'summary': r['summary'],
                        'status': r['status'],
                        'business_unit': r['business_unit'],
                        'link_type': 'semantic',
                        'score': float(r['score'])
                    }
                    for r in semantic_rows
                ]

            cross_ref.append({
                'incident_id': incident['jira_id'],
                'incident_title': incident['title'],
                'linked_tickets': linked_tickets
            })

        logger.info("cross_ref_complete",
                    incident_count=len(incident_ids),
                    results=len(cross_ref))

        return ToolResult(success=True, data=cross_ref).model_dump()

    except Exception as e:
        logger.error("cross_ref_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()
---
## PROMPT 2.2 — ADK Tools: Incident Search & Cross-Reference

```
Create the ADK tools for the L3 Resolutions Agent.

Create services/l3-agent/tools/incident_search.py:

Tool: search_incidents
- Input model: SearchIncidentsInput
  - query_text: str
  - business_units: list[str] | None  # None = all BUs for L3
  - severity_filter: str | None
  - top_k: int = 10
- pgvector query against incidents table (same pattern as search_tickets)
- Return SearchResult list with result_type = "incident"

Create services/l3-agent/tools/rca_fetch.py:

Tool: fetch_incident_rca
- Input: incident_jira_id: str
- Fetches full incident record from incidents table by jira_id
- Returns: title, description, root_cause, long_term_fix, related_tickets, resolved_at, severity
- If root_cause or long_term_fix is empty, note "RCA not yet documented"

Create services/l3-agent/tools/cross_ref_tickets.py:

Tool: cross_reference_tickets_with_incidents
- Input model: CrossRefInput
  - incident_ids: list[str]           # JIRA IDs of incidents
  - business_units: list[str]          # filter tickets by BU
- Implementation:
  1. Fetch incidents by jira_id list from incidents table
  2. Extract related_tickets JSONB field from each incident
  3. For each related ticket jira_id, fetch summary + status from tickets table
  4. Also do a semantic search: for each incident title, search tickets in given BUs (top 3)
  5. Merge and deduplicate results
- Return: list of { incident_id, incident_title, linked_tickets: list[{jira_id, summary, status}] }
```

---
## Prompt 2.3 by claude
Refer to .cursorrules for all conventions. Create the shared summarize skill 
used by both L1/L2 and L3 agents.

Create these files:

1. services/shared/skills/__init__.py (empty)

2. services/shared/skills/summarize.py

Imports:
- google.generativeai as genai
- structlog, os, sys, json
- sys.path.insert(0, '.')
- from services.shared.models import ToolResult, SearchResult, ChatMessage
- from dotenv import load_dotenv
- load_dotenv('.env.local')

Module-level initialisation:
- Configure genai: genai.configure() 
  (picks up GOOGLE_APPLICATION_CREDENTIALS automatically)
- Initialise Gemini model:
  _model = genai.GenerativeModel(
      os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
  )
- Initialise structlog logger

Plain async function (no decorator):

async def summarize_search_results(
    original_question: str,
    search_results: list[dict],
    result_type: str = "tickets",
    follow_up_context: list[dict] = None
) -> dict:
    """Synthesise search results into a clear answer for the engineer.

    Always use this tool after retrieving search results to provide a 
    coherent, actionable answer. Do not return raw search results without 
    summarising them first.

    Args:
        original_question: The engineer's original question
        search_results: List of SearchResult dicts from search or rerank tools
        result_type: Type of results - 'tickets', 'incidents', or 'mixed'
        follow_up_context: Optional list of prior ChatMessage dicts for context

    Returns:
        Dictionary with summary text, key_points list and suggested_follow_ups
    """
    try:
        if not search_results:
            return ToolResult(
                success=True,
                data={
                    'summary': 'No relevant results found for your query.',
                    'key_points': [],
                    'suggested_follow_ups': [
                        'Try rephrasing your question',
                        'Check if you have selected the correct business unit',
                        'Try searching with different keywords'
                    ]
                }
            ).model_dump()

        # Format search results for prompt
        formatted_results = []
        for i, r in enumerate(search_results[:5], 1):
            score_pct = round(r.get('score', 0) * 100)
            result_lines = [
                f"[{i}] {r.get('result_type', 'ticket').upper()}: {r.get('jira_id')}",
                f"    Title: {r.get('title')}",
                f"    Status: {r.get('status', 'Unknown')} | BU: {r.get('business_unit', 'Unknown')} | Match: {score_pct}%",
            ]
            if r.get('summary'):
                result_lines.append(f"    Description: {r['summary'][:300]}")
            metadata = r.get('metadata') or {}
            if metadata.get('root_cause'):
                result_lines.append(f"    Root Cause: {metadata['root_cause'][:300]}")
            if metadata.get('long_term_fix'):
                result_lines.append(f"    Long-term Fix: {metadata['long_term_fix'][:300]}")
            formatted_results.append('\n'.join(result_lines))

        results_text = '\n\n'.join(formatted_results)

        # Build conversation context
        context_text = ''
        if follow_up_context:
            recent = follow_up_context[-3:]
            context_lines = []
            for msg in recent:
                role = msg.get('role', 'user').upper()
                content = msg.get('content', '')[:200]
                context_lines.append(f"{role}: {content}")
            context_text = (
                "\n\nRecent conversation context:\n" + 
                '\n'.join(context_lines)
            )

        # Build prompt
        prompt = f"""You are a technical support knowledge assistant helping 
a support engineer find answers in historical tickets and incident reports.

The engineer asked: {original_question}

Here are the most relevant {result_type} found:

{results_text}
{context_text}

Provide a response with these three sections:

SUMMARY:
A clear, direct answer to the engineer's question based on the retrieved 
records. Be specific and technical. Reference ticket/incident IDs directly.
If this is a follow-up question, take the conversation context into account.

KEY POINTS:
- List 3-5 specific actionable findings or resolution steps
- Each point should reference a specific ticket or incident ID
- Focus on what was done to fix the issue

SUGGESTED FOLLOW-UPS:
- List 2-3 follow-up questions the engineer might want to ask next

Keep the response concise and technical. Do not add generic filler text."""

        # Call Gemini
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _model.generate_content(prompt)
        )

        response_text = response.text

        # Parse sections from response
        summary = ''
        key_points = []
        follow_ups = []

        lines = response_text.split('\n')
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if 'SUMMARY:' in line.upper():
                current_section = 'summary'
                continue
            elif 'KEY POINTS:' in line.upper():
                current_section = 'key_points'
                continue
            elif 'SUGGESTED FOLLOW' in line.upper():
                current_section = 'follow_ups'
                continue

            if current_section == 'summary':
                summary += line + ' '
            elif current_section == 'key_points' and line.startswith('-'):
                key_points.append(line[1:].strip())
            elif current_section == 'follow_ups' and line.startswith('-'):
                follow_ups.append(line[1:].strip())

        # Fallback if parsing fails
        if not summary:
            summary = response_text[:500]

        result = {
            'summary': summary.strip(),
            'key_points': key_points or ['See retrieved records above'],
            'suggested_follow_ups': follow_ups or [
                'Ask about a specific ticket ID for more details',
                'Ask about the root cause of a specific issue'
            ]
        }

        logger.info("summarize_complete",
                    question_length=len(original_question),
                    result_count=len(search_results),
                    summary_length=len(summary))

        return ToolResult(success=True, data=result).model_dump()

    except Exception as e:
        logger.error("summarize_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()
---

## PROMPT 2.3 — Summarize Skill (Shared)

```
Create services/shared/skills/summarize.py — the summarize skill used by both L1/L2 and L3 agents.

This is an ADK Tool wrapping a structured LLM prompt call.

Tool: summarize_search_results
- Input model: SummarizeInput
  - original_question: str
  - search_results: list[SearchResult]
  - result_type: Literal["tickets", "incidents", "mixed"]
  - follow_up_context: list[ChatMessage] | None  # prior conversation
- Output: ToolResult with data = { summary: str, key_points: list[str], suggested_follow_ups: list[str] }

Prompt template (pass to Gemini via Vertex AI):
---
You are a technical support knowledge assistant helping a support engineer find answers in historical tickets and incident reports.

The engineer asked: {original_question}

Here are the most relevant {result_type} found:

{formatted_results}
---
{optional_conversation_context}
---
Provide:
1. A clear, direct answer to the engineer's question based on the retrieved records
2. Key resolution steps or patterns found across these records
3. Any caveats (e.g. if records are old, if root cause differs)

Be concise and technical. Do not add generic filler text.
---

- Format search results with: JIRA ID, summary, status, score, key snippet
- If follow_up_context provided, include last 3 turns for continuity
- Use Vertex AI Gemini 1.5 Flash for the LLM call
- Authentication via GOOGLE_APPLICATION_CREDENTIALS — no API key needed
- Use google.generativeai SDK: genai.GenerativeModel("gemini-1.5-flash")
- Call generate_content_async() for async support
- GCP_PROJECT_ID and VERTEX_AI_LOCATION from env vars
```

---
## Prompt 2.4 by claude
Refer to .cursorrules for all conventions. Create the complete L1/L2 Resolution 
Agent service at services/l1l2_agent/

Create these files:

1. services/l1l2_agent/main.py

Imports:
- asyncio, os, sys
- asyncpg
- structlog
- dotenv load_dotenv
- sys.path.insert(0, '.')

Module-level DB pool (singleton):
_db_pool = None

async def get_db_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            os.getenv('DATABASE_URL').replace('postgresql+asyncpg://', 'postgresql://'),
            min_size=2,
            max_size=10
        )
    return _db_pool

2. services/l1l2_agent/agent.py

Imports:
- os, sys
- google.adk.agents LlmAgent
- structlog
- dotenv load_dotenv
- sys.path.insert(0, '.')
- from services.l1l2_agent.tools.vector_search import search_tickets
- from services.l1l2_agent.tools.rerank import rerank_results
- from services.l1l2_agent.tools.jira_fetch import fetch_jira_ticket, check_ticket_status
- from services.shared.skills.summarize import summarize_search_results

load_dotenv('.env.local')

SYSTEM_INSTRUCTION = """You are an L1/L2 technical support assistant for a 
multi-agent agentic platform. Your role is to help support engineers find 
solutions to technical issues by searching historical tickets.

When an engineer asks a question:

1. ALWAYS use search_tickets first with the provided business_units scope
2. After searching, use rerank_results to improve result ordering
3. If the engineer mentions a specific ticket ID (pattern like B1-1234 or INC-001), 
   use fetch_jira_ticket directly instead of searching
4. If they ask about ticket status only, use check_ticket_status
5. ALWAYS use summarize_search_results after retrieving results to provide 
   a coherent answer — never return raw results directly
6. If search returns low relevance results (score < 0.6), try a rephrased query
7. Always cite ticket IDs in your response e.g. "See B1-1008 for reference"
8. If no relevant results found, say so clearly and suggest:
   - Try different keywords
   - Check if the correct business unit is selected
   - The issue may not have been seen before

You are precise, technical and concise. Engineers don't want filler text."""

agent = LlmAgent(
    name="l1l2_resolution_agent",
    model="gemini-2.5-flash",
    description="Searches historical support tickets to help L1/L2 engineers find solutions to technical issues",
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        search_tickets,
        rerank_results,
        fetch_jira_ticket,
        check_ticket_status,
        summarize_search_results
    ]
)
---
## PROMPT 2.4 — L1/L2 Resolution Agent

```
Create the complete L1/L2 Resolution Agent service at services/l1l2-agent/.

Files:

1. services/l1l2-agent/agent.py
   - Google ADK LlmAgent using Gemini 1.5 Flash via Vertex AI
   - Import: from google.adk.agents import LlmAgent
   - Import: from google.adk.tools import tool
   - model="gemini-1.5-flash" — ADK uses GOOGLE_APPLICATION_CREDENTIALS automatically
   - Name: "l1l2_resolution_agent"
   - Tools: [search_tickets, rerank_results, fetch_jira_ticket, check_ticket_status, summarize_search_results]
   - All tools must be decorated with @tool and have clear docstrings explaining when ADK should call them
   - System instruction (full text):

"You are an L1/L2 technical support assistant. Your role is to help support engineers find solutions to technical issues by searching historical tickets.

When a user asks a question:
1. ALWAYS use the search_tickets tool first with the provided business_units scope
2. After searching, use rerank_results to re-order results by relevance before summarising
3. If they mention a specific JIRA ticket ID (e.g. B1-1234), use fetch_jira_ticket directly
4. If they ask about ticket status, use check_ticket_status
5. After retrieving and reranking results, ALWAYS use summarize_search_results to provide a coherent answer
5. If the initial search returns low-confidence results (score < 0.7), try a rephrased query
6. Be specific and technical — the user is an engineer
7. Always cite the JIRA ticket IDs in your response
8. If no relevant results found, say so clearly and suggest alternative search terms"

2. services/l1l2-agent/main.py
   - FastAPI app that wraps the ADK agent
   - POST /chat endpoint:
     - Input: AgentRequest
     - Output: StreamingResponse (SSE)
     - Streams agent response token by token
   - GET /health endpoint
   - Dependency injection for DB pool and Redis

3. services/l1l2-agent/Dockerfile
   - Python 3.11 slim, non-root user

4. services/l1l2-agent/requirements.txt
   - google-adk, google-cloud-aiplatform, vertexai, google-generativeai
   - fastapi, uvicorn, asyncpg, redis, httpx, structlog, pydantic>=2.0
```

---
## Prompt 2.5 - l3 resolutoin by claude
Refer to .cursorrules for all conventions. Create the complete L3 Resolutions 
Agent service at services/l3_agent/

Create these files:

1. services/l3_agent/main.py

Same pattern as services/l1l2_agent/main.py:

Imports:
- asyncio, os, sys
- asyncpg
- structlog  
- dotenv load_dotenv
- sys.path.insert(0, '.')

Module-level DB pool singleton:
_db_pool = None

async def get_db_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            os.getenv('DATABASE_URL').replace('postgresql+asyncpg://', 'postgresql://'),
            min_size=2,
            max_size=10
        )
    return _db_pool

2. services/l3_agent/agent.py

Imports:
- os, sys
- google.adk.agents LlmAgent
- structlog
- dotenv load_dotenv
- sys.path.insert(0, '.')
- from services.l3_agent.tools.incident_search import search_incidents
- from services.l3_agent.tools.rca_fetch import fetch_incident_rca
- from services.l3_agent.tools.cross_ref_tickets import cross_reference_tickets_with_incidents
- from services.l1l2_agent.tools.jira_fetch import fetch_jira_ticket
- from services.shared.skills.summarize import summarize_search_results

load_dotenv('.env.local')

SYSTEM_INSTRUCTION = """You are an L3 technical support specialist for a 
multi-agent agentic platform with deep knowledge of production incidents 
and Root Cause Analyses (RCAs).

When the Incident Management knowledge base is active:

1. Use search_incidents to find relevant past incidents — when business_units 
   is provided, scope the search to those BUs; otherwise search all BUs
2. When a specific incident is identified, use fetch_incident_rca to get 
   full RCA details including root cause and long-term fix
3. If the engineer wants to cross-reference with tickets, use 
   cross_reference_tickets_with_incidents
4. For questions about a specific ticket raised during an incident, 
   use fetch_jira_ticket
5. ALWAYS use summarize_search_results to synthesise findings into a 
   clear answer — never return raw data directly
6. Highlight in your response:
   - Root cause of the incident
   - Long-term fix that was applied
   - Related tickets that were raised
   - Whether this is a recurring pattern
7. If the engineer asks a follow-up about an incident already discussed, 
   use the conversation context — do not search again unless needed
8. If RCA is not documented, say so clearly:
   "RCA not yet documented for this incident"
9. Always cite incident IDs and ticket IDs in your response

You are precise, technical and concise."""

agent = LlmAgent(
    name="l3_resolutions_agent",
    model="gemini-2.5-flash",
    description="Searches historical production incidents and RCAs to help L3 engineers diagnose and resolve production issues",
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        search_incidents,
        fetch_incident_rca,
        cross_reference_tickets_with_incidents,
        fetch_jira_ticket,
        summarize_search_results
    ]
)
---
## PROMPT 2.5 — L3 Resolutions Agent

```
Create the complete L3 Resolutions Agent service at services/l3-agent/.

Files:

1. services/l3-agent/agent.py
   - Google ADK LlmAgent using Gemini 1.5 Flash via Vertex AI
   - model="gemini-1.5-flash" — ADK uses GOOGLE_APPLICATION_CREDENTIALS automatically
   - Name: "l3_resolutions_agent"
   - Tools: [search_incidents, fetch_incident_rca, cross_reference_tickets_with_incidents, fetch_jira_ticket, summarize_search_results]
   - All tools decorated with @tool and descriptive docstrings
   - System instruction:

"You are an L3 technical support specialist with deep knowledge of production incidents and root cause analyses.

When the Incident Management knowledge base is active:
1. Use search_incidents to find relevant past incidents
2. When a specific incident is identified, use fetch_incident_rca to get full RCA details
3. If the user wants to cross-reference with tickets, use cross_reference_tickets_with_incidents
4. For follow-up questions about a specific incident already discussed, refer to the conversation context
5. Always use summarize_search_results to synthesise your findings
6. Highlight: root cause, long-term fix, affected systems, similar patterns
7. If user selects a specific BU alongside Incident Management, apply that BU filter to both incident and ticket searches
8. Cite incident IDs and ticket IDs in responses"

2. services/l3-agent/main.py
   - Same FastAPI + SSE streaming pattern as L1/L2 agent
   - POST /chat and GET /health endpoints

3. Dockerfile + requirements.txt (same pattern as l1l2-agent)
```

---
## Prompt 2.6 by claude - Session & Feedback Agent
Refer to .cursorrules for all conventions. Create the Session & Feedback Agent 
at services/session_agent/

Create these files:

1. services/session_agent/__init__.py (empty)
2. services/session_agent/tools/__init__.py (empty)

3. services/session_agent/tools/session_store.py

Imports:
- asyncpg, structlog, os, sys, json, uuid
- from datetime import datetime, timezone
- sys.path.insert(0, '.')
- from services.shared.models import ToolResult, ChatSession, SessionSummary

Plain async functions (no decorator):

async def save_session(
    session_id: str,
    engineer_id: str,
    title: str,
    context_scope: dict,
    messages: list[dict]
) -> dict:
    """Save or update a chat session for an engineer.

    Use this tool to persist conversation history after each message exchange.

    Args:
        session_id: UUID string of the session
        engineer_id: Email or ID of the engineer
        title: Short title for the session (first user message truncated to 60 chars)
        context_scope: Dict with business_units list and include_incidents bool
        messages: Full list of ChatMessage dicts in the conversation

    Returns:
        Dictionary with success status and session_id
    """
    try:
        from services.session_agent.main import get_db_pool
        pool = await get_db_pool()

        now = datetime.now(timezone.utc)
        await pool.execute(
            """
            INSERT INTO chat_sessions 
                (id, engineer_id, title, context_scope, messages, 
                 created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $6)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                context_scope = EXCLUDED.context_scope,
                messages = EXCLUDED.messages,
                updated_at = EXCLUDED.updated_at
            """,
            uuid.UUID(session_id),
            engineer_id,
            title,
            json.dumps(context_scope),
            json.dumps(messages),
            now
        )

        logger.info("session_saved",
                    session_id=session_id,
                    engineer_id=engineer_id,
                    message_count=len(messages))

        return ToolResult(
            success=True,
            data={'session_id': session_id}
        ).model_dump()

    except Exception as e:
        logger.error("session_save_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


async def load_session(session_id: str) -> dict:
    """Load a specific chat session by ID.

    Use this tool to resume a previous conversation.

    Args:
        session_id: UUID string of the session to load

    Returns:
        Dictionary with full session including all messages
    """
    try:
        from services.session_agent.main import get_db_pool
        pool = await get_db_pool()

        row = await pool.fetchrow(
            """
            SELECT id, engineer_id, title, context_scope, 
                   messages, created_at, updated_at
            FROM chat_sessions
            WHERE id = $1
            """,
            uuid.UUID(session_id)
        )

        if not row:
            return ToolResult(
                success=False,
                error=f"Session {session_id} not found"
            ).model_dump()

        result = {
            'id': str(row['id']),
            'engineer_id': row['engineer_id'],
            'title': row['title'],
            'context_scope': row['context_scope'],
            'messages': row['messages'] or [],
            'created_at': str(row['created_at']),
            'updated_at': str(row['updated_at'])
        }

        logger.info("session_loaded",
                    session_id=session_id,
                    message_count=len(result['messages']))

        return ToolResult(success=True, data=result).model_dump()

    except Exception as e:
        logger.error("session_load_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


async def list_engineer_sessions(
    engineer_id: str,
    limit: int = 20
) -> dict:
    """List recent chat sessions for an engineer.

    Use this tool to show an engineer their conversation history.

    Args:
        engineer_id: Email or ID of the engineer
        limit: Maximum number of sessions to return (default 20)

    Returns:
        Dictionary with list of session summaries ordered by most recent first
    """
    try:
        from services.session_agent.main import get_db_pool
        pool = await get_db_pool()

        rows = await pool.fetch(
            """
            SELECT id, title, messages, updated_at
            FROM chat_sessions
            WHERE engineer_id = $1
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            engineer_id,
            limit
        )

        sessions = []
        for row in rows:
            messages = row['messages'] or []
            last_msg = messages[-1] if messages else None
            preview = None
            if last_msg:
                preview = last_msg.get('content', '')[:100]

            sessions.append({
                'id': str(row['id']),
                'title': row['title'] or 'Untitled session',
                'last_message_preview': preview,
                'updated_at': str(row['updated_at'])
            })

        return ToolResult(success=True, data=sessions).model_dump()

    except Exception as e:
        logger.error("list_sessions_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


4. services/session_agent/tools/feedback_store.py

Imports:
- asyncpg, structlog, os, sys, uuid
- from datetime import datetime, timezone
- sys.path.insert(0, '.')
- from services.shared.models import ToolResult, FeedbackRating

async def save_feedback(
    session_id: str,
    message_index: int,
    rating: str,
    comment: str = None
) -> dict:
    """Save engineer feedback for a specific response.

    Use this tool when an engineer rates a response as correct, 
    can_be_better, or incorrect.

    Args:
        session_id: UUID string of the session
        message_index: Index of the message being rated
        rating: One of 'correct', 'can_be_better', 'incorrect'
        comment: Optional comment from the engineer

    Returns:
        Dictionary with success status
    """
    try:
        from services.session_agent.main import get_db_pool
        pool = await get_db_pool()

        valid_ratings = ['correct', 'can_be_better', 'incorrect']
        if rating not in valid_ratings:
            return ToolResult(
                success=False,
                error=f"Invalid rating. Must be one of: {valid_ratings}"
            ).model_dump()

        await pool.execute(
            """
            INSERT INTO engineer_feedback 
                (session_id, message_index, rating, comment, created_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            uuid.UUID(session_id),
            message_index,
            rating,
            comment,
            datetime.now(timezone.utc)
        )

        logger.info("feedback_saved",
                    session_id=session_id,
                    rating=rating)

        return ToolResult(success=True, data={'saved': True}).model_dump()

    except Exception as e:
        logger.error("feedback_save_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


async def get_feedback_summary(
    days: int = 7,
    business_unit: str = None
) -> dict:
    """Get aggregated feedback statistics.

    Use this tool to get a summary of how well the AI is performing.
    Admin only.

    Args:
        days: Number of past days to include (default 7)
        business_unit: Optional BU code to filter by

    Returns:
        Dictionary with total, correct, can_be_better, incorrect counts 
        and accuracy percentage
    """
    try:
        from services.session_agent.main import get_db_pool
        pool = await get_db_pool()

        row = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN rating = 'correct' THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN rating = 'can_be_better' THEN 1 ELSE 0 END) as can_be_better,
                SUM(CASE WHEN rating = 'incorrect' THEN 1 ELSE 0 END) as incorrect
            FROM engineer_feedback
            WHERE created_at >= NOW() - INTERVAL '$1 days'
            """,
            days
        )

        total = int(row['total'] or 0)
        correct = int(row['correct'] or 0)
        accuracy = round((correct / total * 100), 1) if total > 0 else 0.0

        result = {
            'total': total,
            'correct': correct,
            'can_be_better': int(row['can_be_better'] or 0),
            'incorrect': int(row['incorrect'] or 0),
            'accuracy_pct': accuracy,
            'period_days': days
        }

        return ToolResult(success=True, data=result).model_dump()

    except Exception as e:
        logger.error("feedback_summary_failed", error=str(e))
        return ToolResult(success=False, error=str(e)).model_dump()


5. services/session_agent/main.py

Same DB pool singleton pattern as l1l2_agent/main.py and l3_agent/main.py.
Read DATABASE_URL from environment, create asyncpg pool.

6. services/session_agent/agent.py

Imports:
- google.adk.agents LlmAgent
- os, sys
- dotenv load_dotenv
- sys.path.insert(0, '.')
- from services.session_agent.tools.session_store import (
    save_session, load_session, list_engineer_sessions)
- from services.session_agent.tools.feedback_store import (
    save_feedback, get_feedback_summary)

load_dotenv('.env.local')

agent = LlmAgent(
    name="session_feedback_agent",
    model="gemini-2.5-flash",
    description="Manages chat session persistence and engineer feedback collection",
    instruction="""You manage chat sessions and feedback for the support platform.

Use save_session to persist conversations after each exchange.
Use load_session to resume a previous conversation by ID.
Use list_engineer_sessions to show an engineer their history.
Use save_feedback when an engineer rates a response.
Use get_feedback_summary for admin analytics on response quality.""",
    tools=[
        save_session,
        load_session,
        list_engineer_sessions,
        save_feedback,
        get_feedback_summary
    ]
)
---
## PROMPT 2.6 — Session & Feedback Agent

```
Create the Session & Feedback Agent at services/session-agent/.

1. services/session-agent/tools/session_store.py

Tool: save_session
- Input: session_id (UUID), engineer_id, title, context_scope (BusinessUnitScope), messages (list[ChatMessage])
- Upserts to chat_sessions table
- Updates updated_at timestamp
- Returns ToolResult with session_id

Tool: load_session
- Input: session_id (UUID) OR engineer_id (returns most recent 20 sessions)
- Returns ToolResult with ChatSession or list[ChatSession summary]
- Session summary: id, title, last_message_preview (first 100 chars), updated_at

Tool: list_engineer_sessions
- Input: engineer_id: str, limit: int = 20
- Returns list of session summaries ordered by updated_at DESC

2. services/session-agent/tools/feedback_store.py

Tool: save_feedback
- Input: FeedbackInput (session_id, message_index, rating, comment)
- Inserts to engineer_feedback table
- Returns ToolResult success/failure

Tool: get_feedback_summary
- Input: date_range (last N days, default 7), business_unit (optional)
- Returns: { total: int, correct: int, can_be_better: int, incorrect: int, accuracy_pct: float }
- Joins feedback with sessions to filter by BU if provided

3. services/session-agent/agent.py
   - ADK Agent wrapping the session tools
   - Also exposes direct HTTP endpoints (not just agent interface):
     - POST /sessions — create/update session
     - GET /sessions/{engineer_id} — list sessions
     - GET /sessions/{session_id}/messages — get full session
     - POST /feedback — submit feedback
     - GET /feedback/summary — get summary stats
```

---
## Prompt 2.7 Orchestrator Agent by Claude
Refer to .cursorrules for all conventions. Create the Orchestrator Agent at 
services/orchestrator/

Create these files:

1. services/orchestrator/__init__.py (empty)

2. services/orchestrator/intent_classifier.py

Imports:
- os, sys, re, json, hashlib
- google.generativeai as genai
- redis.asyncio as redis
- structlog
- dotenv load_dotenv
- sys.path.insert(0, '.')
- from services.shared.models import BusinessUnitScope

load_dotenv('.env.local')
genai.configure()
_model = genai.GenerativeModel(os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))

Enum class IntentType (str enum):
- TICKET_SEARCH    = "ticket_search"
- JIRA_LOOKUP      = "jira_lookup"
- STATUS_CHECK     = "status_check"
- INCIDENT_SEARCH  = "incident_search"
- CROSS_REF        = "cross_ref"
- FOLLOW_UP        = "follow_up"
- SESSION_RESUME   = "session_resume"
- OUT_OF_SCOPE     = "out_of_scope"

JIRA_ID_PATTERN = re.compile(r'\b[A-Z]+-\d+\b')

async def classify_intent(
    message: str,
    context_scope: BusinessUnitScope,
    has_conversation_history: bool = False
) -> IntentType:
    - First check regex: if JIRA_ID_PATTERN found in message → return JIRA_LOOKUP
    - Check keywords for STATUS_CHECK: 
      ["status of", "what is the status", "is it resolved", "who is assigned"]
    - If include_incidents is True and message contains incident keywords
      ["incident", "outage", "production issue", "rca", "root cause", "p1", "p2", "postmortem"]
      → return INCIDENT_SEARCH
    - Check for cross_ref keywords:
      ["cross reference", "cross-reference", "related tickets", "tickets raised for", 
       "linked tickets", "incidents and tickets"]
      → return CROSS_REF
    - Check for session resume keywords:
      ["resume", "continue our", "go back to", "previous conversation", "earlier session"]
      → return SESSION_RESUME
    - If has_conversation_history and message is short (< 50 chars) → return FOLLOW_UP
    - For everything else: call Gemini with this prompt:
      
      "Classify this support engineer message into one of these intents:
       ticket_search, jira_lookup, status_check, incident_search, 
       cross_ref, follow_up, out_of_scope
       
       Message: {message}
       Has incidents enabled: {context_scope.include_incidents}
       
       Reply with ONLY the intent name, nothing else."
      
      Parse response and return matching IntentType
      Default to TICKET_SEARCH if classification fails
    
    - Cache result in Redis for 60 seconds:
      key = f"intent:{hashlib.md5(message.encode()).hexdigest()}"
    - Log: intent_classified with intent and message_length


3. services/orchestrator/router.py

Imports:
- os, sys
- from services.orchestrator.intent_classifier import IntentType
- from services.shared.models import BusinessUnitScope

def route_to_agent(
    intent: IntentType,
    context_scope: BusinessUnitScope,
    last_agent: str = None
) -> str:
    - Returns the service endpoint URL for the appropriate agent
    - TICKET_SEARCH, JIRA_LOOKUP, STATUS_CHECK → L1L2_AGENT_ENDPOINT env var
    - INCIDENT_SEARCH, CROSS_REF → L3_AGENT_ENDPOINT env var
    - FOLLOW_UP → last_agent if provided, else L1L2_AGENT_ENDPOINT
    - SESSION_RESUME → SESSION_AGENT_ENDPOINT env var
    - OUT_OF_SCOPE → None (orchestrator handles directly)
    - Log: routing_decision with intent and endpoint


4. services/orchestrator/agent.py

Imports:
- os, sys
- google.adk.agents LlmAgent
- dotenv load_dotenv
- sys.path.insert(0, '.')
- from services.l1l2_agent.agent import agent as l1l2_agent
- from services.l3_agent.agent import agent as l3_agent
- from services.session_agent.agent import agent as session_agent

load_dotenv('.env.local')

ORCHESTRATOR_INSTRUCTION = """You are the orchestration layer of a multi-agent 
technical support platform. Your role is to route engineer queries to the 
right specialist agent and ensure coherent multi-turn conversations.

You have access to three specialist agents:
- l1l2_resolution_agent: handles ticket search, JIRA lookups, status queries
  for L1/L2 support engineers
- l3_resolutions_agent: handles incident management, RCA search, 
  cross-referencing incidents with tickets for L3 engineers  
- session_feedback_agent: handles session persistence and feedback

Routing rules:
1. If query mentions a specific ticket ID (e.g. B1-1234) → l1l2_resolution_agent
2. If query asks about ticket status → l1l2_resolution_agent
3. If Incident Management is active AND query is about incidents, outages, 
   RCAs or root causes → l3_resolutions_agent
4. If query involves both incidents AND tickets (cross-reference) → l3_resolutions_agent
5. For general ticket search → l1l2_resolution_agent
6. For session management → session_feedback_agent
7. For completely unrelated queries → politely decline and ask for a 
   support-related question

Always delegate to a specialist agent — never answer engineering questions yourself.
The engineer has already selected their business unit scope — pass it through."""

agent = LlmAgent(
    name="orchestrator",
    model="gemini-2.5-flash",
    description="Routes support engineer queries to the appropriate specialist agent",
    instruction=ORCHESTRATOR_INSTRUCTION,
    sub_agents=[l1l2_agent, l3_agent, session_agent]
)


5. services/orchestrator/main.py

Imports:
- asyncio, os, sys, uuid, json
- asyncpg
- redis.asyncio as redis
- structlog
- dotenv load_dotenv
- sys.path.insert(0, '.')
- from services.orchestrator.intent_classifier import classify_intent, IntentType
- from services.orchestrator.router import route_to_agent
- from services.shared.models import AgentRequest, BusinessUnitScope, ChatMessage

load_dotenv('.env.local')

Module-level singletons:
_db_pool = None
_redis_client = None

async def get_db_pool() -> asyncpg.Pool: (same pattern as other services)
async def get_redis() -> redis.Redis: (create from REDIS_URL env var)

async def process_request(request: AgentRequest) -> dict:
    """Main orchestration function.
    
    Steps:
    1. Load session history from DB if session_id provided
       - Query chat_sessions table for messages
       - Parse JSONB messages field
    2. Classify intent using classify_intent()
    3. Route to appropriate agent endpoint using route_to_agent()
    4. Build context with last 5 messages from history
    5. Return routing info: { intent, agent_endpoint, context_messages }
    6. Save session asynchronously (fire and forget)
    """
    db_pool = await get_db_pool()
    redis_client = await get_redis()

    # Load session history
    history = []
    if request.session_id:
        row = await db_pool.fetchrow(
            "SELECT messages FROM chat_sessions WHERE id = $1",
            request.session_id
        )
        if row and row['messages']:
            raw = row['messages']
            history = json.loads(raw) if isinstance(raw, str) else raw

    # Classify intent
    has_history = len(history) > 0
    intent = await classify_intent(
        message=request.message,
        context_scope=request.context_scope,
        has_conversation_history=has_history
    )

    # Get last agent from session metadata if available
    last_agent = None
    if history:
        for msg in reversed(history):
            if msg.get('metadata', {}).get('agent'):
                last_agent = msg['metadata']['agent']
                break

    # Route
    agent_endpoint = route_to_agent(intent, request.context_scope, last_agent)

    # Last 5 messages as context
    context_messages = history[-5:] if history else []

    logger.info("request_orchestrated",
                engineer_id=request.engineer_id,
                intent=intent,
                agent_endpoint=agent_endpoint,
                history_length=len(history))

    return {
        'intent': intent,
        'agent_endpoint': agent_endpoint,
        'context_messages': context_messages,
        'session_id': str(request.session_id) if request.session_id else None
    }
---

## PROMPT 2.7 — Orchestrator Agent

```
Create the Orchestrator Agent at services/orchestrator/.

1. services/orchestrator/intent_classifier.py

Function: classify_intent(message: str, context_scope: BusinessUnitScope) -> IntentType

IntentType enum:
- TICKET_SEARCH       — user describing a problem, looking for known solutions
- JIRA_LOOKUP         — user mentions a specific ticket ID (regex: [A-Z]+-\d+)
- STATUS_CHECK        — user asking "what is the status of..."
- INCIDENT_SEARCH     — user asking about production incidents (only if include_incidents=True)
- CROSS_REF           — user wants to link incidents with tickets
- FOLLOW_UP           — user is continuing an existing conversation thread
- SESSION_RESUME      — user wants to load a past conversation
- OUT_OF_SCOPE        — unrelated question

Use Gemini 1.5 Flash via google.generativeai SDK for classification.
Cache classification in Redis for 60 seconds keyed on message hash.

2. services/orchestrator/router.py

Function: route_to_agent(intent: IntentType, context_scope: BusinessUnitScope) -> str

Returns the endpoint URL of the appropriate agent:
- TICKET_SEARCH, JIRA_LOOKUP, STATUS_CHECK → L1L2_AGENT_ENDPOINT
- INCIDENT_SEARCH, CROSS_REF → L3_AGENT_ENDPOINT
- FOLLOW_UP → same agent as last message in session
- SESSION_RESUME → SESSION_AGENT_ENDPOINT

3. services/orchestrator/agent.py
   - Google ADK LlmAgent as orchestrator using Gemini 1.5 Flash
   - model="gemini-1.5-flash" — GOOGLE_APPLICATION_CREDENTIALS used automatically
   - Name: "orchestrator"
   - Register l1l2_agent and l3_agent instances as sub-agents: agents=[l1l2_agent, l3_agent]
   - ADK handles delegation automatically based on orchestrator instruction and sub-agent descriptions

4. services/orchestrator/main.py
   - FastAPI app
   - POST /chat — main orchestration endpoint
     Input: AgentRequest (with session_id, engineer_id, message, context_scope)
     Steps:
     1. Load session from session-agent (if session_id provided)
     2. Classify intent
     3. Route to appropriate agent
     4. Stream response back
     5. Save updated session to session-agent
   - GET /health endpoint

5. Context injection:
   - Always prepend last 5 messages from session to agent request
   - Include context_scope in every sub-agent call
   - After response: async save session (don't block the stream)
```

