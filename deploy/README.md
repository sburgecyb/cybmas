# GCP deployment — step by step

**Consolidated GCP setup + build + deploy (single doc):** [`docs/GCP_SETUP_AND_DEPLOY.md`](../docs/GCP_SETUP_AND_DEPLOY.md).

Work through **phases in order**. You do **not** need Docker on your laptop; use **Cloud Build** (see Phase 0).

| Phase | What you do | Outcome |
|-------|----------------|---------|
| **0** | Install `gcloud`, pick project | CLI ready |
| **1** | Enable APIs | Services can run |
| **2** | Artifact Registry + IAM | Image storage + push rights |
| **3** | `gcloud builds submit` | `api-gateway` + `orchestrator` + **`frontend`** images |
| **3b** | Memorystore Redis + VPC connector | Private Redis reachable from Cloud Run |
| **4** | Cloud Run: orchestrator | ADK backend URL |
| **5** | Cloud Run: API gateway | `ORCHESTRATOR_ENDPOINT` → phase 4 URL |
| **5b** | Cloud SQL: migrations + seeds | Schema + users (+ optional demo vectors) in **prod** DB |
| **6** | Cloud Run: **frontend** | Next.js UI; rebuild image with real **`_NEXT_PUBLIC_API_URL`** after API URL exists |
| **7** | Optional: `cloudbuild.embedding-worker.yaml` + `gcloud run jobs deploy` + Scheduler | **JIRA → pgvector** via Cloud Run Job **`cybmas-embedding-worker`** (not part of default GitHub Actions build) |
| **7b** | Optional: `cloudbuild.kb-ingest-job.yaml` + `gcloud run jobs deploy` | **KB file in GCS → `knowledge_articles`** via Cloud Run Job **`cybmas-kb-ingest-job`** (same build pattern as Phase 7; see Phase 7b below) |

More detail: `docs/DEPLOYMENT.md`, `docs/SECRETS.md`.

---

## Phase 0 — Tools (no Docker)

1. Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) so `gcloud` works in PowerShell or Cloud Shell.
2. Log in and set your project:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
```

*(Use the same account that owns or can deploy to the project.)*

**Stop here and confirm:** `gcloud config get-value project` prints the correct ID.

---

## Phase 1 — Enable APIs

**PowerShell (repo root):**

```powershell
.\scripts\gcp_enable_apis.ps1 -ProjectId YOUR_PROJECT_ID
```

**Bash / Cloud Shell:**

```bash
chmod +x scripts/gcp_enable_apis.sh
./scripts/gcp_enable_apis.sh YOUR_PROJECT_ID
```

**Stop here and confirm:** [APIs & Services → Enabled APIs](https://console.cloud.google.com/apis/dashboard) lists Cloud Run, Artifact Registry, Cloud Build, Vertex AI API, etc.

---

## Phase 2 — Artifact Registry + Cloud Build push access

**Create the Docker repo** (name `cybmas` matches default `cloudbuild.yaml`; change `_REPO` if you use another name):

```bash
gcloud artifacts repositories create cybmas \
  --repository-format=docker \
  --location=us-central1 \
  --description="cybmas container images"
```

**Let Cloud Build push images** (replace `PROJECT_ID` and `PROJECT_NUMBER`; find number in Cloud Console → IAM or `gcloud projects describe PROJECT_ID --format='value(projectNumber)'`):

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

**Stop here and confirm:** Artifact Registry shows an empty `cybmas` repository in `us-central1`.

---

## Phase 3 — Build images in Cloud Build (no local Docker)

From the **repository root** (clone or copy of this repo).

Builds three images: **`api-gateway`**, **`orchestrator`**, **`frontend`**. The Next.js app bakes **`NEXT_PUBLIC_API_URL`** at build time (default `http://localhost:8000`). For a **production** frontend, set **`_NEXT_PUBLIC_API_URL`** to the **HTTPS URL of `cybmas-api`** (you get that URL after Phase 5). If you have not deployed the API yet, you can run Phase 3 once for backends only by using the default (frontend image will point at localhost until you **re-run** this phase with the real gateway URL). The **embedding worker** image is built separately — **`cloudbuild.embedding-worker.yaml`** (Phase 7).

**Easiest (defaults: `us-central1`, repo `cybmas`, tag `latest`):**

```bash
gcloud builds submit --config=cloudbuild.yaml .
```

**Production frontend + custom tag** — **PowerShell** (quote the whole substitutions string):

```powershell
gcloud builds submit --config=cloudbuild.yaml --substitutions="_NEXT_PUBLIC_API_URL=https://cybmas-api-xxxxx-uc.a.run.app,_TAG=latest" .
```

**Bash / Cloud Shell:**

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_NEXT_PUBLIC_API_URL=https://cybmas-api-xxxxx-uc.a.run.app,_TAG=latest .
```

**Stop here and confirm:** [Artifact Registry](https://console.cloud.google.com/artifacts) → `cybmas` → you see **`api-gateway`**, **`orchestrator`**, and **`frontend`** (tag `latest` or `dev-1`). After Phase 7, **`embedding-worker`** appears too if you ran that build.

---

## Phase 3b — Memorystore for Redis (Cloud Run)

Cloud Run cannot reach Memorystore over the public internet. You need a **VPC** (use `default` or your own), a **Serverless VPC Access connector**, and **`--vpc-egress`** on each service that uses Redis.

**Prereq:** Phase 1 must include `redis.googleapis.com`, `vpcaccess.googleapis.com`, and `compute.googleapis.com` (re-run `scripts/gcp_enable_apis` if you enabled APIs before those were added).

### 1. Pick a connector IP range

Choose a **`/28`** in `10.0.0.0/8`, `172.16.0.0/12`, or `192.168.0.0/16` that does **not** overlap any existing subnet in that VPC ([VPC → VPC networks](https://console.cloud.google.com/networking/networks) → subnets). Example: `10.8.0.0/28`.

### 2. Create the Serverless VPC Access connector

**PowerShell** (same region as Cloud Run / Redis):

```powershell
$PROJECT_ID = "YOUR_PROJECT_ID"
$REGION = "us-central1"

gcloud compute networks vpc-access connectors create cybmas-redis-conn `
  --project=$PROJECT_ID `
  --region=$REGION `
  --network=default `
  --range=10.8.0.0/28
```

Wait until status is **READY** (`gcloud compute networks vpc-access connectors describe cybmas-redis-conn --region=$REGION`).

### 3. Create the Redis instance

**PowerShell:**

```powershell
gcloud redis instances create cybmas-redis `
  --project=$PROJECT_ID `
  --region=$REGION `
  --tier=basic `
  --size=1 `
  --redis-version=redis_7_0 `
  --network=projects/$PROJECT_ID/global/networks/default
```

Provisioning can take several minutes. **`STANDARD_HA`** is for production; **`basic`** + **1** GiB is enough to try.

### 4. Build `REDIS_URL` and store in Secret Manager

**PowerShell:**

```powershell
$redisHost = gcloud redis instances describe cybmas-redis --region=$REGION --project=$PROJECT_ID --format="value(host)"
$redisUrl = "redis://${redisHost}:6379"
# First time:
$redisUrl | gcloud secrets create redis_url --data-file=- --project=$PROJECT_ID
# Later updates:
# $redisUrl | gcloud secrets versions add redis_url --data-file=- --project=$PROJECT_ID
```

Grant your orchestrator and API gateway service accounts **`roles/secretmanager.secretAccessor`** on `redis_url` (same as `database_url`).

### 5. Cloud Run flags (orchestrator and API gateway)

Add to **both** `gcloud run deploy` commands:

```text
--vpc-connector=cybmas-redis-conn `
--vpc-egress=private-ranges-only `
```

Use **`private-ranges-only`** so traffic to Google APIs (Vertex, Secret Manager, Artifact Registry) stays on the default path; only **RFC 1918** destinations (Memorystore) go through the VPC.

Keep **`--set-secrets=...,REDIS_URL=redis_url:latest`** so the container reads the URL from Secret Manager.

**Stop here and confirm:** From Cloud Shell on a VM in the same VPC you can `redis-cli -h HOST ping`; after deploy, gateway/orchestrator logs should not show repeated Redis connection errors on warm requests.

---

## Phase 4 — Deploy orchestrator (Cloud Run)

1. Create or pick a **service account** for the orchestrator with at least:
   - **Vertex AI User** (`roles/aiplatform.user`)
   - **Cloud SQL Client** if you use Cloud SQL (`roles/cloudsql.client`)
2. Deploy (adjust image URL, region, SA email):

```bash
REGION=us-central1
PROJECT_ID=YOUR_PROJECT_ID
TAG=dev-1

# JIRA_* on the orchestrator is required for “show me ticket PROJ-123” (live API).
# Without them, only the DB/embeddings path works — Cloud has no .env.local.
gcloud run deploy cybmas-orchestrator \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/orchestrator:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=YOUR_ORCHESTRATOR_SA@${PROJECT_ID}.iam.gserviceaccount.com \
  --vpc-connector=cybmas-redis-conn \
  --vpc-egress=private-ranges-only \
  --set-env-vars=GCP_PROJECT_ID=${PROJECT_ID},VERTEX_AI_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true,JIRA_BASE_URL=https://YOURORG.atlassian.net \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JIRA_API_TOKEN=jira_api_token:latest,JIRA_USER_EMAIL=jira_user_email:latest
```

After deploy, open **`/health`** on the orchestrator URL and confirm JSON shows **`"configured": true`** under **`jira_live`**. If **`missing_env`** is non-empty, add those variables and redeploy.

Add **`--add-cloudsql-instances=PROJECT_ID:REGION:INSTANCE`** when using Cloud SQL (see Phase 3b for Redis/VPC). *(Replace `--set-secrets` with plain `--set-env-vars` while testing, or wire Secret Manager names you actually created per `docs/SECRETS.md`.)*

### JIRA live API (`fetch_jira_ticket`, ticket status)

The orchestrator uses **`pipeline/embedding_worker/jira_client.py`**, which reads **`os.environ`** only (no `.env.local` in the container). If these are missing, JIRA calls fail when the agent needs live Atlassian data:

| Variable | Example | Secret Manager (recommended) |
|----------|---------|--------------------------------|
| **`JIRA_BASE_URL`** | `https://yourorg.atlassian.net` | Plain env var is fine |
| **`JIRA_API_TOKEN`** | Atlassian API token | Yes — e.g. `jira_api_token` |
| **`JIRA_USER_EMAIL`** | Email for that token | Yes or env — e.g. `jira_user_email` |

**PowerShell — create secrets (once):**

```powershell
"https://yourorg.atlassian.net" | gcloud secrets create jira_base_url --data-file=- --project=$PROJECT_ID 2>$null
# Or skip secret and use --set-env-vars for JIRA_BASE_URL only
"ATATT..." | gcloud secrets create jira_api_token --data-file=- --project=$PROJECT_ID
"you@atlassian-account.com" | gcloud secrets create jira_user_email --data-file=- --project=$PROJECT_ID
```

Grant the **orchestrator** SA `secretAccessor` on those secrets, then extend deploy:

```text
--set-env-vars=GCP_PROJECT_ID=...,VERTEX_AI_LOCATION=...,GOOGLE_GENAI_USE_VERTEXAI=true,JIRA_BASE_URL=https://yourorg.atlassian.net
--set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JIRA_API_TOKEN=jira_api_token:latest,JIRA_USER_EMAIL=jira_user_email:latest
```

Atlassian is a **public** HTTPS endpoint; with **`--vpc-egress=private-ranges-only`**, traffic to JIRA does **not** go through the VPC connector (only private IPs do).

**Stop here and confirm:** Open the service URL + `/health` → `{"status":"ok",...}`. **Copy the base HTTPS URL** (no trailing slash) for Phase 5.

---

## Phase 5 — Deploy API gateway (Cloud Run)

```bash
ORCH_URL="https://cybmas-orchestrator-xxxxx-uc.a.run.app"

gcloud run deploy cybmas-api \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/api-gateway:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --vpc-connector=cybmas-redis-conn \
  --vpc-egress=private-ranges-only \
  --set-env-vars=ORCHESTRATOR_ENDPOINT=${ORCH_URL} \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JWT_SECRET_KEY=jwt_secret_key:latest
```

**Stop here and confirm:** Gateway `/health` OK; a test chat request works if DB/Redis/secrets are correct.

---

## Phase 5b — Migrations and seed data (**Cloud SQL**, not local Postgres)

The repo scripts do not care whether Postgres is local or Cloud SQL. They only need a reachable **`DATABASE_URL`** that points at your **Cloud SQL** database.

**Important:** The **`database_url`** secret used by Cloud Run often uses the **Unix socket** form (`…?host=/cloudsql/PROJECT:REGION:INSTANCE`). That form works **inside** Cloud Run, not on your laptop. For seeding from your machine, use a **TCP** URL through the **Cloud SQL Auth Proxy** (recommended) or Cloud SQL **public IP** (with authorized networks).

### 1. Install and run the Auth Proxy

- Download: [Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/connect-auth-proxy) for your OS.
- Start it (replace connection name from Cloud SQL → Instance → **Connection name**):

```bash
# Example: listens on localhost:5432
cloud-sql-proxy --port 5432 PROJECT_ID:REGION:INSTANCE_ID
```

Keep this terminal open while you run the Python commands below.

### 2. Set `DATABASE_URL` for the **proxy** (repo root)

Use your Cloud SQL **user**, **password** (URL-encoded if needed), **database name**, and **`127.0.0.1:5432`**:

```text
postgresql+asyncpg://DB_USER:URL_ENCODED_PASSWORD@127.0.0.1:5432/DB_NAME
```

Put that in **`.env.local`** as **`DATABASE_URL`**, or export it in the shell for one session. This is **only for admin/seed runs** from your PC; Cloud Run can keep using the secret with the socket URL.

### 3. Python env (same machine as the proxy)

From the **repository root**, with the same venv/deps you use for local dev (`psycopg2`, `asyncpg`, `bcrypt`, `python-dotenv`, etc.):

```bash
python scripts/run_migrations.py    # schema + pgvector migrations
python scripts/seed_users.py        # admin + demo engineers (login)
python scripts/seed_demo_data.py  # optional: tickets/incidents + embeddings (needs GCP / Vertex auth)
```

`seed_demo_data.py` calls Vertex for embeddings — use **`gcloud auth application-default login`** or a service account key with **Vertex AI User**, same as local.

**Stop here and confirm:** In Cloud SQL (Query editor or `psql`), you see rows in **`users`**; optional **`tickets`** / **`incidents`** after demo seed.

---

## Phase 6 — Cloud Run: frontend (Next.js)

The UI is **`frontend/`**, built as image **`frontend`** (see **`frontend/Dockerfile`**). Cloud Run sets **`PORT=8080`**; the Next standalone server uses it automatically.

1. **Image** — Must be built with **`_NEXT_PUBLIC_API_URL`** = your **`cybmas-api`** HTTPS base URL (no trailing slash). If you already ran Phase 3 with the default localhost URL, run Phase 3 again with the substitution above before deploying.

2. **Deploy** (adjust `REGION`, `PROJECT_ID`, `TAG`, image URL):

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

3. **CORS** — The browser calls the **API gateway** from the **frontend** origin. Redeploy **`cybmas-api`** with **`CORS_ORIGINS`** including your frontend URL (comma-separated if multiple):

```bash
FRONTEND_URL="https://cybmas-frontend-xxxxx-uc.a.run.app"
ORCH_URL="https://cybmas-orchestrator-xxxxx-uc.a.run.app"

gcloud run deploy cybmas-api \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/api-gateway:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=YOUR_GATEWAY_SA@${PROJECT_ID}.iam.gserviceaccount.com \
  --vpc-connector=cybmas-redis-conn \
  --vpc-egress=private-ranges-only \
  --set-env-vars=ORCHESTRATOR_ENDPOINT=${ORCH_URL},CORS_ORIGINS=${FRONTEND_URL} \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JWT_SECRET_KEY=jwt_secret_key:latest \
  --project=${PROJECT_ID}
```

**OPTIONS preflight → 400 + “CORS error” on POST:** Starlette rejects preflight when **`Origin`** is not allowed. The allow-list is an **exact** match (no trailing slash on the URL). In DevTools → Network → the **OPTIONS** request → **Request Headers**, copy **`Origin`** and ensure that exact string appears in **`CORS_ORIGINS`**. The gateway now strips trailing slashes from each entry in **`CORS_ORIGINS`**. You can also set **`CORS_ORIGIN_REGEX`** (full regex match on `Origin`), e.g. `https://.*\.a\.run\.app`, and add it to **`--set-env-vars`** when you redeploy **`cybmas-api`** (rebuild image after pulling the latest `main.py`).

Add **`--add-cloudsql-instances=...`** on the gateway if it uses the Cloud SQL socket. Merge any other env vars you already use so nothing is dropped.

**Stop here and confirm:** Open the **frontend** URL in a browser; register or log in; chat hits the gateway.

---

## Phase 7 — JIRA → embeddings (Cloud Run Job)

The **embedding worker** (`pipeline/embedding_worker/`) pulls issues from JIRA, calls **Vertex AI** `text-embedding-004`, and **upserts** rows into **Cloud SQL / pgvector**. It is **not** built by the default GitHub Actions workflow (so **`cloudbuild.yaml`** stays the same three images as before). Build the image when you need it:

```bash
gcloud builds submit --config=cloudbuild.embedding-worker.yaml --substitutions=_TAG=YOUR_TAG .
```

Then create or update the Cloud Run Job **`cybmas-embedding-worker`** with `gcloud run jobs deploy` (env/secrets/VPC/Cloud SQL flags as below). Use the **same tag** as your services if you want parity, or `latest`.

### Prereqs (same as orchestrator + DB)

- **Secret Manager** secrets already used by **`cybmas-orchestrator`**: `database_url`, `redis_url`, `jira_api_token`, `jira_user_email` (see Phase 4 / `docs/SECRETS.md`).
- **Cloud SQL**: `database_url` should use the **Unix socket** form for Cloud Run. Deploy the job with **`--add-cloudsql-instances=PROJECT_ID:REGION:INSTANCE_ID`** (same connection name as **`cybmas-orchestrator`** / **`cybmas-api`**).
- **Memorystore Redis**: add **`--vpc-connector=...`** and **`--vpc-egress=private-ranges-only`** using the same connector as the orchestrator (Phase 3b, e.g. **`cybmas-redis-conn`**). Without it, the job cannot reach a **private** Redis host.
- **Runtime service account** (recommended): use the **same** service account as **`cybmas-orchestrator`** (**`--service-account=...`**) with **Secret Manager**, **Cloud SQL Client**, **Vertex AI User**.
- **Database**: ensure **`Default`** exists in **`business_units`** (migration **`004_default_business_unit.sql`** or `database/seeds/business_units.sql`). Run **`python scripts/run_migrations.py`** against Cloud SQL if you have not applied **`004`** yet.

### Job env vars (for `gcloud run jobs deploy` or an env-vars YAML file)

| Env var | Required | Purpose |
|---------|----------|---------|
| **`JIRA_BASE_URL`** | Yes | e.g. `https://yourorg.atlassian.net` (no trailing slash) |
| **`JIRA_PROJECT_KEYS`** | No | If set, sync only these project keys. If **unset or empty**, sync **all projects** the JIRA user can access (no `project in` filter). |
| **`BU_B1_PROJECTS`**, **`BU_B2_PROJECTS`** | No | Map **project key** → **B1** / **B2** for **`business_unit`** only; does **not** restrict which projects are synced. |
| **`JIRA_BUSINESS_UNIT_FIELD_ID`** | No | e.g. **`customfield_10100`** — JIRA field value used as **`business_unit`** when non-empty (requested automatically in search). Must match **`business_units.code`**. |
| **`DEFAULT_BUSINESS_UNIT`** | No | Used when JIRA field is empty **and** project is not in the BU map. If unset, code **`Default`** is used. |
| **`INCIDENT_ISSUE_TYPES`** | No | Overrides default `Incident,Production Issue` |

On **`gcloud run jobs deploy`**, also pass **`--add-cloudsql-instances=PROJECT:REGION:INSTANCE`**, **`--vpc-connector`** / **`--vpc-egress`** (if Redis is private), **`--service-account`**, and **`--set-secrets`** (same pattern as **`cybmas-orchestrator`**). Job name defaults to **`cybmas-embedding-worker`**.

After the image exists in Artifact Registry and you have deployed the job once, confirm:

```bash
gcloud run jobs describe cybmas-embedding-worker --region=us-central1 --project=YOUR_PROJECT_ID
```

### Run the worker locally (debug JIRA → DB)

**`.env.local`** at the **repository root** must include the same vars as Cloud Run: **`DATABASE_URL`**, **`REDIS_URL`**, **`JIRA_BASE_URL`**, **`JIRA_API_TOKEN`**, **`JIRA_USER_EMAIL`**, **`GCP_PROJECT_ID`**, Vertex auth (**`GOOGLE_APPLICATION_CREDENTIALS`** or **`gcloud auth application-default login`**), optional **`BU_*`** / **`SYNC_MODE`**.

**Python version:** **`asyncpg`** usually has no wheel on very new Python (e.g. 3.14). Use **3.11 or 3.12** for the worker venv:

```powershell
cd F:\cybmas
py -3.12 -m venv .venv-embedding
.\.venv-embedding\Scripts\pip install -r pipeline\embedding_worker\requirements.txt
```

**Option A — helper script** (picks `.venv-embedding` or `.venv` if present):

```powershell
cd F:\cybmas
.\scripts\run_embedding_sync_local.ps1              # SYNC_MODE=delta
.\scripts\run_embedding_sync_local.ps1 -SyncMode full
.\scripts\run_embedding_sync_local.ps1 -Python C:\path\to\python3.12.exe
```

**Option B — manual:**

```powershell
cd F:\cybmas
$env:SYNC_MODE = "full"   # first-time: pull all matching issues; delta uses Redis watermark
.\.venv-embedding\Scripts\python pipeline\embedding_worker\main.py
```

`main.py` loads **`<repo>/.env.local`** automatically; the worker directory is on `sys.path` for imports.

Watch the console for:

- **`sync.issue_begin`** — JIRA issue picked up (`jira_id`, `kind` ticket/incident, `business_unit`, `summary_preview`).
- **`sync.issue_synced`** — normalize + embed + upsert finished without exception.
- **`sync.issue_failed`** — exception with `error`, `error_type`, and traceback (`exc_info`).
- **`upsert.ticket_upserted`** / **`upsert.incident_upserted`** — row written (from `upsert.py`).
- **`sync.db_counts`** — `tickets_table_rows` / `incidents_table_rows` after the run.
- **`sync.completed`** — `total_processed` vs `errors`.

For **JSON** logs (closer to Cloud Logging), set **`LOG_FORMAT=json`** before running.

### Manual run (delta or one-off full sync)

```bash
# Delta (default template env SYNC_MODE=delta)
gcloud run jobs execute cybmas-embedding-worker --region=us-central1 --project=YOUR_PROJECT_ID --wait

# Full re-sync (overrides env for this execution only)
gcloud run jobs execute cybmas-embedding-worker --region=us-central1 --project=YOUR_PROJECT_ID \
  --update-env-vars=SYNC_MODE=full --wait
```

Logs: **Cloud Run → Jobs → Executions → Logs**.

### Optional — Cloud Scheduler (every 15 minutes)

Create a **service account** used only to **invoke** the job (e.g. `cybmas-scheduler@PROJECT.iam.gserviceaccount.com`), grant it **`roles/run.invoker`** on the job, enable **Cloud Scheduler API**, then run from repo root (bash):

```bash
export PROJECT_ID=YOUR_PROJECT_ID
export CALLER_SA=cybmas-scheduler@${PROJECT_ID}.iam.gserviceaccount.com
chmod +x scripts/setup_embedding_scheduler.sh
./scripts/setup_embedding_scheduler.sh
```

Or see **`scripts/setup_embedding_scheduler.ps1`** on Windows. Adjust **`SCHEDULE`** (default `*/15 * * * *`) inside the script if needed.

---

## Phase 7b — KB JSON/JSONL from GCS → `knowledge_articles` (Cloud Run Job)

Loads a **single object** from **Google Cloud Storage** (JSON with a `documents` array or **JSONL**), embeds with **Vertex** `text-embedding-004`, and **upserts** into **`knowledge_articles`** (migration **`005_knowledge_articles.sql`**). This job does **not** use Redis or JIRA.

Build the image (not part of the default three-image **`cloudbuild.yaml`**):

```bash
gcloud builds submit --config=cloudbuild.kb-ingest-job.yaml --substitutions=_TAG=YOUR_TAG .
```

### Prereqs

- **Cloud SQL** + **`database_url`** secret: use the **Unix socket** DSN form for Cloud Run (same as **`cybmas-orchestrator`**).
- **Migration `005`** applied** on that database.
- **GCS**: upload your KB file (e.g. `gs://YOUR_BUCKET/kb/articles.jsonl`). The job’s service account needs **`roles/storage.objectViewer`** on that bucket (or the object), or use a bucket with uniform access and grant the SA **Storage Object Viewer**.
- **Vertex AI**: same project/region as the embedding worker (**`GCP_PROJECT_ID`**, **`VERTEX_AI_LOCATION`**).

### Job env vars

| Env var | Required | Purpose |
|---------|----------|---------|
| **`KB_GCS_URI`** | Yes | e.g. `gs://my-bucket/path/kb.json` or `.jsonl` |
| **`DATABASE_URL`** | Yes | Usually from **`--set-secrets=database_url=database_url:latest`** (map to env name **`DATABASE_URL`**) |
| **`GCP_PROJECT_ID`** | Yes | GCP project for Vertex |
| **`VERTEX_AI_LOCATION`** | Yes | e.g. `us-central1` |
| **`KB_THROTTLE_SECONDS`** | No | Sleep after each embed (rate limits); default `0` |

### Deploy example

Adjust **`PROJECT_ID`**, **`REGION`**, **`INSTANCE_CONNECTION_NAME`**, **`IMAGE_TAG`**, service account, and bucket URI.

```bash
export PROJECT_ID=YOUR_PROJECT_ID
export REGION=us-central1
export INSTANCE_CONNECTION_NAME=${PROJECT_ID}:${REGION}:YOUR_INSTANCE
export IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/kb-ingest-job:latest

gcloud run jobs deploy cybmas-kb-ingest-job \
  --image=${IMAGE} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --tasks=1 \
  --max-retries=0 \
  --task-timeout=3600 \
  --set-env-vars=GCP_PROJECT_ID=${PROJECT_ID},VERTEX_AI_LOCATION=us-central1,KB_GCS_URI=gs://YOUR_BUCKET/path/kb.jsonl \
  --set-secrets=DATABASE_URL=database_url:latest \
  --add-cloudsql-instances=${INSTANCE_CONNECTION_NAME} \
  --service-account=YOUR_ORCH_SA@${PROJECT_ID}.iam.gserviceaccount.com
```

**Note:** No **`--vpc-connector`** is required for GCS + Vertex alone. If you reuse the orchestrator SA, it likely already has Secret Manager + Cloud SQL Client + Vertex AI User; add **Storage Object Viewer** on the KB bucket.

### Run (override `KB_GCS_URI` per execution if you prefer)

```bash
gcloud run jobs execute cybmas-kb-ingest-job --region=${REGION} --project=${PROJECT_ID} --wait

gcloud run jobs execute cybmas-kb-ingest-job --region=${REGION} --project=${PROJECT_ID} \
  --update-env-vars=KB_GCS_URI=gs://YOUR_BUCKET/other/kb.jsonl --wait
```

---

## Optional — Local Docker smoke test

If you **do** have Docker, you can build from repo root:

```bash
docker build -f services/api_gateway/Dockerfile -t cybmas-api:local .
docker build -f services/orchestrator/Dockerfile -t cybmas-orchestrator:local .
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t cybmas-frontend:local frontend/
```

Skip if policy forbids Docker.

---

## CI/CD — GitHub Actions → Cloud Build → Cloud Run (**Dev**)

**Full standalone runbook (new GCP project / new repo, plus troubleshooting):** [`docs/CICD_PIPELINE_SETUP.md`](../docs/CICD_PIPELINE_SETUP.md).

The workflow **`.github/workflows/gcp-deploy.yml`** is **Dev-only** for now:

- **Push to `main`** — Cloud Build (`cloudbuild.yaml`) then deploy images to Dev Cloud Run **services** only (**api**, **orchestrator**, **frontend**).
- **Actions → Run workflow** — same steps without a new commit (manual redeploy).

Deploy steps update **service** container images only. VPC connector, secrets, and env on each service stay as you last set them (Phases 4–6).

**Prereq:** Dev Cloud Run services **`cybmas-api`**, **`cybmas-orchestrator`**, **`cybmas-frontend`** must exist once. The **embedding worker** is optional: Phase 7 + **`cloudbuild.embedding-worker.yaml`**.

### 1. GitHub — Secrets and variables

**Secrets** (Settings → Secrets and variables → Actions):

| Secret | Value |
|--------|--------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full provider name, e.g. `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Service account email for OIDC (see §2) |

**Variables:**

| Variable | Required | Note |
|----------|----------|------|
| `GCP_PROJECT_DEV` | Yes | Dev GCP project ID |
| `DEV_API_GATEWAY_URL` | Yes | HTTPS base URL of dev **`cybmas-api`** (no trailing slash); baked into the frontend build |
| `GCP_REGION` | No | Defaults to `us-central1` in the workflow |
| `ARTIFACT_REGISTRY_REPO` | No | Defaults to `cybmas` |
| `CLOUD_RUN_SERVICE_*_DEV` | No | Only if your Dev service names differ from `cybmas-api`, `cybmas-orchestrator`, `cybmas-frontend` |
**Secrets “not found” in Actions though they exist in Settings**

- GitHub only injects **repository** Actions secrets into runs for that **same** repository. Open the failed run: the title shows **`owner/repo`** — secrets must be defined on **that** repo. If you push to a **fork**, the workflow runs on the **fork**; the fork has **no** copies of your upstream secrets unless you add them there (or push to upstream instead).
- **Pull requests from forks** do not receive secrets (the message you saw). This workflow is triggered by **push** to `main`/`master` and **workflow_dispatch**, not by `pull_request`. If you later add `pull_request`, the same fork rule applies to those runs.
- Secrets stored only under a GitHub **Environment** are used only if the job declares `environment: that-name`. The workflow sets **`environment: GCP_CICD`** so secrets/variables on that environment are loaded. Rename the environment in GitHub or change that line to match (e.g. `Dev`). If **`GCP_CICD`** has **required reviewers**, every run waits for approval—clear that for automatic Dev deploys, or use repository secrets only and remove `environment:` from the workflow.
- **Dependabot** uses separate **Dependabot** secrets, not the Actions secrets above.

### 2. Workload Identity Federation (Dev project)

Use your **Dev** `PROJECT_ID` below. This avoids storing a JSON key in GitHub.

**Where to run:** Any shell with `gcloud` installed and logged in (`gcloud auth login`) as a user who can manage IAM on the dev project. **Google Cloud Shell** uses **bash** (first block below). On **Windows PowerShell**, `export` does not exist — use the **PowerShell** block instead (or use **WSL / Git Bash** and run the bash script).

**Bash (Cloud Shell, WSL, Git Bash)**

```bash
export PROJECT_ID=YOUR_DEV_GCP_PROJECT_ID
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
export POOL=github
export PROVIDER=github
export REPO="GITHUB_ORG/GITHUB_REPO"   # e.g. acme/cybmas — must match this repo on GitHub (case-sensitive)

# One line per gcloud — trailing `\` is bash-only; do not paste those lines into PowerShell.
gcloud iam workload-identity-pools create "$POOL" --location="global" --project="$PROJECT_ID" --display-name="GitHub"

# GitHub OIDC: GCP requires --attribute-condition to reference a JWT claim (see deployment-pipelines conditions).
# Restrict to one repo (recommended). For all repos under an org: assertion.repository_owner=='your-org'
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location="global" --project="$PROJECT_ID" --workload-identity-pool="$POOL" --display-name="GitHub provider" --issuer-uri="https://token.actions.githubusercontent.com" --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" --attribute-condition="assertion.repository=='${REPO}'"

export GHA_SA="github-actions-cybmas@${PROJECT_ID}.iam.gserviceaccount.com"
# If this errors with ALREADY_EXISTS, continue to the next command.
gcloud iam service-accounts create github-actions-cybmas --project="$PROJECT_ID" --display-name="GitHub Actions cybmas"

gcloud iam service-accounts add-iam-policy-binding "$GHA_SA" --project="$PROJECT_ID" --role="roles/iam.workloadIdentityUser" --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}"
```

**Already ran `create-oidc` without `--attribute-condition`?** Delete the provider, then run `create-oidc` again with the line above (pool and SA can stay):

`gcloud iam workload-identity-pools providers delete "$PROVIDER" --location=global --workload-identity-pool="$POOL" --project="$PROJECT_ID"`

**PowerShell (Windows)** — set your project and GitHub repo, then run the whole block.

**Do not** paste the **bash** script into **Windows PowerShell 5.1**: bash uses `\` line continuations and operators like **`||`** / **`&&`**, which PowerShell 5.1 does not support (you may see **`The token '||' is not a valid statement separator`**). Use the **PowerShell** block below, or **PowerShell 7+**, or **Cloud Shell / WSL / Git Bash** for the bash block.

If you see **`WORKLOAD_IDENTITY_POOL must be specified`**, the pool name was not passed to `create`.

**PowerShell line continuation:** put a **backtick** (`` ` ``) as the **last character** on the line—**no space after it**—then continue the command on the next line.

```powershell
$PROJECT_ID = "YOUR_DEV_GCP_PROJECT_ID"
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$POOL = "github"
$PROVIDER = "github"
$REPO = "GITHUB_ORG/GITHUB_REPO"   # e.g. acme/cybmas

gcloud iam workload-identity-pools create github `
  --location=global `
  --project=$PROJECT_ID `
  --display-name="GitHub"

# Must include --attribute-condition (same REPO as $REPO). Org-wide: assertion.repository_owner=='your-org'
gcloud iam workload-identity-pools providers create-oidc github `
  --location=global `
  --project=$PROJECT_ID `
  --workload-identity-pool=$POOL `
  --display-name="GitHub provider" `
  --issuer-uri="https://token.actions.githubusercontent.com" `
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" `
  --attribute-condition="assertion.repository=='$REPO'"

$GHA_SA = "github-actions-cybmas@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts create github-actions-cybmas `
  --project=$PROJECT_ID `
  --display-name="GitHub Actions cybmas" 2>$null

$member = "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$REPO"
gcloud iam service-accounts add-iam-policy-binding $GHA_SA `
  --project=$PROJECT_ID `
  --role="roles/iam.workloadIdentityUser" `
  --member=$member

# Project-level roles (Cloud Build submit, source upload, Cloud Run deploy)
foreach ($ROLE in @("roles/cloudbuild.builds.editor", "roles/storage.objectAdmin", "roles/run.developer", "roles/serviceusage.serviceUsageConsumer", "roles/artifactregistry.reader")) {
  gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$GHA_SA" `
    --role=$ROLE
}

# Act as each Cloud Run *runtime* service account (the SA each service runs as — not the GitHub SA).
# Each array entry must be ONE valid email only — the exact string from `gcloud run services describe ...` (see below).
# Do NOT concatenate two addresses (wrong: name@project.iam...@${PROJECT_ID}.iam... — that causes INVALID_ARGUMENT).
# If all three services use the same SA, list that single email once and run one binding, or use an array of one element.
$runtimeSas = @(
  "YOUR_GATEWAY_SA@${PROJECT_ID}.iam.gserviceaccount.com",
  "YOUR_ORCHESTRATOR_SA@${PROJECT_ID}.iam.gserviceaccount.com",
  "YOUR_FRONTEND_SA@${PROJECT_ID}.iam.gserviceaccount.com"
)
foreach ($RUNTIME_SA in $runtimeSas) {
  gcloud iam service-accounts add-iam-policy-binding $RUNTIME_SA `
    --project=$PROJECT_ID `
    --member="serviceAccount:$GHA_SA" `
    --role="roles/iam.serviceAccountUser"
}
```

**Examples of valid `$runtimeSas` entries** (pick one style; each string is a single email):

- Custom SAs in project `myproj`: `cybmas-api@myproj.iam.gserviceaccount.com` (substitute only `YOUR_*` / project id — **one** `@` domain).
- Default compute SA (from `describe`): `566370119486-compute@developer.gserviceaccount.com` — use **as-is**, with **no** extra `@project.iam.gserviceaccount.com` appended.

**PowerShell — print the three runtime emails** (then copy each into `$runtimeSas`):

```powershell
$REGION = "us-central1"
foreach ($svc in @("cybmas-api", "cybmas-orchestrator", "cybmas-frontend")) {
  gcloud run services describe $svc --region=$REGION --project=$PROJECT_ID --format="value(spec.template.spec.serviceAccountName)"
}
```

Grant **`$GHA_SA`** on the **Dev** project (bash — same shell as the bash WIF script above):

```bash
# Project-level roles (Cloud Build submit, source upload bucket, Cloud Run deploy)
for ROLE in roles/cloudbuild.builds.editor roles/storage.objectAdmin roles/run.developer roles/serviceusage.serviceUsageConsumer roles/artifactregistry.reader; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${GHA_SA}" \
    --role="$ROLE"
done
```

**`roles/iam.serviceAccountUser`** is not only at project scope: GitHub Actions must be allowed to **act as** each **runtime** service account attached to your Cloud Run services.

**What is `YOUR_GATEWAY_SA`?** A placeholder for the **service account name** (the part before `@`) used by **`cybmas-api`** in Cloud Run — not a fixed GCP string. Same pattern: **`YOUR_ORCHESTRATOR_SA`** → **`cybmas-orchestrator`**’s SA, **`YOUR_FRONTEND_SA`** → **`cybmas-frontend`**’s SA. Look them up under Cloud Run → each service → **Security** → Service account, or: `gcloud run services describe SERVICE --region=REGION --project=PROJECT_ID --format='value(spec.template.spec.serviceAccountName)'`. If a service uses the **default compute** account, the email ends with **`@developer.gserviceaccount.com`** — use that full value in the loop, not the `...@PROJECT_ID.iam.gserviceaccount.com` pattern.

```bash
# Example — repeat for gateway, orchestrator, frontend if they use different runtime SAs
for RUNTIME_SA in \
  "YOUR_GATEWAY_SA@${PROJECT_ID}.iam.gserviceaccount.com" \
  "YOUR_ORCHESTRATOR_SA@${PROJECT_ID}.iam.gserviceaccount.com" \
  "YOUR_FRONTEND_SA@${PROJECT_ID}.iam.gserviceaccount.com"
do
  gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${GHA_SA}" \
    --role="roles/iam.serviceAccountUser"
done
```

If all three services share **one** compute service account, a single `add-iam-policy-binding` on that account is enough.

Ensure the **Cloud Build default service account** can push to Artifact Registry (Phase 2).

**`gcloud builds submit` forbidden on bucket `[PROJECT_ID_cloudbuild]`** (e.g. `cybmas_cloudbuild`) **or `serviceusage.services.use`**

`gcloud builds submit` uploads source to **`gs://PROJECT_ID_cloudbuild`** as the **GitHub Actions** service account. That call also uses **Service Usage** on the project (`X-Goog-User-Project`). Apply **all** of the following on the **dev project** for `github-actions-cybmas@PROJECT_ID.iam.gserviceaccount.com`:

1. **`roles/serviceusage.serviceUsageConsumer`** (includes `serviceusage.services.use`).
2. **`roles/cloudbuild.builds.editor`** (start builds).
3. **`roles/storage.objectAdmin`** at **project** level (from the role loop) **may not be enough** — Cloud Build often needs **bucket metadata** (`storage.buckets.get` / list). If the error persists after (1)–(2), grant **project-level** **`roles/storage.admin`** to that SA (broader; typical fix for this exact error):

```powershell
$PROJECT_ID = "cybmas"
$GHA_SA = "github-actions-cybmas@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$GHA_SA" `
  --role="roles/storage.admin"
```

4. **Bucket-level** binding (optional if you prefer not to use project `storage.admin`):

```powershell
gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}_cloudbuild" `
  --member="serviceAccount:$GHA_SA" `
  --role="roles/storage.objectAdmin"
```

If it **still** fails, an **organization policy** (e.g. domain-restricted sharing, resource locations) is likely blocking — only an **org admin** can allow the SA or bucket. As a longer-term alternative, use a **Cloud Build trigger** connected to GitHub so Cloud Build clones source inside GCP (no GitHub SA upload to `_cloudbuild`).

Verify the bucket exists: `gcloud storage buckets describe "gs://${PROJECT_ID}_cloudbuild" --project=$PROJECT_ID`

**`PERMISSION_DENIED: artifactregistry.repositories.downloadArtifacts`** on `gcloud run deploy`

`gcloud run deploy --image=...docker.pkg.dev/...` runs as the **GitHub Actions** service account; it must be able to **read** images from Artifact Registry. Grant **`roles/artifactregistry.reader`** on the dev project (or on the `cybmas` repository only):

```powershell
$PROJECT_ID = "cybmas"
$GHA_SA = "github-actions-cybmas@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$GHA_SA" `
  --role="roles/artifactregistry.reader"
```

The **Cloud Run runtime** service account (on each service) also needs pull access to deploy new revisions; if the runtime SA differs from the GitHub SA, ensure that runtime SA has **`roles/artifactregistry.reader`** too (often already granted in Phase 2).

### 3. Artifact Registry (Dev)

The **cybmas** Docker repository must exist in the Dev project and region (Phase 2). `gcloud builds submit` uses `--project=$GCP_PROJECT_DEV`.

### 4. Production (later)

A separate prod pipeline (second project, `cybmas-prod-*` services, GitHub Environment approval) can be added when you are ready; it is not in the workflow yet.

---

## Changelog

- **CI/CD:** `.github/workflows/gcp-deploy.yml` — **Dev only:** push **`main`** or manual **Run workflow** → Cloud Build + Dev Cloud Run.
- **Phase 6 / `cloudbuild.yaml`:** **`frontend`** image; **`_NEXT_PUBLIC_API_URL`**; redeploy **`cybmas-api`** with **`CORS_ORIGINS`** = frontend URL.
- **Phase 5b:** Run migrations/seeds against **Cloud SQL** via Auth Proxy + TCP `DATABASE_URL` (not the `/cloudsql/` socket URL from your laptop).
- **Phase 3b:** Memorystore Redis + Serverless VPC Access connector; Cloud Run uses `--vpc-connector` + `--vpc-egress=private-ranges-only` + Secret `redis_url`.
- Dockerfiles: gateway + orchestrator context **`.`** (repo root); frontend context **`frontend/`**.
- Root **`.dockerignore`**, **`cloudbuild.yaml`** push to Artifact Registry.
