# GCP deployment — step by step

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

Builds three images: **`api-gateway`**, **`orchestrator`**, **`frontend`**. The Next.js app bakes **`NEXT_PUBLIC_API_URL`** at build time (default `http://localhost:8000`). For a **production** frontend, set **`_NEXT_PUBLIC_API_URL`** to the **HTTPS URL of `cybmas-api`** (you get that URL after Phase 5). If you have not deployed the API yet, you can run Phase 3 once for backends only by using the default (frontend image will point at localhost until you **re-run** this phase with the real gateway URL).

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

**Stop here and confirm:** [Artifact Registry](https://console.cloud.google.com/artifacts) → `cybmas` → you see **`api-gateway`**, **`orchestrator`**, and **`frontend`** (tag `latest` or `dev-1`).

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

The workflow **`.github/workflows/gcp-deploy.yml`** is **Dev-only** for now:

- **Push to `main`** — Cloud Build (root `cloudbuild.yaml`) then deploy images to Dev Cloud Run.
- **Actions → Run workflow** — same steps without a new commit (manual redeploy).

Deploy steps only update the **container image** (`gcloud run deploy … --image=…`). VPC connector, secrets, service accounts, and env vars stay as you already set on each service (Phases 4–6).

**Prereq:** Dev Cloud Run services **`cybmas-api`**, **`cybmas-orchestrator`**, **`cybmas-frontend`** must exist once (first deploy via CLI as in this doc). CI then rolls new revisions only.

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
foreach ($ROLE in @("roles/cloudbuild.builds.editor", "roles/storage.objectAdmin", "roles/run.developer")) {
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
for ROLE in roles/cloudbuild.builds.editor roles/storage.objectAdmin roles/run.developer; do
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
