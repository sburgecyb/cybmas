# Cursor Prompts — Quick Reference Index

Use this as your build order. Run prompts sequentially within each phase. Each prompt is self-contained and builds on the outputs of prior prompts.

---

## Phase 1 — Foundation (Start Here)
File: `cursor-prompts/PHASE_1_FOUNDATION.md`

| # | Prompt | Output | Dependencies |
|---|---|---|---|
| 1.1 | Project Scaffold | Monorepo structure, docker-compose, .env.example | None |
| 1.2 | Database Schema | SQL migrations (001, 002, 003), seed files | 1.1 |
| 1.3 | Shared Pydantic Models | services/shared/models.py | 1.2 |
| 1.3b | JIRA Webhook Receiver | pipeline/webhook_receiver/ (Cloud Run service) | 1.1 |
| 1.4 | JIRA Client | pipeline/embedding_worker/jira_client.py | 1.3 |
| 1.5 | Embedding Worker Pipeline | Full pipeline: embedder, processor, upsert, main | 1.3, 1.4 |

---

## Phase 2 — Agent Services
File: `cursor-prompts/PHASE_2_AGENTS.md`

| # | Prompt | Output | Dependencies |
|---|---|---|---|
| 2.1 | Vector Search & JIRA Tools | l1l2-agent/tools/: vector_search, jira_fetch | 1.2, 1.3 |
| 2.2 | Incident Search Tools | l3-agent/tools/: incident_search, rca_fetch, cross_ref | 1.2, 1.3 |
| 2.3 | Summarize Skill | shared/skills/summarize.py | 1.3 |
| 2.4 | L1/L2 Resolution Agent | services/l1l2-agent/ (complete service) | 2.1, 2.3 |
| 2.5 | L3 Resolutions Agent | services/l3-agent/ (complete service) | 2.2, 2.3 |
| 2.6 | Session & Feedback Agent | services/session-agent/ (complete service) | 1.2, 1.3 |
| 2.7 | Orchestrator Agent | services/orchestrator/ (complete service) | 2.4, 2.5, 2.6 |

---

## Phase 3 — API Gateway & Frontend
File: `cursor-prompts/PHASE_3_API_FRONTEND.md`

| # | Prompt | Output | Dependencies |
|---|---|---|---|
| 3.1 | API Gateway Service | services/api-gateway/ (complete service) | 2.7 |
| 3.2 | Frontend Chat Interface | frontend/ core components + pages | 3.1 |
| 3.3 | Frontend Auth & Sessions | JWT login page, useAuth/useChat/useSession hooks | 3.2 |
| 3.4 | Source Citations Component | frontend/components/SourcesPanel.tsx | 3.2 |

---

## Phase 4 — Infrastructure & Testing
File: `cursor-prompts/PHASE_4_INFRA_TESTING.md`

| # | Prompt | Output | Dependencies |
|---|---|---|---|
| 4.1 | Terraform GCP Infrastructure | infra/ modules + environments | 1.1 |
| 4.2 | Cloud Build CI/CD | cloudbuild.yaml (prod), cloudbuild.dev.yaml, cloudbuild.infra.yaml, cloudbuild.rollback.yaml, cloudbuild.pipeline.yaml | All phases |
| 4.2b | Initial GCP Setup Script | scripts/gcp_setup.sh — enables APIs, creates Terraform state bucket, Artifact Registry, GitHub connection | 4.1 |
| 4.3 | Unit Tests | tests/unit/ for all tools and skills | Phase 2 |
| 4.4 | Integration Tests | tests/integration/ with testcontainers | Phase 2 |
| 4.5 | Observability | Structured logging, tracing, alerts | All phases |
| 4.6 | Local Dev Setup | Makefile, dev scripts, seed scripts | All phases |

---

---

## Phase 5 — Demo Seed Data
File: `cursor-prompts/PHASE_SEED_DATA.md`

Run after Phase 4.6 (Local Dev Setup). Requires Vertex AI credentials working (`python test_credentials.py` passes).

| # | Prompt | Output | Dependencies |
|---|---|---|---|
| SD.1 | Demo Seed Data Script | scripts/seed_demo_data.py — 30 tickets + 5 incidents with REAL Vertex AI embeddings | 1.2, credentials |
| SD.2 | Seed Users Script | scripts/seed_users.py — 3 default users (admin + 2 engineers) | 1.2 |
| SD.3 | Orchestrator Update | scripts/seed_test_data.py updated to run SD.1 + SD.2 in order | SD.1, SD.2 |

**After running `make seed` the chatbot can immediately answer realistic questions like:**
- "We're seeing database timeouts in the reservation search"
- "What happened with the March payment outage?"
- "Are there any incidents related to overbooking?"
- "What is the status of B1-1008?"

---

## Usage Tips for Cursor

1. **Open the relevant phase file** in Cursor before starting
2. **Copy one prompt block at a time** — paste into Cursor chat
3. **Reference context files**: Before each prompt, tell Cursor:
   - "Refer to ARCHITECTURE.md for the system design"
   - "Refer to PROJECT_STANDARDS.md for conventions"
   - "Refer to .cursorrules for code quality rules"
4. **Review generated code** before moving to the next prompt
5. **Run tests** at end of each phase: `make test`

## Re-generation Tips

If a prompt generates incorrect output:

- For DB schema issues: "The schema should match ARCHITECTURE.md exactly. Regenerate the migration file."
- For ADK agent issues: "Follow the Google ADK agent definition pattern from AGENT_PROMPTS.md"
- For tool output issues: "All tools must return a ToolResult object as defined in shared/models.py"
