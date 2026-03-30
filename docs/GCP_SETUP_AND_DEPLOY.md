# GCP setup, build, and deploy (cybmas)

This document describes **Google Cloud configuration and deployment steps** needed before (and alongside) automated CI/CD: APIs, Artifact Registry, Cloud Build images, networking for Redis, Cloud Run services, secrets, database migrations, and frontend/CORS.

**Use it when:** standing up a **new GCP project** or walking through a full manual deploy.

**Related documents**

| Document | Purpose |
|----------|---------|
| [`deploy/README.md`](../deploy/README.md) | Original phased guide with extra detail, JIRA secrets, and CI/CD notes |
| [`docs/CICD_PIPELINE_SETUP.md`](CICD_PIPELINE_SETUP.md) | GitHub Actions + Workload Identity + pipeline-only troubleshooting |
| [`docs/SECRETS.md`](SECRETS.md) | Secret Manager names, Cloud SQL socket URLs, service account wiring |
| [`cloudbuild.yaml`](../cloudbuild.yaml) | Builds `api-gateway`, `orchestrator`, `frontend` images |

**Scope of this guide:** the **three** services built by root `cloudbuild.yaml` — **`cybmas-orchestrator`**, **`cybmas-api`**, **`cybmas-frontend`**. Other agents (`cybmas-l1l2`, etc.) follow the same Cloud Run patterns if you add them later.

---

## 0. Order of work (summary)

Complete steps **in order** unless noted.

| Step | Section | Outcome |
|------|---------|---------|
| 1 | [§1](#1-prerequisites) | Project, billing, Cloud SQL decision |
| 2 | [§2](#2-cli-and-project) | `gcloud` authenticated, project set |
| 3 | [§3](#3-enable-apis) | Required APIs enabled |
| 4 | [§4](#4-artifact-registry--cloud-build-push) | Docker repo `cybmas`; Cloud Build can push |
| 5 | [§5](#5-secret-manager-and-service-accounts) | Secrets exist; runtime SAs created with roles |
| 6 | [§6](#6-cloud-sql-postgres) | Instance + `database_url` secret (socket form for Cloud Run) |
| 7 | [§7](#7-build-container-images-cloud-build) | Three images in Artifact Registry |
| 8 | [§8](#8-memorystore-redis--vpc-connector) | Redis + connector (if app uses Redis) |
| 9 | [§9](#9-deploy-cloud-run-orchestrator) | `cybmas-orchestrator` URL |
| 10 | [§10](#10-deploy-cloud-run-api-gateway) | `cybmas-api` URL |
| 11 | [§11](#11-database-migrations-and-seeds) | Schema and users in Cloud SQL |
| 12 | [§12](#12-rebuild-frontend-image-optional) | Frontend image with real API URL |
| 13 | [§13](#13-deploy-cloud-run-frontend--cors) | `cybmas-frontend` + CORS on gateway |
| 14 | [§14](#14-automated-deploys-ci-cd) | GitHub Actions (optional) |

---

## 1. Prerequisites

- **GCP project** with **billing** enabled.
- **Project ID** recorded (e.g. `myorg-cybmas-dev`); used in every `--project=` and image path.
- **Region** — examples use **`us-central1`**; keep Cloud Run, Artifact Registry, Redis, and connector in the **same** region.
- **Cloud SQL for PostgreSQL** — create an instance in Console or `gcloud sql instances create ...` (see [Cloud SQL docs](https://cloud.google.com/sql/docs/postgres/create-instance)). You need connection name `PROJECT:REGION:INSTANCE`, DB name, user, password.
- **Quota** for Cloud Run, Cloud Build, Vertex AI (if using Gemini/Vertex), and optionally Memorystore.

---

## 2. CLI and project

Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install). Then:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
```

Confirm: `gcloud config get-value project` prints the intended ID.

---

## 3. Enable APIs

From the **repository root**:

**PowerShell**

```powershell
.\scripts\gcp_enable_apis.ps1 -ProjectId YOUR_PROJECT_ID
```

**Bash / Cloud Shell**

```bash
chmod +x scripts/gcp_enable_apis.sh
./scripts/gcp_enable_apis.sh YOUR_PROJECT_ID
```

Confirm in [APIs & Services](https://console.cloud.google.com/apis/dashboard): Cloud Run, Artifact Registry, Cloud Build, Vertex AI, Secret Manager, and (for Redis) Redis, VPC Access, Compute — re-run the script if you add steps later.

---

## 4. Artifact Registry + Cloud Build push

**Create Docker repository** (name **`cybmas`** matches default `cloudbuild.yaml`):

```bash
gcloud artifacts repositories create cybmas \
  --repository-format=docker \
  --location=us-central1 \
  --project=YOUR_PROJECT_ID \
  --description="cybmas container images"
```

**Grant Cloud Build’s service account write access** to that repo:

```bash
PROJECT_ID=YOUR_PROJECT_ID
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

gcloud artifacts repositories add-iam-policy-binding cybmas \
  --location=us-central1 \
  --member="serviceAccount:${CLOUDBUILD_SA}" \
  --role="roles/artifactregistry.writer" \
  --project=$PROJECT_ID
```

---

## 5. Secret Manager and service accounts

Create secrets your services will mount (names must match what you pass to `--set-secrets`). Typical set:

| Secret | Used by | Notes |
|--------|---------|--------|
| `database_url` | gateway, orchestrator | Cloud SQL **Unix socket** URL for Cloud Run — see [`docs/SECRETS.md`](SECRETS.md) |
| `redis_url` | gateway, orchestrator | After §8 |
| `jwt_secret_key` | gateway | Strong random string |
| `jira_api_token`, `jira_user_email` | orchestrator | Optional for live JIRA |

**Create** (example pattern):

```bash
echo -n 'YOUR_VALUE' | gcloud secrets create SECRET_NAME --data-file=- --project=YOUR_PROJECT_ID
```

**Runtime service accounts** (recommended: separate SAs per service):

- **Orchestrator SA:** e.g. `roles/aiplatform.user`, `roles/cloudsql.client`, `secretmanager.secretAccessor` on the secrets it needs.
- **Gateway SA:** `roles/cloudsql.client`, `secretmanager.secretAccessor` on its secrets.

Grant **Artifact Registry read** on the `cybmas` repo to each runtime SA that pulls images (`roles/artifactregistry.reader`), or use project-level reader.

Details: [`docs/SECRETS.md`](SECRETS.md).

---

## 6. Cloud SQL (Postgres)

1. Create the instance and database user (Console or `gcloud sql`).
2. Store **`DATABASE_URL`** for **Cloud Run** in Secret Manager as `database_url` using the **`/cloudsql/PROJECT:REGION:INSTANCE`** host form so the gateway and orchestrator can connect from Cloud Run.
3. You will attach the instance to services with:

   `--add-cloudsql-instances=PROJECT_ID:REGION:INSTANCE_ID`

   on **`gcloud run deploy`** for services that use the socket URL.

For **migrations from your laptop**, use Cloud SQL Auth Proxy + TCP URL — see [§11](#11-database-migrations-and-seeds).

---

## 7. Build container images (Cloud Build)

From **repository root** (monorepo). Builds **`api-gateway`**, **`orchestrator`**, **`frontend`** per [`cloudbuild.yaml`](../cloudbuild.yaml).

**First time** (frontend may point at localhost until API URL exists):

```bash
gcloud builds submit --config=cloudbuild.yaml --project=YOUR_PROJECT_ID .
```

**After `cybmas-api` has a URL**, rebuild the frontend with:

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --project=YOUR_PROJECT_ID \
  --substitutions=_NEXT_PUBLIC_API_URL=https://YOUR-CYBMAS-API-URL.run.app,_TAG=latest .
```

**PowerShell** (quote the whole `--substitutions` value):

```powershell
gcloud builds submit --config=cloudbuild.yaml --project=YOUR_PROJECT_ID --substitutions="_NEXT_PUBLIC_API_URL=https://YOUR-API.run.app,_TAG=latest" .
```

Confirm in Artifact Registry: images **`api-gateway`**, **`orchestrator`**, **`frontend`** with your tag.

---

## 8. Memorystore (Redis) + VPC connector

Required if the app uses Redis (sessions/cache). Cloud Run reaches Memorystore only via **private IP** + **Serverless VPC Access**.

1. Pick a non-overlapping **`/28`** range (e.g. `10.8.0.0/28`) on your VPC (`default` or custom).
2. **Connector:**

```powershell
$PROJECT_ID = "YOUR_PROJECT_ID"
$REGION = "us-central1"
gcloud compute networks vpc-access connectors create cybmas-redis-conn `
  --project=$PROJECT_ID --region=$REGION --network=default --range=10.8.0.0/28
```

3. **Redis:**

```powershell
gcloud redis instances create cybmas-redis `
  --project=$PROJECT_ID --region=$REGION --tier=basic --size=1 `
  --redis-version=redis_7_0 `
  --network=projects/$PROJECT_ID/global/networks/default
```

4. **Secret `redis_url`:** `redis://HOST:6379` using Memorystore host from `gcloud redis instances describe`.

On **orchestrator** and **gateway** deploys, add:

```text
--vpc-connector=cybmas-redis-conn
--vpc-egress=private-ranges-only
```

Use **`private-ranges-only`** so Google APIs (Vertex, secrets) are not forced through the VPC.

---

## 9. Deploy Cloud Run: orchestrator

Replace placeholders: `REGION`, `PROJECT_ID`, `TAG`, orchestrator SA email, Cloud SQL attachment if used.

```bash
REGION=us-central1
PROJECT_ID=YOUR_PROJECT_ID
TAG=latest

gcloud run deploy cybmas-orchestrator \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/orchestrator:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --project=${PROJECT_ID} \
  --service-account=ORCHESTRATOR_SA@${PROJECT_ID}.iam.gserviceaccount.com \
  --vpc-connector=cybmas-redis-conn \
  --vpc-egress=private-ranges-only \
  --set-env-vars=GCP_PROJECT_ID=${PROJECT_ID},VERTEX_AI_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true,JIRA_BASE_URL=https://yourorg.atlassian.net \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JIRA_API_TOKEN=jira_api_token:latest,JIRA_USER_EMAIL=jira_user_email:latest \
  --add-cloudsql-instances=${PROJECT_ID}:${REGION}:YOUR_INSTANCE_NAME
```

Omit `--add-cloudsql-instances` if not using Cloud SQL socket. Adjust `--set-secrets` to secrets you actually created.

Check **`/health`**; copy the **HTTPS base URL** (no trailing slash) for the gateway.

---

## 10. Deploy Cloud Run: API gateway

```bash
ORCH_URL="https://cybmas-orchestrator-xxxxx-uc.a.run.app"
REGION=us-central1
PROJECT_ID=YOUR_PROJECT_ID
TAG=latest

gcloud run deploy cybmas-api \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/api-gateway:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --project=${PROJECT_ID} \
  --service-account=GATEWAY_SA@${PROJECT_ID}.iam.gserviceaccount.com \
  --vpc-connector=cybmas-redis-conn \
  --vpc-egress=private-ranges-only \
  --set-env-vars=ORCHESTRATOR_ENDPOINT=${ORCH_URL} \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JWT_SECRET_KEY=jwt_secret_key:latest \
  --add-cloudsql-instances=${PROJECT_ID}:${REGION}:YOUR_INSTANCE_NAME
```

Check **`/health`**. Save the gateway **HTTPS URL** for the frontend build and for **`DEV_API_GATEWAY_URL`** in GitHub Actions.

---

## 11. Database migrations and seeds

Cloud Run uses a **socket** `DATABASE_URL`. On your **machine**, use **Cloud SQL Auth Proxy** and a **TCP** URL.

1. Run [Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/connect-auth-proxy) to `localhost:5432`.
2. Set `DATABASE_URL` for asyncpg, e.g. `postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/DBNAME` in `.env.local` or export.
3. From **repo root**:

```bash
python scripts/run_migrations.py
python scripts/seed_users.py
python scripts/seed_demo_data.py   # optional; needs Vertex auth for embeddings
```

---

## 12. Rebuild frontend image (optional)

If the first build used the default `NEXT_PUBLIC_API_URL`, run [§7](#7-build-container-images-cloud-build) again with `_NEXT_PUBLIC_API_URL=https://YOUR-GATEWAY.run.app` before deploying the frontend.

---

## 13. Deploy Cloud Run: frontend + CORS

```bash
REGION=us-central1
PROJECT_ID=YOUR_PROJECT_ID
TAG=latest

gcloud run deploy cybmas-frontend \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/frontend:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --project=${PROJECT_ID}
```

**CORS:** redeploy **`cybmas-api`** with **`CORS_ORIGINS`** set to the **exact** frontend origin (copy from browser DevTools if needed), e.g.:

```bash
FRONTEND_URL="https://cybmas-frontend-xxxxx-uc.a.run.app"
ORCH_URL="https://cybmas-orchestrator-xxxxx-uc.a.run.app"

gcloud run deploy cybmas-api \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/api-gateway:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --project=${PROJECT_ID} \
  --service-account=GATEWAY_SA@${PROJECT_ID}.iam.gserviceaccount.com \
  --vpc-connector=cybmas-redis-conn \
  --vpc-egress=private-ranges-only \
  --set-env-vars=ORCHESTRATOR_ENDPOINT=${ORCH_URL},CORS_ORIGINS=${FRONTEND_URL} \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JWT_SECRET_KEY=jwt_secret_key:latest \
  --add-cloudsql-instances=${PROJECT_ID}:${REGION}:YOUR_INSTANCE_NAME
```

Merge any other env vars you already set so nothing is dropped.

---

## 14. Automated deploys (CI/CD)

After §9–§13, Cloud Run services **exist** with full configuration. The GitHub Actions workflow only **updates images**:

- Workflow: `.github/workflows/gcp-deploy.yml`
- Setup: [`docs/CICD_PIPELINE_SETUP.md`](CICD_PIPELINE_SETUP.md)

---

## 15. Quick reference

| Resource | Typical name / pattern |
|----------|-------------------------|
| Artifact Registry repo | `cybmas` (Docker, `us-central1`) |
| Images | `{region}-docker.pkg.dev/{PROJECT_ID}/cybmas/<image>:{tag}` — `<image>` = `api-gateway`, `orchestrator`, or `frontend` |
| Cloud Build staging bucket | `gs://{PROJECT_ID}_cloudbuild` |
| VPC connector | `cybmas-redis-conn` |
| Redis | `cybmas-redis` |
| Cloud Run | `cybmas-orchestrator`, `cybmas-api`, `cybmas-frontend` |

---

## 16. Optional local Docker build

If Docker is allowed locally, from repo root:

```bash
docker build -f services/api_gateway/Dockerfile -t cybmas-api:local .
docker build -f services/orchestrator/Dockerfile -t cybmas-orchestrator:local .
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t cybmas-frontend:local frontend/
```

Production UI should use the real gateway URL in `NEXT_PUBLIC_API_URL` at **build** time.

---

*For JIRA secret creation, regex CORS, and Terraform alternatives, see [`deploy/README.md`](../deploy/README.md) and [`docs/SECRETS.md`](SECRETS.md).*
