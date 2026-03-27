# Cursor Build Prompts — Phase 4: Infrastructure, Testing & Deployment

---

## PROMPT 4.1 — Terraform: Core GCP Infrastructure

```
Create Terraform infrastructure for the cybmas system targeting GCP.

infra/main.tf — root module wiring all modules together
infra/variables.tf — project_id, region (default: us-central1), env (dev/prod)
infra/outputs.tf — Cloud Run service URLs, DB connection string, bucket name

Create modules:

1. infra/modules/cloud_sql/main.tf
   - google_sql_database_instance: postgres 15, private IP only
   - Enable database flags: cloudsql.enable_pgvector = on
   - google_sql_database: name = support_agent
   - google_sql_user: password from Secret Manager
   - google_service_networking_connection for private IP

2. infra/modules/cloud_run/main.tf
   - Reusable module for deploying Cloud Run services
   - Secrets mounted as environment variables using secret_key_ref:
     env { name = "JWT_SECRET_KEY" value_source { secret_key_ref { secret = var.jwt_secret_id version = "latest" } } }
   - Variables: service_name, image, env_vars, secrets, min_instances, max_instances, memory, cpu
   - IAM: allUsers invoker for API Gateway only; internal-only for all agent services
   - Service account with appropriate roles
   - VPC connector for private Cloud SQL access

2b. infra/modules/cloud_run_jobs/main.tf
   - Module for Cloud Run Jobs (embedding worker)
   - Variables: job_name, image, env_vars, secrets, parallelism, task_count
   - Service account with Vertex AI User + Cloud SQL Client roles
   - Triggered by Pub/Sub push subscription
   - Timeout: 3600 seconds (1 hour for full sync)

2c. infra/api_gateway_openapi.yaml
   - OpenAPI 3.0 spec for GCP API Gateway
   - Defines all routes: /api/auth/*, /api/chat, /api/sessions/*, /api/feedback/*
   - x-google-backend extensions pointing to each Cloud Run service URL
   - Security: JWT bearer token on all routes except /health and /api/auth/login
   - CORS configuration for frontend domain

3. infra/modules/pubsub/main.tf
   - google_pubsub_topic: jira-events
   - google_pubsub_subscription: embedding-worker-sub
   - Dead letter topic: jira-events-dlq
   - Message retention: 7 days

4. infra/modules/memorystore/main.tf
   - google_redis_instance: STANDARD_HA tier in prod, BASIC in dev
   - Private IP in same VPC
   - Version: REDIS_7_0

5. infra/modules/secret_manager/main.tf
   - Secrets: database_password, jira_api_token, jira_webhook_secret, jwt_secret_key
   - IAM binding: each Cloud Run service SA can access its needed secrets

6. infra/modules/storage/main.tf
   - google_storage_bucket: cybmas-raw-{project_id}
   - Lifecycle rule: move to Nearline after 90 days
   - Versioning enabled

7. infra/modules/artifact_registry/main.tf
   - google_artifact_registry_repository: name=cybmas, format=DOCKER, location=us-central1
   - IAM: grant Cloud Build SA write access
   - IAM: grant all Cloud Run service accounts read access

8. infra/modules/cicd/main.tf
   - google_cloudbuild_trigger for prod (push to main branch):
     - Connects to GitHub repo
     - filename = "cloudbuild.yaml"
     - substitutions: _PROJECT_ID, _REGION, _ENV=prod
   - google_cloudbuild_trigger for dev (push to develop branch):
     - filename = "cloudbuild.dev.yaml"
     - substitutions: _PROJECT_ID, _REGION, _ENV=dev
   - google_cloudbuild_trigger for infra (manual only):
     - filename = "cloudbuild.infra.yaml"
     - disabled = true by default (must enable manually)
   - Cloud Build SA IAM roles:
     - roles/run.admin — deploy Cloud Run services
     - roles/iam.serviceAccountUser — act as Cloud Run SAs
     - roles/cloudsql.admin — run migrations
     - roles/secretmanager.secretAccessor — read secrets during build
     - roles/storage.admin — push/pull Artifact Registry images
     - roles/artifactregistry.writer — push Docker images

9. infra/environments/dev/main.tf
   - Instantiates all modules with dev settings (smaller instances, BASIC redis)

10. infra/environments/prod/main.tf
    - Instantiates all modules with prod settings

Use:
- google provider ~> 5.0
- Backend: GCS bucket for state
- All resources tagged: env, project, managed-by=terraform
```

---

## PROMPT 4.1b — Terraform: Secret Manager & IAM Bindings

```
Extend the Terraform infrastructure with complete Secret Manager resources and per-service IAM bindings.

File: infra/modules/secret_manager/main.tf

1. Create Secret Manager secrets (empty — values populated via gcloud CLI or CI):
   - google_secret_manager_secret: database_password
   - google_secret_manager_secret: jira_api_token
   - google_secret_manager_secret: jira_webhook_secret
   - google_secret_manager_secret: jwt_secret_key
   - All secrets: replication = automatic, labels = {env, project}

2. Create service accounts for each Cloud Run service:
   - google_service_account: api_gateway_sa
   - google_service_account: orchestrator_sa
   - google_service_account: l1l2_agent_sa
   - google_service_account: l3_agent_sa
   - google_service_account: session_agent_sa
   - google_service_account: embedding_worker_sa
   - google_service_account: webhook_receiver_sa

3. Grant Vertex AI roles to all agent service accounts:
   - roles/aiplatform.user on project for: l1l2_agent_sa, l3_agent_sa, orchestrator_sa, embedding_worker_sa

4. Grant Cloud SQL client role to DB-accessing services:
   - roles/cloudsql.client for: api_gateway_sa, orchestrator_sa, l1l2_agent_sa, l3_agent_sa, session_agent_sa, embedding_worker_sa

5. Grant Secret Manager accessor — least privilege per service:
   - Grant role: roles/secretmanager.secretAccessor for each binding
   - api_gateway_sa        → database_password, jwt_secret_key
   - orchestrator_sa       → database_password
   - l1l2_agent_sa         → database_password, jira_api_token
   - l3_agent_sa           → database_password, jira_api_token
   - session_agent_sa      → database_password
   - embedding_worker_sa   → database_password, jira_api_token
   - webhook_receiver_sa   → jira_webhook_secret

6. Grant Pub/Sub roles:
   - webhook_receiver_sa → roles/pubsub.publisher on jira-events topic
   - embedding_worker_sa → roles/pubsub.subscriber on embedding-worker-sub

7. Create scripts/setup_secrets.sh:
   - Shell script to populate Secret Manager with values from .env.local
   - Usage: bash scripts/setup_secrets.sh
   - Reads DATABASE_PASSWORD, JIRA_API_TOKEN, JIRA_WEBHOOK_SECRET, JWT_SECRET_KEY from .env.local
   - Creates or updates each secret version in Secret Manager
   - Prints confirmation for each secret created
   - Warns if any secret value appears to be a placeholder (contains "replace" or "your-")
```

---

## PROMPT 4.2 — Cloud Build CI/CD Pipeline

```
Create the complete CI/CD pipeline using Google Cloud Build.

─────────────────────────────────────────────────────────────
FILE 1: cloudbuild.yaml — Production pipeline (push to main)
─────────────────────────────────────────────────────────────

Steps in order:

Step 1 — Run unit tests
  name: python:3.11
  entrypoint: bash
  args: [-c, "pip install -r requirements-dev.txt && pytest tests/unit -v --tb=short"]

Step 2 — Run integration tests
  name: python:3.11 (with Cloud SQL Proxy sidecar)
  args: pytest tests/integration -v --tb=short
  env: DATABASE_URL from Secret Manager test instance

Step 3 — Build all Docker images in parallel
  Build 7 images simultaneously using Cloud Build parallel steps:
  - api-gateway
  - orchestrator
  - l1l2-agent
  - l3-agent
  - session-agent
  - pipeline/embedding_worker
  - pipeline/webhook_receiver
  Tag each: us-central1-docker.pkg.dev/$_PROJECT_ID/cybmas/{service}:$COMMIT_SHA
  Also tag with :latest

Step 4 — Push all images to Artifact Registry
  Push all 7 images (both :$COMMIT_SHA and :latest tags)

Step 5 — Run DB migrations
  name: python:3.11
  Connect to Cloud SQL via Cloud SQL Proxy
  Run: python scripts/run_migrations.py
  This ensures schema is up to date before deploying new code

Step 6 — Deploy all Cloud Run services with --no-traffic flag
  Deploy each service with new image but send 0% traffic yet:
  gcloud run deploy {service}     --image=us-central1-docker.pkg.dev/$_PROJECT_ID/cybmas/{service}:$COMMIT_SHA     --region=$_REGION     --no-traffic     --set-secrets=...     --service-account=...
  Deploy all 7 services (including frontend and webhook-receiver)

Step 7 — Run smoke tests against new revision (0% traffic)
  Get the new revision URL for each service
  Hit /health on each revision URL directly
  Assert HTTP 200 within 30 seconds
  If any smoke test fails: mark build FAILED, do not proceed to traffic migration

Step 8 — Migrate traffic to new revision (100%)
  Only runs if Step 7 passed:
  gcloud run services update-traffic {service} --to-latest --region=$_REGION
  Do this for all 7 services

Step 9 — Tag previous revision for rollback
  Store previous revision name in GCS: gs://$_PROJECT_ID-deployments/last-good-revision-{service}.txt
  Enables one-command rollback

Step 10 — Notify on failure / success
  Notify on failure: send alert to Cloud Monitoring alerting policy, post to ops notification channel
  On success: log deployment summary with image SHAs and revision names to Cloud Logging

Substitution variables:
  _PROJECT_ID, _REGION=us-central1, _ENV=prod

─────────────────────────────────────────────────────────────
FILE 2: cloudbuild.dev.yaml — Dev pipeline (push to develop)
─────────────────────────────────────────────────────────────

Same as production pipeline except:
- Deploys to dev Cloud Run services (separate from prod)
- Skips integration tests (too slow for every PR)
- Uses _ENV=dev substitution
- No --no-traffic flag needed (dev gets traffic immediately)
- No rollback tagging needed
- Smoke tests still required before traffic migration

─────────────────────────────────────────────────────────────
FILE 3: cloudbuild.infra.yaml — Terraform pipeline (manual)
─────────────────────────────────────────────────────────────

Steps:
  Step 1 — terraform init
    name: hashicorp/terraform:1.7
    args: [init, -backend-config=bucket=$_STATE_BUCKET]

  Step 2 — terraform plan
    name: hashicorp/terraform:1.7
    args: [plan, -out=tfplan, -var=project_id=$_PROJECT_ID, -var=env=$_ENV]
    Save plan output to Cloud Storage for review

  Step 3 — terraform apply (manual approval gate)
    name: hashicorp/terraform:1.7
    args: [apply, tfplan]
    waitFor: manual approval step (use Cloud Build approval feature)

Triggered manually only — never auto-triggered on push.
Used for: initial infrastructure setup, adding new resources, scaling changes.

─────────────────────────────────────────────────────────────
FILE 4: cloudbuild.pipeline.yaml — Embedding sync (scheduled)
─────────────────────────────────────────────────────────────

Steps:
  Step 1 — Trigger Cloud Run Job for full JIRA sync
    gcloud run jobs execute embedding-worker       --region=$_REGION       --update-env-vars SYNC_MODE=full       --wait
  Triggered by Cloud Scheduler daily at 02:00 UTC
  Also triggerable manually for re-indexing

─────────────────────────────────────────────────────────────
FILE 5: cloudbuild.rollback.yaml — Emergency rollback
─────────────────────────────────────────────────────────────

Steps:
  Step 1 — Read last-good revision from GCS
    gsutil cat gs://$_PROJECT_ID-deployments/last-good-revision-{service}.txt

  Step 2 — Migrate traffic back to previous revision
    gcloud run services update-traffic {service}       --to-revisions={previous_revision}=100       --region=$_REGION
  Do this for all 7 services

  Step 3 — Alert ops team that rollback was executed

Triggered manually: gcloud builds submit --config=cloudbuild.rollback.yaml
─────────────────────────────────────────────────────────────

Docker image naming convention:
  us-central1-docker.pkg.dev/{project_id}/cybmas/{service}:{commit_sha}
  us-central1-docker.pkg.dev/{project_id}/cybmas/{service}:latest

Substitution variables across all pipelines:
  _PROJECT_ID  — GCP project ID
  _REGION      — us-central1
  _ENV         — dev | prod
  _STATE_BUCKET — GCS bucket for Terraform state
```

---

## PROMPT 4.2b — Initial GCP Setup Script

```
Create scripts/gcp_setup.sh — a one-time setup script run before first Terraform apply.
This script bootstraps the GCP project with everything Terraform needs to run.

Steps the script performs:

1. Validate prerequisites
   - gcloud CLI installed and authenticated
   - Required env vars set: GCP_PROJECT_ID, GCP_REGION, GITHUB_REPO

2. Enable all required GCP APIs
   gcloud services enable:
   - run.googleapis.com           (Cloud Run)
   - sqladmin.googleapis.com      (Cloud SQL)
   - redis.googleapis.com         (Memorystore)
   - pubsub.googleapis.com        (Pub/Sub)
   - secretmanager.googleapis.com (Secret Manager)
   - artifactregistry.googleapis.com (Artifact Registry)
   - cloudbuild.googleapis.com    (Cloud Build)
   - cloudscheduler.googleapis.com (Cloud Scheduler)
   - cloudtrace.googleapis.com    (Cloud Trace)
   - monitoring.googleapis.com    (Cloud Monitoring)
   - aiplatform.googleapis.com    (Vertex AI)
   - vpcaccess.googleapis.com     (VPC Serverless Access)
   - servicenetworking.googleapis.com (Private IP networking)

3. Create GCS bucket for Terraform state
   gsutil mb -p $GCP_PROJECT_ID -l $GCP_REGION gs://$GCP_PROJECT_ID-terraform-state
   gsutil versioning set on gs://$GCP_PROJECT_ID-terraform-state

4. Create GCS bucket for deployment tracking (rollbacks)
   gsutil mb -p $GCP_PROJECT_ID -l $GCP_REGION gs://$GCP_PROJECT_ID-deployments

5. Create Artifact Registry repository
   gcloud artifacts repositories create cybmas      --repository-format=docker      --location=$GCP_REGION      --project=$GCP_PROJECT_ID

6. Connect GitHub repository to Cloud Build
   gcloud builds connections create github cybmas-github      --region=$GCP_REGION
   (prints URL for engineer to authorize GitHub OAuth)

7. Print summary and next steps:
   "GCP project bootstrapped. Next steps:
    1. Run: cd infra/environments/dev && terraform init && terraform plan
    2. Review plan output
    3. Run: terraform apply
    4. Populate Secret Manager: bash scripts/setup_secrets.sh
    5. Push to develop branch to trigger first dev deployment"

Usage: bash scripts/gcp_setup.sh
Requirements: gcloud CLI authenticated with Owner role on the project
```

---

## PROMPT 4.3 — Unit Tests: Tools, Skills & Auth

```
Create unit tests for all ADK tools, skills, and JWT auth.

1. tests/unit/test_vector_search.py
   - Mock asyncpg pool + cursor
   - Test: correct SQL generated for single BU filter
   - Test: correct SQL generated for multi-BU filter
   - Test: embedding is called before SQL query
   - Test: empty results returns empty list in ToolResult
   - Test: DB error returns ToolResult(success=False, error=...)

2. tests/unit/test_jira_fetch.py
   - Mock httpx.AsyncClient responses
   - Test: fetch_jira_ticket returns formatted ticket
   - Test: ADF plain text extraction handles nested lists
   - Test: retry logic triggers on 429 response
   - Test: cache hit returns without calling JIRA API
   - Test: unknown ticket ID returns ToolResult(success=False)

3. tests/unit/test_cross_ref.py
   - Test: incident with related_tickets merges correctly
   - Test: semantic fallback search is called when related_tickets empty
   - Test: deduplication works when same ticket appears in multiple sources

4. tests/unit/test_summarize_skill.py
   - Mock google.generativeai generate_content_async call
   - Test: prompt includes original question
   - Test: all search results appear in prompt context
   - Test: follow_up_context adds last 3 turns
   - Test: LLM error returns graceful ToolResult

5. tests/unit/test_intent_classifier.py
   - Test: JIRA ID pattern (B1-1234) → JIRA_LOOKUP intent
   - Test: "status of" → STATUS_CHECK intent
   - Test: incident keywords + include_incidents=True → INCIDENT_SEARCH
   - Test: incident keywords + include_incidents=False → TICKET_SEARCH

6. tests/unit/test_session_tools.py
   - Mock asyncpg
   - Test: save_session upserts correctly
   - Test: load_session returns messages in order
   - Test: list_engineer_sessions returns max 20 ordered by updated_at DESC

7. tests/unit/test_auth.py
   - Test: login with correct password returns signed JWT token
   - Test: login with wrong password returns None / raises error
   - Test: decoded JWT token contains correct sub (email) and role claims
   - Test: expired JWT token raises JWTError on validation
   - Test: tampered JWT signature raises JWTError on validation
   - Test: bcrypt hashed password does not equal the plain text input
   - Test: verify_password(plain, hashed) returns True for correct password
   - Test: verify_password(plain, hashed) returns False for wrong password
   - Mock asyncpg for user repository tests

Use pytest-asyncio for async tests.
Use pytest fixtures in conftest.py for mock pool, mock Redis, mock httpx.
```

---

## PROMPT 4.4 — Integration Tests

```
Create integration tests that run against a real (test) database.

Setup: tests/integration/conftest.py
- Spin up test PostgreSQL + pgvector using testcontainers-python
- Run all migrations against test DB
- Seed test fixtures:
  - 2 business units (B1, B2)
  - 10 sample tickets (5 per BU)
  - 3 sample incidents
  - 2 test users:
    - engineer@test.com / Test1234! (role=engineer) — bcrypt hashed
    - admin@test.com / Admin1234! (role=admin) — bcrypt hashed
- Provide db_pool fixture (asyncpg) and redis_client fixture (fakeredis)
- Provide auth_headers(role="engineer"|"admin") fixture that returns
  {"Authorization": "Bearer <valid_jwt>"} for use in test requests

1. tests/integration/test_auth_integration.py
   - Test: POST /api/auth/login with valid credentials returns access_token + role
   - Test: POST /api/auth/login with wrong password returns 401
   - Test: POST /api/auth/login with unknown email returns 401
     (same error message as wrong password — no user enumeration)
   - Test: POST /api/auth/register creates new user and returns 200
   - Test: POST /api/auth/register with duplicate email returns 409
   - Test: GET /api/auth/me with valid token returns engineer_id and role
   - Test: GET /api/auth/me with no Authorization header returns 401
   - Test: GET /api/auth/me with expired token returns 401
   - Test: GET /api/feedback/summary with engineer role returns 403
   - Test: GET /api/feedback/summary with admin role returns 200

2. tests/integration/test_vector_search_integration.py
   - Insert test tickets with deterministic random 768-dim embeddings (numpy random seed=42)
   - Test: search_tickets returns top-k results ordered by score DESC
   - Test: BU filter correctly excludes results from other BUs
   - Test: empty DB returns empty result list

3. tests/integration/test_session_integration.py
   - Test: create session → load session → messages match exactly
   - Test: update session appends message → updated_at changes
   - Test: list_engineer_sessions returns correct count in DESC order
   - Test: engineer cannot load session belonging to another engineer (403)

4. tests/integration/test_feedback_integration.py
   - Test: save_feedback inserts row with correct session_id and rating
   - Test: get_feedback_summary returns correct total and per-rating counts
   - Test: feedback summary returns 403 when called with engineer role token

5. tests/integration/test_cross_ref_integration.py
   - Insert incidents with related_tickets pointing to seeded ticket IDs
   - Test: cross_reference returns correct linked ticket summaries
   - Test: incidents with empty related_tickets fall back to semantic search

All integration tests must clean up after each test using DB transactions that roll back.
```

---

## PROMPT 4.5 — Observability: Structured Logging & Tracing

```
Add structured logging and distributed tracing across all services.

1. services/shared/logging.py
   - Configure structlog with JSON renderer for production
   - Pretty console renderer for local dev (LOG_FORMAT=dev env var)
   - Bound context processor: auto-adds service_name, env, version
   - get_logger(name) factory function

2. services/shared/tracing.py
   - Initialise Cloud Trace with google-cloud-trace
   - trace_id extracted from X-Cloud-Trace-Context header
   - Propagate trace_id in all outbound HTTP requests
   - Context var: current_trace_id (available to log processors)

3. Add logging to all tools:
   For each tool call, log at INFO level:
   {
     "event": "tool_called",
     "tool": "search_tickets",
     "input_summary": {"query_length": 45, "business_units": ["B1"]},
     "result_count": 8,
     "latency_ms": 142,
     "trace_id": "...",
     "session_id": "..."
   }

4. Add FastAPI middleware to all services (services/shared/middleware/logging_middleware.py):
   - Log every request: method, path, status_code, latency_ms, engineer_id, trace_id
   - Log every unhandled exception with full traceback at ERROR level
   - NEVER log passwords, JWT tokens, or Authorization headers — redact them

5. infra/modules/monitoring/main.tf
   - Alert policy: p95 latency > 5000ms on any Cloud Run service
   - Alert policy: 5xx error rate > 1% in 5 min window
   - Alert policy: Pub/Sub subscription oldest_unacked_message_age > 600s
   - Dashboard with panels: request latency, error rate, active sessions
   - Notification channel: email to ops team
```

---

## PROMPT 4.6 — Local Development Setup

```
Create the local development environment setup scripts and Makefile.

1. scripts/dev_setup.sh
   - Check prereqs: python 3.11+, node 18+, psql CLI available, redis-cli available
   - Check GOOGLE_APPLICATION_CREDENTIALS env var is set and file exists
   - Copy .env.example to .env.local if not already present
   - Test DB connection using DATABASE_URL from .env.local
   - Run python test_credentials.py to verify Google auth works
   - Run migrations: python scripts/run_migrations.py
   - Run seeds: python scripts/seed_test_data.py
   - Install script dependencies: pip install -r scripts/requirements-scripts.txt
   - Print summary: "Dev environment ready"
   - Print test credentials: engineer@test.com / Test1234! and admin@test.com / Admin1234!

2. scripts/run_migrations.py
   - Read all .sql files from database/migrations/ in filename order
   - Track applied migrations in schema_migrations table (create if not exists)
   - Skip already-applied migrations (idempotent)
   - Log each migration applied
   - Reads DATABASE_URL from .env.local (use python-dotenv)

3. scripts/seed_test_data.py
   - Thin orchestrator script only — calls seed_users.py and seed_demo_data.py in order
   - Prints summary of everything inserted
   - Idempotent — safe to run multiple times

4. scripts/create_user.py
   - CLI utility for onboarding new engineer accounts
   - Usage: python scripts/create_user.py --email user@company.com --role engineer
   - Prompts for password securely using getpass (never echo to terminal)
   - Validates: email format, password min 8 chars, role must be engineer or admin
   - Hashes password with bcrypt and inserts into users table
   - Prints confirmation: "User user@company.com created with role engineer"

5. Makefile targets:
   make setup       — run scripts/dev_setup.sh
   make up          — start all 5 backend services with uvicorn (each on its own port)
   make down        — kill all uvicorn processes
   make test        — pytest tests/unit -v
   make test-int    — pytest tests/integration -v
   make migrate     — python scripts/run_migrations.py
   make seed        — python scripts/seed_test_data.py  (runs seed_users + seed_demo_data)
   make create-user — python scripts/create_user.py
   make seed-users   — python scripts/seed_users.py (just users, no demo data)
   make logs        — tail logs from all running services
   make frontend    — cd frontend && npm run dev
```
