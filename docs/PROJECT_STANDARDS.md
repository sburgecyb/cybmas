# Project Standards & Repository Structure

## Repository Layout

```
cybmas/
├── README.md
├── ARCHITECTURE.md
├── .env.example
├── docker-compose.yml            # local dev stack (postgres, redis)
│
├── frontend/                     # Next.js 14 App Router
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx              # redirect to /chat
│   │   └── chat/
│   │       ├── page.tsx          # main chat page
│   │       └── [sessionId]/
│   │           └── page.tsx      # session resume
│   ├── components/
│   │   ├── ChatWindow.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── FeedbackWidget.tsx
│   │   ├── BusinessUnitSelector.tsx
│   │   ├── IncidentToggle.tsx
│   │   └── SessionSidebar.tsx
│   ├── hooks/
│   │   ├── useChat.ts
│   │   └── useSession.ts
│   ├── lib/
│   │   └── api.ts                # typed API client
│   └── Dockerfile
│
├── services/
│   ├── api-gateway/              # Cloud Run — API Gateway service
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── chat.py
│   │   │   └── sessions.py
│   │   ├── middleware/
│   │   │   ├── auth.py
│   │   │   └── rate_limit.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   ├── orchestrator/             # Cloud Run — Orchestrator Agent
│   │   ├── agent.py              # Google ADK agent definition
│   │   ├── intent_classifier.py
│   │   ├── router.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   ├── l1l2-agent/               # Cloud Run — L1/L2 Resolution Agent
│   │   ├── agent.py
│   │   ├── tools/
│   │   │   ├── vector_search.py
│   │   │   ├── jira_fetch.py
│   │   │   └── ticket_status.py
│   │   ├── skills/
│   │   │   └── summarize.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   ├── l3-agent/                 # Cloud Run — L3 Resolutions Agent
│   │   ├── agent.py
│   │   ├── tools/
│   │   │   ├── incident_search.py
│   │   │   ├── rca_fetch.py
│   │   │   └── cross_ref_tickets.py
│   │   ├── skills/
│   │   │   └── summarize.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   └── session-agent/            # Cloud Run — Session & Feedback Agent
│       ├── agent.py
│       ├── tools/
│       │   ├── session_store.py
│       │   └── feedback_store.py
│       ├── requirements.txt
│       └── Dockerfile
│
├── pipeline/                     # Data ingestion pipeline
│   ├── embedding_worker/
│   │   ├── main.py               # Cloud Run Job entry point
│   │   ├── jira_client.py
│   │   ├── embedder.py           # Vertex AI text-embedding-gecko
│   │   ├── upsert.py             # pgvector upsert logic
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── scheduler/
│       └── cloud_scheduler_config.yaml
│
├── infra/                        # Terraform
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── modules/
│   │   ├── cloud_run/
│   │   ├── cloud_sql/
│   │   ├── pubsub/
│   │   └── memorystore/
│   └── environments/
│       ├── dev/
│       └── prod/
│
├── database/
│   ├── migrations/
│   │   ├── 001_initial_schema.sql
│   │   ├── 002_pgvector_indexes.sql
│   │   └── 003_feedback_table.sql
│   └── seeds/
│       └── business_units.sql
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## Coding Standards

### Python (Services & Pipeline)

- Python 3.11+
- Type hints on all functions
- `pydantic` v2 for data models and validation
- `fastapi` for HTTP services (API Gateway)
- `google-cloud-adk` for agent definitions
- `asyncpg` for async PostgreSQL access
- `redis.asyncio` for async Redis
- All secrets via environment variables (Secret Manager in GCP)
- Structured logging with `structlog`, emitting JSON
- No bare `except:` — always catch specific exceptions
- All tools return typed `ToolResult` objects

### TypeScript / Next.js (Frontend)

- Next.js 14 App Router with Server Components
- `zod` for runtime validation of API responses
- `tailwindcss` for styling
- No `any` types — use proper generics
- SSE responses consumed via `EventSource` or `fetch` with `ReadableStream`
- All API calls go through `lib/api.ts` — no raw `fetch` in components

### Terraform

- All GCP resources tagged with `project`, `env`, `component`
- Remote state in GCS backend
- Separate workspaces for dev / prod
- No hardcoded credentials — use `google_secret_manager_secret_version`

---

## Environment Variables

```
# API Gateway
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_API_TOKEN=...
GCP_PROJECT_ID=...

# JWT Authentication (no external auth service)
JWT_SECRET_KEY=...   # generate: python -c "import secrets; print(secrets.token_hex(32))"
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=8

# Agents
ORCHESTRATOR_ENDPOINT=https://orchestrator-....run.app
L1L2_AGENT_ENDPOINT=https://l1l2-agent-....run.app
L3_AGENT_ENDPOINT=https://l3-agent-....run.app
SESSION_AGENT_ENDPOINT=https://session-agent-....run.app
VERTEX_AI_LOCATION=us-central1
EMBEDDING_MODEL=text-embedding-004

# Pipeline
PUBSUB_TOPIC=jira-events
PUBSUB_SUBSCRIPTION=embedding-worker-sub
GCS_BUCKET=cybmas-raw
```

---

## ADK Agent Convention

Every agent module must export an `agent` instance using `LlmAgent` with `model="gemini-1.5-flash"`. Authentication is automatic via `GOOGLE_APPLICATION_CREDENTIALS`.

```python
from google.adk.agents import LlmAgent
from google.adk.tools import tool

agent = LlmAgent(
    name="l1l2_resolution_agent",
    model="gemini-1.5-flash",  # Vertex AI via GOOGLE_APPLICATION_CREDENTIALS
    description="...",
    instruction="...",
    tools=[...],
)
```

Tools are plain Python functions decorated with `@tool` from `google.adk.tools`.
The function docstring is critical — ADK uses it to decide when to call the tool.
Skills (compound multi-step prompting) live in `skills/` and are wrapped as `@tool` functions.

---

## Branching & CI/CD

- `main` → production
- `develop` → staging / integration
- `feature/*` → PRs to develop
- Cloud Build triggers: push to `main` → deploy prod, push to `develop` → deploy dev
- Tests must pass before merge: `pytest tests/unit tests/integration`

---

## Observability Standards

- Every Cloud Run request must emit a structured log with: `trace_id`, `session_id`, `agent_name`, `tool_name`, `latency_ms`, `tokens_used`
- Alerts on: p95 latency > 5s, error rate > 1%, embedding worker lag > 10 min
- Distributed tracing via Cloud Trace — propagate `X-Cloud-Trace-Context` header across services
