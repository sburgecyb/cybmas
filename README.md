# cybmas — Multi-Agent Technical Support System

An AI-powered technical support chatbot for L1/L2/L3 support engineers, built on **Google ADK**, deployed on **GCP**.

## What It Does

- **UC1 — Ticket Resolution**: Engineers describe problems in plain English. The system searches thousands of historical JIRA tickets scoped to their business unit and surfaces relevant resolutions.
- **UC2 — Incident Management**: L3 engineers search past production incidents and RCAs. Cross-reference incidents with JIRA tickets. Follow-up investigation of specific incidents.

## Architecture

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design.

**Key components:**
- 3 specialised ADK agents (L1/L2 Resolution, L3 Resolutions, Session & Feedback)
- 1 Orchestrator ADK agent for routing
- 1 API Gateway (FastAPI + Cloud Run)
- 1 Webhook Receiver (Cloud Run service — receives JIRA events → Pub/Sub)
- PostgreSQL + pgvector for semantic search
- JIRA as source of truth, ingested via real-time webhooks + scheduled delta/full sync

## Quick Start (Local Dev)

```bash
# Prerequisites: Python 3.11+, Node 18+, Docker Desktop
# GCP service account JSON key at C:\keys\cybmasacn.json

# 1. Clone and setup
git clone <repo>
cd cybmas
cp .env.example .env.local
# Edit .env.local — set GCP_PROJECT_ID, JIRA credentials, JWT_SECRET_KEY

# 2. Start Postgres (pgvector) + Redis via Docker Compose
docker compose up -d
# Migrations in database/migrations/ run automatically on first start
# Postgres:  localhost:5432  |  Redis: localhost:6379

# 3. Seed reference data
docker compose exec postgres psql -U postgres -d cybmas -f /docker-entrypoint-initdb.d/../seeds/business_units.sql

# 4. Create and activate Python virtual environment
python -m venv venv
venv\Scripts\Activate.ps1   # Windows PowerShell

# 5. Install Google ADK and all dependencies
pip install google-adk google-cloud-aiplatform vertexai google-generativeai
pip install fastapi uvicorn asyncpg redis httpx structlog pydantic python-jose passlib

# 6. Verify Google credentials work
python test_credentials.py    # should print 768-dim embeddings + Gemini response

# 7. Start all backend services
make up

# 8. Start frontend
cd frontend
npm install
npm run dev       # http://localhost:3000
```

**Local prerequisites:**
- Docker Desktop (provides Postgres 15 + pgvector and Redis 7)
- Service account JSON key at `C:\keys\cybmasacn.json` with Vertex AI User role
- Python virtual environment activated before running any `pip` or `adk` commands

See [docs/ADK_SETUP.md](docs/ADK_SETUP.md) for detailed ADK + Vertex AI setup instructions.

## Development

| Command | Description |
|---|---|
| `make setup` | First-time local setup |
| `make up` | Start all services |
| `make down` | Stop all services |
| `make test` | Run unit tests |
| `make test-int` | Run integration tests |
| `make migrate` | Run pending DB migrations |
| `make seed` | Seed test data |
| `make logs` | Tail all service logs |

## Documentation

| Document | Description |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system architecture |
| [PROJECT_STANDARDS.md](docs/PROJECT_STANDARDS.md) | Code standards and repo structure |
| [AGENT_PROMPTS.md](docs/AGENT_PROMPTS.md) | Agent system prompts and prompt design |
| [DATA_PIPELINE.md](docs/DATA_PIPELINE.md) | JIRA → pgvector pipeline design |

## Cursor Build Prompts

The system was built using AI-assisted development. Prompts are organised by phase:

| Phase | File | Scope |
|---|---|---|
| 1 | [PHASE_1_FOUNDATION.md](cursor-prompts/PHASE_1_FOUNDATION.md) | Scaffold, DB schema, JIRA client, pipeline |
| 2 | [PHASE_2_AGENTS.md](cursor-prompts/PHASE_2_AGENTS.md) | All ADK agents and tools |
| 3 | [PHASE_3_API_FRONTEND.md](cursor-prompts/PHASE_3_API_FRONTEND.md) | API Gateway and Next.js frontend |
| 4 | [PHASE_4_INFRA_TESTING.md](cursor-prompts/PHASE_4_INFRA_TESTING.md) | Terraform, CI/CD, tests |

## GCP Deployment

```bash
# Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Deploy infrastructure
cd infra/environments/dev
terraform init
terraform apply

# Deploy services
gcloud builds submit --config cloudbuild.dev.yaml
```

## Tech Stack

| Layer | Local Dev | Production (GCP) |
|---|---|---|
| Agents | Google ADK | Google ADK |
| LLM | Gemini 1.5 Flash (Vertex AI) | Gemini 1.5 Flash (Vertex AI) |
| Embeddings | text-embedding-004 (Vertex AI, 768d) | text-embedding-004 (Vertex AI, 768d) |
| Backend | Python 3.11 + FastAPI | Python 3.11 + FastAPI |
| Frontend | Next.js 14 + TypeScript + Tailwind | Next.js 14 + TypeScript + Tailwind |
| Database | Local PostgreSQL + pgvector | Cloud SQL PostgreSQL 15 + pgvector |
| Cache | Local Redis / Memurai (WSL) | Memorystore for Redis |
| Infra | Local processes | Terraform + Cloud Run + Cloud Build |
| Tickets | JIRA Cloud | JIRA Cloud |
| Google Auth | Service account JSON key | Cloud Run attached service account |
| User Auth | JWT (python-jose + passlib) | JWT (python-jose + passlib) |

## Security — Secrets Management

- **Never commit** `.env.local` or `keys/` folder — both are in `.gitignore`
- **Local dev**: secrets in `.env.local`, Google credentials via `keys/cybmasacn.json`
- **Production**: all secrets in GCP Secret Manager, mounted to Cloud Run as env vars
- **Service accounts**: each Cloud Run service has its own SA with least-privilege access
- See [docs/SECRETS.md](docs/SECRETS.md) for full secrets inventory and rotation guide

---

## Contributing

- Branch from `develop`
- PRs require unit + integration tests passing
- Follow `.cursorrules` for code style
