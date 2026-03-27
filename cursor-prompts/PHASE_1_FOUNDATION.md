# Cursor Build Prompts — Phase 1: Foundation & Database

---

## PROMPT 1.1 — Project Scaffold

```
Create the full monorepo directory structure for the cybmas project as defined in PROJECT_STANDARDS.md.

Create the following empty placeholder files and directories:
- frontend/ (Next.js 14 App Router project)
- services/api-gateway/
- services/orchestrator/
- services/l1l2-agent/
- services/l3-agent/
- services/session-agent/
- pipeline/embedding_worker/
- pipeline/webhook_receiver/    # Cloud Run service that receives JIRA webhooks and publishes to Pub/Sub
- infra/ (Terraform)
- database/migrations/
- tests/unit/ tests/integration/ tests/e2e/

Also create:
- .gitignore with entries:
  .env.local
  .env.*.local
  keys/
  *.json
  __pycache__/
  *.pyc
  venv/
  .venv/
  node_modules/
  .DS_Store
  *.egg-info/
  dist/
  build/
  .terraform/
  *.tfstate
  *.tfstate.backup
  .terraform.lock.hcl
- .env.example with all environment variables from PROJECT_STANDARDS.md
- docker-compose.yml that starts:
  - postgres:15 with pgvector extension enabled
  - redis:7
  - Exposes postgres on 5432, redis on 6379
  - Has a volume for postgres data persistence
- README.md with project overview, setup steps, and links to architecture doc
```

---

## PROMPT 1.2 — Database Schema & Migrations as per claude
...
Refer to .cursorrules for all conventions. Create the full PostgreSQL database schema for the multi-agent platform.

Create these files:

1. database/migrations/001_initial_schema.sql

Content:
-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Track applied migrations
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(50) PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now()
);

-- Engineer accounts (JWT auth)
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(100),
    role            VARCHAR(20) DEFAULT 'engineer' CHECK (role IN ('engineer', 'admin')),
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_login      TIMESTAMPTZ
);
CREATE INDEX users_email_idx ON users(email);

-- Business units
CREATE TABLE business_units (
    id    SERIAL PRIMARY KEY,
    code  VARCHAR(20) UNIQUE NOT NULL,
    name  VARCHAR(100)
);

-- JIRA tickets with vector embeddings
CREATE TABLE tickets (
    id            SERIAL PRIMARY KEY,
    jira_id       VARCHAR(50) UNIQUE NOT NULL,
    business_unit VARCHAR(20) REFERENCES business_units(code),
    ticket_type   VARCHAR(20),
    summary       TEXT NOT NULL,
    description   TEXT,
    status        VARCHAR(50),
    resolution    TEXT,
    discussion    JSONB,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    embedding     vector(768),
    raw_json      JSONB
);

-- Incident reports and RCAs
CREATE TABLE incidents (
    id              SERIAL PRIMARY KEY,
    jira_id         VARCHAR(50) UNIQUE,
    business_unit   VARCHAR(20),
    title           TEXT NOT NULL,
    description     TEXT,
    root_cause      TEXT,
    long_term_fix   TEXT,
    related_tickets JSONB,
    severity        VARCHAR(20),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    embedding       vector(768),
    raw_json        JSONB
);

-- Chat sessions
CREATE TABLE chat_sessions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engineer_id   VARCHAR(100) NOT NULL,
    title         TEXT,
    context_scope JSONB,
    messages      JSONB,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX chat_sessions_engineer_idx ON chat_sessions(engineer_id, updated_at DESC);

-- Engineer feedback
CREATE TABLE engineer_feedback (
    id            SERIAL PRIMARY KEY,
    session_id    UUID REFERENCES chat_sessions(id),
    message_index INT,
    rating        VARCHAR(20) CHECK (rating IN ('correct','can_be_better','incorrect')),
    comment       TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX feedback_session_idx ON engineer_feedback(session_id);


2. database/migrations/002_pgvector_indexes.sql

Content:
-- HNSW indexes for fast cosine similarity search
CREATE INDEX tickets_embedding_idx ON tickets
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX incidents_embedding_idx ON incidents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- B-tree indexes for filtering
CREATE INDEX tickets_bu_idx ON tickets(business_unit);
CREATE INDEX tickets_status_idx ON tickets(status);
CREATE INDEX tickets_type_idx ON tickets(ticket_type);
CREATE INDEX incidents_bu_idx ON incidents(business_unit);
CREATE INDEX incidents_severity_idx ON incidents(severity);


3. database/migrations/003_feedback_constraints.sql

Content:
-- Additional constraints on feedback
ALTER TABLE engineer_feedback
    ADD CONSTRAINT feedback_rating_required CHECK (rating IS NOT NULL);
ALTER TABLE engineer_feedback
    ADD CONSTRAINT feedback_session_required CHECK (session_id IS NOT NULL);


4. database/seeds/business_units.sql

Content:
INSERT INTO business_units (code, name) VALUES
    ('B1', 'Reservations Platform'),
    ('B2', 'Payments Platform')
ON CONFLICT (code) DO NOTHING;


5. scripts/run_migrations.py

A Python script that:
- Loads DATABASE_URL from .env.local using python-dotenv
- Connects to PostgreSQL using psycopg2 (sync, not async — scripts are sync)
- Creates schema_migrations table if not exists
- Reads all .sql files from database/migrations/ ordered by filename
- For each file: checks if version already in schema_migrations, skips if yes
- Runs the SQL if not yet applied
- Inserts the filename into schema_migrations on success
- Prints: "Applied: 001_initial_schema.sql" or "Skipped: 001_initial_schema.sql (already applied)"
- Uses psycopg2, python-dotenv


6. database/db_client.py

An async database client:
- Loads DATABASE_URL from environment
- async function get_db_pool() -> asyncpg.Pool
  - Creates asyncpg connection pool, min_size=2, max_size=10
  - Returns pool
- async context manager get_db_connection(pool) -> asyncpg.Connection
  - Yields a connection from the pool
  - Handles release on exit
...
  
```
Create the full PostgreSQL database schema for the cybmas system.

Files to create:
1. database/migrations/001_initial_schema.sql
   - Enable pgvector extension: CREATE EXTENSION IF NOT EXISTS vector;
   - users table (id, email, hashed_password, full_name, role, is_active, created_at, last_login)
     - role CHECK constraint: engineer or admin
     - UNIQUE on email
     - Index on email
   - business_units table
   - tickets table with embedding vector(768) column — always 768 dims (Vertex AI text-embedding-004)
   - incidents table with embedding vector(768) column — same 768 dims
   - chat_sessions table (JSONB messages field)
   - engineer_feedback table
   - All foreign keys and NOT NULL constraints

2. database/migrations/002_pgvector_indexes.sql
   - HNSW index on tickets.embedding (vector_cosine_ops, m=16, ef_construction=64)
   - HNSW index on incidents.embedding (vector_cosine_ops, m=16, ef_construction=64)
   - B-tree index on tickets.business_unit, tickets.status, tickets.ticket_type
   - B-tree index on incidents.business_unit, incidents.severity
   - Index on chat_sessions(engineer_id, updated_at DESC)

3. database/migrations/003_feedback_table.sql
   - Add any missing constraints on engineer_feedback
   - Add index on feedback(session_id)

4. database/seeds/business_units.sql
   - Insert sample BUs: B1 (Business Unit 1), B2 (Business Unit 2)

5. database/db_client.py
   - Async connection pool using asyncpg
   - Context manager for transactions
   - get_db_pool() factory function
   - Environment variable: DATABASE_URL

Use exact schema from ARCHITECTURE.md. Add SQL comments explaining each table's purpose.
```

---
## as per Claude Prompt 1.3
...
Refer to .cursorrules for all conventions. Create services/shared/models.py containing 
all shared Pydantic v2 data models used across all agent services.

Create the file services/shared/__init__.py (empty).

Create services/shared/models.py with these models:

from pydantic import BaseModel, ConfigDict, field_validator, EmailStr
from typing import Any, Optional, Literal
from datetime import datetime
from enum import Enum
import uuid

# ── Auth Models ────────────────────────────────────────────

class UserRole(str, Enum):
    engineer = "engineer"
    admin = "admin"

class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.engineer
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v):
        return v.lower().strip()

class UserLogin(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    engineer_id: str
    role: str

class TokenPayload(BaseModel):
    sub: str        # email
    role: str
    exp: int        # unix timestamp

# ── Business Unit ──────────────────────────────────────────

class BusinessUnit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: Optional[str] = None

# ── Ticket & Incident ──────────────────────────────────────

class Ticket(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    jira_id: str
    business_unit: Optional[str] = None
    ticket_type: Optional[str] = None
    summary: str
    description: Optional[str] = None
    status: Optional[str] = None
    resolution: Optional[str] = None
    discussion: Optional[list[dict]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # embedding excluded from serialization by default
    raw_json: Optional[dict] = None

class Incident(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    jira_id: Optional[str] = None
    business_unit: Optional[str] = None
    title: str
    description: Optional[str] = None
    root_cause: Optional[str] = None
    long_term_fix: Optional[str] = None
    related_tickets: Optional[list[str]] = None
    severity: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    raw_json: Optional[dict] = None

# ── Chat & Session ─────────────────────────────────────────

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: Optional[datetime] = None
    metadata: Optional[dict] = None

class BusinessUnitScope(BaseModel):
    business_units: list[str]
    include_incidents: bool = False

    @field_validator("business_units")
    @classmethod
    def at_least_one_bu(cls, v):
        if not v:
            raise ValueError("At least one business unit must be selected")
        return v

class ChatSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    engineer_id: str
    title: Optional[str] = None
    context_scope: Optional[BusinessUnitScope] = None
    messages: Optional[list[ChatMessage]] = None
    created_at: datetime
    updated_at: datetime

class SessionSummary(BaseModel):
    id: uuid.UUID
    title: Optional[str] = None
    last_message_preview: Optional[str] = None
    updated_at: datetime

# ── Feedback ───────────────────────────────────────────────

class FeedbackRating(str, Enum):
    correct = "correct"
    can_be_better = "can_be_better"
    incorrect = "incorrect"

class EngineerFeedback(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    session_id: uuid.UUID
    message_index: int
    rating: FeedbackRating
    comment: Optional[str] = None
    created_at: Optional[datetime] = None

class FeedbackInput(BaseModel):
    session_id: uuid.UUID
    message_index: int
    rating: FeedbackRating
    comment: Optional[str] = None

class FeedbackSummary(BaseModel):
    total: int
    correct: int
    can_be_better: int
    incorrect: int
    accuracy_pct: float

# ── Agent & Search ─────────────────────────────────────────

class ToolResult(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class SearchResult(BaseModel):
    jira_id: str
    title: str
    summary: Optional[str] = None
    score: float
    result_type: Literal["ticket", "incident"]
    status: Optional[str] = None
    business_unit: Optional[str] = None
    metadata: Optional[dict] = None

class SearchQuery(BaseModel):
    query_text: str
    business_units: list[str]
    include_incidents: bool = False
    top_k: int = 10

    @field_validator("top_k")
    @classmethod
    def top_k_range(cls, v):
        if not 1 <= v <= 50:
            raise ValueError("top_k must be between 1 and 50")
        return v

class AgentRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None
    engineer_id: str
    message: str
    context_scope: BusinessUnitScope
    conversation_history: Optional[list[ChatMessage]] = None

class AgentResponse(BaseModel):
    session_id: Optional[uuid.UUID] = None
    response_text: str
    sources: Optional[list[SearchResult]] = None
    usage_metadata: Optional[dict] = None
...

## PROMPT 1.3 — Shared Pydantic Models

```
Create services/shared/models.py containing all shared Pydantic v2 data models used across services.

Include:

1. User — id, email, full_name, role (engineer/admin), is_active, created_at, last_login
2. UserCreate — email, password, full_name (used for registration input)  # embedding dims always 768
3. UserLogin — email, password (used for login input)
4. TokenResponse — access_token, token_type, engineer_id, role
5. TokenPayload — sub (email), role, exp
6. BusinessUnit — id, code, name
7. Ticket — all fields from tickets table, embedding excluded from default serialization
8. Incident — all fields from incidents table, embedding excluded
9. ChatMessage — role (user/assistant/system), content, timestamp, metadata dict
10. ChatSession — id, engineer_id, title, context_scope (BusinessUnitScope), messages list, timestamps
11. BusinessUnitScope — business_units: list[str], include_incidents: bool
12. FeedbackRating — Enum: correct, can_be_better, incorrect
13. EngineerFeedback — session_id, message_index, rating, comment
14. ToolResult — success: bool, data: Any, error: str | None
15. SearchQuery — query_text, business_units, include_incidents, top_k (default 10)
16. SearchResult — jira_id, title, summary, score, result_type (ticket/incident), metadata
17. AgentRequest — session_id, engineer_id, message, context_scope, conversation_history
18. AgentResponse — session_id, response_text, sources: list[SearchResult], usage_metadata

All models must use:
- field validators where appropriate
- model_config = ConfigDict(from_attributes=True) for ORM compatibility
- Proper Optional types with defaults
- datetime fields as datetime with timezone
```

---
---
## 1.3 from claude
...
Refer to .cursorrules for all conventions. Create the JIRA webhook receiver service 
at pipeline/webhook_receiver/.

This is a lightweight FastAPI Cloud Run service that receives JIRA webhook POST 
requests and publishes them to Cloud Pub/Sub.

Create these files:

1. pipeline/webhook_receiver/__init__.py (empty)

2. pipeline/webhook_receiver/main.py

A FastAPI application with:

Imports:
- fastapi, uvicorn
- google.cloud.pubsub_v1
- structlog
- hashlib, hmac (for webhook signature validation)
- os, json
- python-dotenv load_dotenv

Environment variables to read:
- JIRA_WEBHOOK_SECRET
- PUBSUB_TOPIC
- GCP_PROJECT_ID

GET /health
- No auth
- Returns: {"status": "ok", "service": "jira-webhook-receiver"}

POST /webhook/jira
- Validates JIRA webhook signature from X-Hub-Signature header
  - Compute HMAC-SHA256 of request body using JIRA_WEBHOOK_SECRET
  - Compare with header value (format: "sha256=<hex>")
  - Return 401 if invalid or header missing
- Parse webhook payload (JSON body)
- Extract: issue_key (from issue.key), event_type (from webhookEvent), 
  project_key (from issue.fields.project.key), timestamp (current UTC)
- Publish message to Pub/Sub topic:
  {
    "jira_id": issue_key,
    "event_type": event_type,
    "project_key": project_key,
    "timestamp": timestamp
  }
- Return 200: {"status": "received", "jira_id": issue_key}
- Log each received webhook at INFO level with jira_id and event_type
- Return 400 if payload cannot be parsed
- Handle Pub/Sub publish errors gracefully — log error, return 500

Startup:
- Load .env.local
- Initialise structlog with JSON format if LOG_FORMAT=json else pretty console
- Initialise Pub/Sub PublisherClient

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=True)

3. pipeline/webhook_receiver/Dockerfile

FROM python:3.11-slim
WORKDIR /app
RUN adduser --disabled-password --gecos '' appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]

4. pipeline/webhook_receiver/requirements.txt

fastapi==0.111.0
uvicorn==0.30.0
google-cloud-pubsub==2.21.1
structlog==24.1.0
python-dotenv==1.0.1
pydantic>=2.0
...

---

## PROMPT 1.3b — JIRA Webhook Receiver

```
Create the JIRA webhook receiver service at pipeline/webhook_receiver/.

This is a lightweight Cloud Run service that receives JIRA webhook POST requests
and publishes them to Cloud Pub/Sub for the embedding worker to process.

1. pipeline/webhook_receiver/main.py
   - FastAPI app
   - POST /webhook/jira
     - Validates JIRA webhook secret (JIRA_WEBHOOK_SECRET env var) from header X-Hub-Signature
     - Parses webhook payload: issue key, event type (created/updated/deleted)
     - Publishes message to Pub/Sub topic (PUBSUB_TOPIC env var)
     - Message format: { jira_id, event_type, project_key, timestamp }
     - Returns 200 immediately (async — do not wait for embedding)
     - Returns 401 if webhook secret invalid
   - GET /health — no auth required
   - Structured logging: log each received webhook event

2. pipeline/webhook_receiver/requirements.txt
   - fastapi, uvicorn, google-cloud-pubsub, structlog, pydantic>=2.0

3. pipeline/webhook_receiver/Dockerfile
   - Python 3.11 slim, non-root user

Add JIRA_WEBHOOK_SECRET to .env.example — generate a random secret and configure
it in JIRA webhook settings so JIRA signs its webhook payloads.
```

---
---
## prompt 1.4 by claude
Refer to .cursorrules for all conventions. Create the JIRA REST API client at 
pipeline/embedding_worker/jira_client.py

Also create pipeline/embedding_worker/__init__.py (empty)

Create pipeline/embedding_worker/jira_client.py with:

Imports:
- httpx (async)
- structlog
- python-dotenv
- datetime, asyncio
- Custom exception class

Environment variables:
- JIRA_BASE_URL
- JIRA_API_TOKEN  
- JIRA_USER_EMAIL

Class: JIRAClient

__init__(self):
    - Read env vars
    - Create httpx.AsyncClient with:
      - base_url = JIRA_BASE_URL
      - auth = (JIRA_USER_EMAIL, JIRA_API_TOKEN) — Basic auth
      - headers = {"Accept": "application/json", "Content-Type": "application/json"}
      - timeout = 30 seconds
    - Initialise structlog logger

async def get_ticket(self, jira_id: str) -> dict:
    - GET /rest/api/3/issue/{jira_id}
    - Query params: fields=summary,description,status,resolution,
      comment,issuetype,priority,created,updated,labels,project
    - Returns full issue dict
    - Raises JIRAClientError if 404
    - Raises JIRAClientError if other error

async def search_tickets(self, jql: str, start_at: int = 0, 
                         max_results: int = 100) -> dict:
    - GET /rest/api/3/search
    - Params: jql, startAt, maxResults, 
      fields=summary,description,status,resolution,
      comment,issuetype,priority,created,updated,labels,project
    - Returns {"issues": [...], "total": N, "startAt": N}

async def get_updated_since(self, since: datetime, 
                             project_keys: list[str]) -> list[dict]:
    - Builds JQL: project in (KEY1,KEY2) AND updated >= "YYYY-MM-DD HH:MM"
      ORDER BY updated ASC
    - Paginates automatically: loops with startAt until all results fetched
    - Returns flat list of all issues

async def get_issue_comments(self, jira_id: str) -> list[dict]:
    - GET /rest/api/3/issue/{jira_id}/comment
    - Returns list of {author, body, created} dicts

def extract_plain_text(self, node: dict | str | None) -> str:
    - Converts JIRA
---
## PROMPT 1.4 — JIRA Client

```
Create pipeline/embedding_worker/jira_client.py — a robust async JIRA REST API client.

Requirements:
- Use httpx.AsyncClient with connection pooling
- Auth via Bearer token (JIRA_API_TOKEN env var)
- Base URL from JIRA_BASE_URL env var

Implement these methods:

1. get_ticket(jira_id: str) -> dict
   - GET /rest/api/3/issue/{jira_id}
   - Include fields: summary, description, status, resolution, comment, issuetype, priority, created, updated, labels, customfield for BU

2. search_tickets(jql: str, start_at: int = 0, max_results: int = 100) -> dict
   - GET /rest/api/3/search with JQL
   - Returns issues list + total count

3. get_issue_comments(jira_id: str) -> list[dict]
   - GET /rest/api/3/issue/{jira_id}/comment
   - Returns comment body + author + created

4. get_updated_since(since: datetime, project_keys: list[str]) -> list[dict]
   - JQL: project in (...) AND updated >= "since_date" ORDER BY updated ASC
   - Paginates automatically until all results fetched

5. extract_plain_text(jira_adf: dict) -> str
   - Converts JIRA Atlassian Document Format (ADF) rich text to plain text
   - Handles: paragraph, text, codeBlock, bulletList, orderedList, heading nodes

Include:
- Retry logic with exponential backoff (max 3 retries) on 429 and 5xx
- Rate limit handling: respect Retry-After header
- Structured logging on each call
- Custom JIRAClientError exception
```

---
## prompt 1.5 by claude
Refer to .cursorrules for all conventions. Create the embedding worker pipeline 
files in pipeline/embedding_worker/

Create these files:

1. pipeline/embedding_worker/embedder.py

Imports:
- vertexai
- vertexai.language_models TextEmbeddingModel
- asyncio, os
- structlog
- concurrent.futures ThreadPoolExecutor

Environment variables:
- GCP_PROJECT_ID
- VERTEX_AI_LOCATION (default: us-central1)
- EMBEDDING_MODEL (default: text-embedding-004)

Module-level initialisation (runs once at import):
- Call vertexai.init(project=GCP_PROJECT_ID, location=VERTEX_AI_LOCATION)
- Load model: _model = TextEmbeddingModel.from_pretrained(EMBEDDING_MODEL)
- Create ThreadPoolExecutor: _executor = ThreadPoolExecutor(max_workers=4)
- Initialise structlog logger

async def embed_text(text: str) -> list[float]:
    - Truncate text to 2000 characters if longer
    - Run model.get_embeddings([text]) in thread pool executor
      (use asyncio.get_event_loop().run_in_executor)
    - Return embeddings[0].values as list[float]
    - Log: embedding_generated with text_length and dims

async def embed_batch(texts: list[str]) -> list[list[float]]:
    - Process in batches of 5 (Vertex AI limit)
    - For each batch: call model.get_embeddings(batch) in executor
    - Sleep 1 second between batches to respect rate limits
    - Return flat list of all embedding vectors
    - Log progress: "Embedded batch N/total"

2. pipeline/embedding_worker/processor.py

Imports:
- sys, os
- jira_client JIRAClient (from same package)

def prepare_ticket_text(ticket: dict) -> str:
    - Extract and concatenate:
      1. f"Issue: {ticket.get('summary', '')}"
      2. f"Type: {ticket.get('ticket_type', '')} | Status: {ticket.get('status', '')}"
      3. If description: f"Description: {description[:1500]}"
      4. If resolution: f"Resolution: {resolution}"
      5. Last 3 comments from discussion list:
         f"Comment: {comment['body'][:300]}" for each
    - Join all parts with double newline
    - Truncate final text to 3000 characters
    - Return cleaned text

def prepare_incident_text(incident: dict) -> str:
    - Extract and concatenate:
      1. f"Incident: {incident.get('title', '')}"
      2. f"Severity: {incident.get('severity', '')}"
      3. If description: f"Description: {description[:1000]}"
      4. If root_cause: f"Root Cause: {root_cause}"
      5. If long_term_fix: f"Long-term Fix: {long_term_fix}"
    - Join with double newline
    - Truncate to 3000 characters
    - Return cleaned text

3. pipeline/embedding_worker/upsert.py

Imports:
- asyncpg
- json
- structlog
- datetime

async def upsert_ticket(pool: asyncpg.Pool, 
                        ticket_data: dict, 
                        embedding: list[float]) -> None:
    - Insert into tickets table using ON CONFLICT (jira_id) DO UPDATE
    - Fields: jira_id, business_unit, ticket_type, summary, description,
      status, resolution, discussion (as JSONB), created_at, updated_at,
      embedding (cast to vector), raw_json (as JSONB)
    - Log: ticket_upserted with jira_id

async def upsert_incident(pool: asyncpg.Pool,
                          incident_data: dict,
                          embedding: list[float]) -> None:
    - Insert into incidents table using ON CONFLICT (jira_id) DO UPDATE
    - Fields: jira_id, business_unit, title, description, root_cause,
      long_term_fix, related_tickets (as JSONB), severity,
      resolved_at, created_at, updated_at, embedding (cast to vector),
      raw_json (as JSONB)
    - Log: incident_upserted with jira_id

4. pipeline/embedding_worker/main.py

Imports:
- asyncio, os
- asyncpg
- redis.asyncio as redis
- structlog
- python-dotenv load_dotenv
- embedder, processor, upsert, jira_client from same package

Environment variables:
- SYNC_MODE (delta | full, default: delta)
- DATABASE_URL
- REDIS_URL
- BU_B1_PROJECTS, BU_B2_PROJECTS
- INCIDENT_ISSUE_TYPES

async def main():
    - Load .env.local
    - Initialise structlog
    - Create asyncpg pool from DATABASE_URL
    - Create Redis client from REDIS_URL
    - Log: sync_started with mode

    If SYNC_MODE == "full":
        - Get all project keys from BU_B1_PROJECTS + BU_B2_PROJECTS env vars
        - Search all tickets via JQL: project in (...) ORDER BY created ASC
        - Process each: prepare_ticket_text → embed_text → upsert_ticket
        - Search incidents: issuetype in (INCIDENT_ISSUE_TYPES) ORDER BY created ASC
        - Process each: prepare_incident_text → embed_text → upsert_incident

    If SYNC_MODE == "delta":
        - Read last_sync_time from Redis key: "embedding_worker:last_sync"
        - Default to 24 hours ago if not set
        - Fetch tickets updated since last_sync_time
        - Process same as full sync but filtered by update time
        - Store current time in Redis as new last_sync_time

    - Log: sync_completed with total_processed, errors, duration_seconds
    - Close pool and Redis connection

if __name__ == "__main__":
    asyncio.run(main())

5. pipeline/embedding_worker/requirements.txt

google-cloud-aiplatform==1.57.0
vertexai==1.57.0
asyncpg==0.29.0
redis==5.0.4
httpx==0.27.0
structlog==24.1.0
python-dotenv==1.0.1
pydantic>=2.0
---

## PROMPT 1.5 — Embedding Worker Pipeline

```
Create the full data ingestion pipeline in pipeline/embedding_worker/.

Files:

1. pipeline/embedding_worker/embedder.py
   - Use Vertex AI text-embedding-004 (768 dimensions) for all embeddings
   - Authentication via GOOGLE_APPLICATION_CREDENTIALS env var (no API key needed)
   - async embed_text(text: str) -> list[float]
   - async embed_batch(texts: list[str]) -> list[list[float]] — batches of max 5 at a time
   - Truncate input to 2000 chars before embedding
   - Always returns 768-dim vectors
   - Use vertexai SDK: TextEmbeddingModel.from_pretrained("text-embedding-004")
   - Initialise vertexai with GCP_PROJECT_ID and VERTEX_AI_LOCATION from env vars
   - Load model once at module level, reuse for all calls
   - Run get_embeddings() in thread pool executor to avoid blocking async loop

2. pipeline/embedding_worker/upsert.py
   - async upsert_ticket(pool, ticket_data: dict, embedding: list[float]) -> None
   - async upsert_incident(pool, incident_data: dict, embedding: list[float]) -> None
   - Uses ON CONFLICT (jira_id) DO UPDATE for idempotency
   - Serialises discussion/raw_json as JSONB

3. pipeline/embedding_worker/processor.py
   - prepare_ticket_text(ticket: dict) -> str
     Concatenates: summary + description + resolution + comment bodies
     (stripped of formatting, max 3000 chars)
   - prepare_incident_text(incident: dict) -> str
     Concatenates: title + description + root_cause + long_term_fix

4. pipeline/embedding_worker/main.py
   - Cloud Run Job entry point
   - Reads mode from env: SYNC_MODE = "delta" | "full"
   - Delta mode: reads last_sync_time from Redis, fetches JIRA tickets updated since then
   - Full mode: paginates all tickets via JQL project in (B1_PROJECT, B2_PROJECT)
   - For each ticket: process text → embed → upsert
   - Updates last_sync_time in Redis on completion
   - Logs total processed, errors, duration

5. pipeline/embedding_worker/Dockerfile
   - Python 3.11 slim base
   - Non-root user
   - requirements.txt install

6. pipeline/embedding_worker/requirements.txt
   - httpx, asyncpg, redis, google-cloud-aiplatform, vertexai, structlog, pydantic>=2.0
```

