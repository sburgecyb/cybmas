# Secrets Management Guide

This document defines how every secret and credential is handled in local development and GCP production.

---

## Secret Inventory

| Secret | Local Dev | GCP Production | Who Needs It |
|---|---|---|---|
| `DATABASE_URL` / DB password | `.env.local` | Secret Manager: `database_password` | api-gateway, all agents, session-agent |
| `JIRA_API_TOKEN` | `.env.local` | Secret Manager: `jira_api_token` | pipeline/webhook_receiver, embedding_worker, l1l2-agent, l3-agent |
| `JIRA_WEBHOOK_SECRET` | `.env.local` | Secret Manager: `jira_webhook_secret` | pipeline/webhook_receiver only |
| `JWT_SECRET_KEY` | `.env.local` | Secret Manager: `jwt_secret_key` | api-gateway only |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to `keys/cybmasacn.json` | Not needed — Cloud Run attached SA | All services |
| `GCP_PROJECT_ID` | `.env.local` | Cloud Run env var (not secret) | All services |

---

## Local Development

### Rule 1 — Never commit secrets
`.env.local` and the `keys/` folder are **always** in `.gitignore`:

```
# .gitignore (must include these)
.env.local
.env.*.local
keys/
*.json           # catches service account key files
__pycache__/
*.pyc
venv/
.venv/
node_modules/
```

### Rule 2 — Use .env.local, never .env
`.env.example` is committed to git — it contains placeholder values only, never real secrets.
`.env.local` is never committed — it contains real values for local dev.

### Rule 3 — Load secrets via python-dotenv
Every Python service loads `.env.local` at startup:

```python
from dotenv import load_dotenv
load_dotenv(".env.local")  # safe — ignored if file doesn't exist in production
```

### Rule 4 — Service account key stays in keys/ folder
The `keys/cybmasacn.json` file must:
- Never be committed to git (covered by `keys/` in `.gitignore`)
- Never be copied into a Docker image
- Be referenced only via `GOOGLE_APPLICATION_CREDENTIALS` env var

---

## GCP Production — Secret Manager

### All secrets are stored in Secret Manager, not in Cloud Run env vars

```
Secret Name               → Accessed By
─────────────────────────────────────────────────────────
database_password         → api-gateway, orchestrator, l1l2-agent, l3-agent, session-agent
jira_api_token            → embedding_worker, webhook_receiver, l1l2-agent, l3-agent
jira_webhook_secret       → webhook_receiver
jwt_secret_key            → api-gateway
```

### How secrets are mounted to Cloud Run

In Terraform, each Cloud Run service references secrets like this:

```hcl
resource "google_cloud_run_v2_service" "api_gateway" {
  template {
    containers {
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "JWT_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret_key.secret_id
            version = "latest"
          }
        }
      }
    }
    service_account = google_service_account.api_gateway_sa.email
  }
}
```

Secrets are injected as environment variables at runtime — no code change needed between local and production.

### IAM — Least Privilege Per Service

Each Cloud Run service has its own service account with access **only** to the secrets it needs:

```
api-gateway SA      → database_password, jwt_secret_key
orchestrator SA     → database_password
l1l2-agent SA       → database_password, jira_api_token
l3-agent SA         → database_password, jira_api_token
session-agent SA    → database_password
embedding-worker SA → database_password, jira_api_token
webhook-receiver SA → jira_webhook_secret
```

Terraform IAM binding example:
```hcl
resource "google_secret_manager_secret_iam_member" "api_gateway_jwt" {
  secret_id = google_secret_manager_secret.jwt_secret_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api_gateway_sa.email}"
}
```

### Creating Secrets in Secret Manager

```bash
# Run once during initial GCP setup

# DB password
echo -n "your-db-password" | gcloud secrets create database_password \
  --data-file=- --project=$GCP_PROJECT_ID

# JIRA API token
echo -n "your-jira-token" | gcloud secrets create jira_api_token \
  --data-file=- --project=$GCP_PROJECT_ID

# JIRA webhook secret
echo -n "your-webhook-secret" | gcloud secrets create jira_webhook_secret \
  --data-file=- --project=$GCP_PROJECT_ID

# JWT secret key (generate a strong random one)
python3 -c "import secrets; print(secrets.token_hex(32))" | \
  gcloud secrets create jwt_secret_key --data-file=- --project=$GCP_PROJECT_ID
```

### Rotating Secrets

```bash
# Add a new version (old version remains until you disable it)
echo -n "new-value" | gcloud secrets versions add jwt_secret_key \
  --data-file=- --project=$GCP_PROJECT_ID

# Cloud Run automatically picks up "latest" version on next deployment
# To force immediate rollout: gcloud run services update api-gateway --region=us-central1
```

---

## Google Service Account — Production

In production, Cloud Run services do **not** use a key file. Instead:

1. Each Cloud Run service has an **attached service account** (configured in Terraform)
2. The service account has the required IAM roles:
   - `roles/secretmanager.secretAccessor` — read secrets
   - `roles/cloudsql.client` — connect to Cloud SQL
   - `roles/aiplatform.user` — call Vertex AI (Gemini + embeddings)
   - `roles/pubsub.publisher` — publish to Pub/Sub (webhook receiver)
   - `roles/pubsub.subscriber` — subscribe from Pub/Sub (embedding worker)

3. `GOOGLE_APPLICATION_CREDENTIALS` is **not set** in Cloud Run — the metadata server provides credentials automatically

This means the application code is identical locally and in production — only the authentication method differs.

---

## Security Checklist Before Deploying

- [ ] `.env.local` is in `.gitignore` and never committed
- [ ] `keys/` folder is in `.gitignore` and never committed
- [ ] All secrets created in Secret Manager (not hardcoded in Terraform)
- [ ] Each Cloud Run service has its own SA with least-privilege access
- [ ] `GOOGLE_APPLICATION_CREDENTIALS` not set in Cloud Run env vars
- [ ] JIRA webhook secret configured in JIRA webhook settings
- [ ] JWT secret key is at least 32 random bytes
- [ ] DB password is strong (20+ chars, mixed)
- [ ] Secret versions are tracked — old versions disabled after rotation

---

## Adding a New Secret (Checklist)

1. Add placeholder to `.env.example` with a comment
2. Add real value to `.env.local` (never commit)
3. Create in Secret Manager: `gcloud secrets create <name>`
4. Add Terraform resource in `infra/modules/secret_manager/main.tf`
5. Add IAM binding for the service(s) that need it
6. Mount to Cloud Run service in `infra/modules/cloud_run/main.tf`
7. Read in application code via `os.getenv("SECRET_NAME")`
