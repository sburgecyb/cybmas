# Deployment Guide

This guide covers the complete deployment lifecycle — from first-time GCP setup to day-to-day CI/CD.

---

## Deployment Architecture

```
Developer pushes code
        │
        ├── push to develop ──► Cloud Build (dev pipeline)
        │                              │
        │                         1. Unit tests
        │                         2. Build 7 Docker images
        │                         3. Push to Artifact Registry
        │                         4. Run DB migrations (dev DB)
        │                         5. Deploy to dev Cloud Run (no-traffic)
        │                         6. Smoke tests (/health on each)
        │                         7. Migrate traffic to new revision
        │
        └── push to main ────► Cloud Build (prod pipeline)
                                       │
                                  1. Unit tests
                                  2. Integration tests
                                  3. Build 7 Docker images
                                  4. Push to Artifact Registry
                                  5. Run DB migrations (prod DB)
                                  6. Deploy to prod Cloud Run (--no-traffic)
                                  7. Smoke tests on new revision
                                  8. Migrate traffic (100%)
                                  9. Tag revision for rollback
```

---

## First-Time GCP Setup (Run Once)

```bash
# Step 1 — Authenticate gcloud
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Step 2 — Bootstrap GCP project
bash scripts/gcp_setup.sh

# Step 3 — Deploy infrastructure
cd infra/environments/dev
terraform init -backend-config="bucket=YOUR_PROJECT_ID-terraform-state"
terraform plan
terraform apply

# Step 4 — Populate secrets in Secret Manager
bash scripts/setup_secrets.sh

# Step 5 — Verify infrastructure
gcloud run services list --region=us-central1
gcloud sql instances list
gcloud redis instances list --region=us-central1
```

---

## Services Deployed

| Service | Cloud Run Name | Port | Min Instances |
|---|---|---|---|
| Frontend (Next.js) | `cybmas-frontend` | 3000 | 1 |
| API Gateway (FastAPI) | `cybmas-api` | 8000 | 1 |
| Orchestrator Agent | `cybmas-orchestrator` | 8001 | 0 |
| L1/L2 Resolution Agent | `cybmas-l1l2` | 8002 | 0 |
| L3 Resolutions Agent | `cybmas-l3` | 8003 | 0 |
| Session & Feedback Agent | `cybmas-session` | 8004 | 0 |
| JIRA Webhook Receiver | `cybmas-webhook` | 8005 | 1 |

One Cloud Run Job:
| Job | Name | Trigger |
|---|---|---|
| Embedding Worker | `cybmas-embedding-worker` | Pub/Sub push + Cloud Scheduler |

---

## CI/CD Pipelines

| Pipeline File | Trigger | Environment | Purpose |
|---|---|---|---|
| `cloudbuild.yaml` | Push to `main` | Production | Full test + deploy |
| `cloudbuild.dev.yaml` | Push to `develop` | Dev | Fast deploy |
| `cloudbuild.infra.yaml` | Manual only | Any | Terraform apply |
| `cloudbuild.pipeline.yaml` | Cloud Scheduler / manual | Production | JIRA full sync |
| `cloudbuild.rollback.yaml` | Manual only | Production | Emergency rollback |

---

## Deployment Flow Detail

### Zero-Downtime Deployment

The production pipeline uses `--no-traffic` flag to ensure zero downtime:

```
1. Deploy new image (--no-traffic=true)
   → New revision created, receives 0% traffic
   → Old revision still serving 100% traffic

2. Smoke test new revision directly
   → Each service /health endpoint checked
   → If any fail: build fails, old revision keeps 100% traffic

3. Migrate traffic (--to-latest)
   → New revision gets 100% traffic
   → Old revision gets 0% (stays available for rollback)
```

### Rollback

If production breaks after deploy:

```bash
# Option 1 — Automated rollback via Cloud Build
gcloud builds submit --config=cloudbuild.rollback.yaml \
  --substitutions=_PROJECT_ID=YOUR_PROJECT_ID,_REGION=us-central1

# Option 2 — Manual single service rollback
gcloud run services update-traffic cybmas-api \
  --to-revisions=PREVIOUS_REVISION_NAME=100 \
  --region=us-central1
```

Previous revision names are stored in:
`gs://YOUR_PROJECT_ID-deployments/last-good-revision-{service}.txt`

---

## DB Migrations in CI/CD

Migrations run automatically in the pipeline **before** deploying new service code:

```
Step 5 in cloudbuild.yaml:
- Connects to Cloud SQL via Cloud SQL Auth Proxy
- Runs: python scripts/run_migrations.py
- Idempotent — skips already-applied migrations
- If migration fails: pipeline stops, no new code deployed
```

**Important**: Never deploy new service code before running migrations. The pipeline enforces this order.

---

## Environment Variables in Cloud Run

All environment variables are injected at deploy time — no values stored in the Docker image:

- **Non-sensitive** (e.g. `GCP_PROJECT_ID`, `VERTEX_AI_LOCATION`, `GEMINI_MODEL`): set as plain env vars in Terraform
- **Sensitive** (DB URL, JWT key, JIRA token): mounted from Secret Manager via `secret_key_ref`

---

## Monitoring Deployments

After each deployment check:

```bash
# Service status
gcloud run services describe cybmas-api \
  --region=us-central1 --format="value(status.conditions)"

# Recent logs
gcloud logs read "resource.type=cloud_run_revision AND \
  resource.labels.service_name=cybmas-api" \
  --limit=50 --freshness=10m

# Cloud Build history
gcloud builds list --limit=5
```

Cloud Monitoring dashboard (created by Terraform) shows:
- Request latency p50/p95/p99 per service
- Error rate per service
- Active sessions count
- Embedding worker lag (Pub/Sub oldest unacked message age)

---

## Branching Strategy

```
main          ← Production deploys. Protected. PR required. 1 approval required.
develop       ← Dev deploys. Protected. PR required.
feature/*     ← Feature branches. PRs to develop only.
hotfix/*      ← Emergency fixes. PRs to both main and develop.
```

---

## First Deployment Checklist

- [ ] `bash scripts/gcp_setup.sh` completed successfully
- [ ] `terraform apply` completed for dev environment
- [ ] `bash scripts/setup_secrets.sh` populated all secrets
- [ ] GitHub repository connected to Cloud Build
- [ ] Cloud Build triggers created (visible in GCP console)
- [ ] Push to `develop` branch — watch first Cloud Build run
- [ ] Verify all 7 services show `READY` in Cloud Run console
- [ ] Hit the API Gateway /health endpoint
- [ ] Test login with admin credentials
- [ ] Run a test JIRA embedding sync: `gcloud builds submit --config=cloudbuild.pipeline.yaml`
