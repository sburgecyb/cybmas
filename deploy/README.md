# GCP deployment — step by step

Work through **phases in order**. You do **not** need Docker on your laptop; use **Cloud Build** (see Phase 0).

| Phase | What you do | Outcome |
|-------|----------------|---------|
| **0** | Install `gcloud`, pick project | CLI ready |
| **1** | Enable APIs | Services can run |
| **2** | Artifact Registry + IAM | Image storage + push rights |
| **3** | `gcloud builds submit` | `api-gateway` + `orchestrator` images |
| **4** | Cloud Run: orchestrator | ADK backend URL |
| **5** | Cloud Run: API gateway | `ORCHESTRATOR_ENDPOINT` → phase 4 URL |
| **6** | Frontend (optional) | `NEXT_PUBLIC_API_URL` → gateway |

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

**Easiest (uses defaults in `cloudbuild.yaml`: `us-central1`, repo `cybmas`, tag `latest`):**

```bash
gcloud builds submit --config=cloudbuild.yaml .
```

**Custom tag** — in **PowerShell** you must **quote** the substitutions string or commas break the flag (and you get a bogus image name):

```powershell
gcloud builds submit --config=cloudbuild.yaml --substitutions="_TAG=dev-1" .
```

**Bash / Cloud Shell** (commas OK unquoted):

```bash
gcloud builds submit --config=cloudbuild.yaml --substitutions=_TAG=dev-1 .
```

**Stop here and confirm:** [Artifact Registry](https://console.cloud.google.com/artifacts) → `cybmas` → you see `api-gateway` and `orchestrator` (tag `latest` or `dev-1`).

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

gcloud run deploy cybmas-orchestrator \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/cybmas/orchestrator:${TAG} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=YOUR_ORCHESTRATOR_SA@${PROJECT_ID}.iam.gserviceaccount.com \
  --set-env-vars=GCP_PROJECT_ID=${PROJECT_ID},VERTEX_AI_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest
```

*(Replace `--set-secrets` with plain `--set-env-vars` while testing, or wire Secret Manager names you actually created per `docs/SECRETS.md`.)*

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
  --set-env-vars=ORCHESTRATOR_ENDPOINT=${ORCH_URL} \
  --set-secrets=DATABASE_URL=database_url:latest,REDIS_URL=redis_url:latest,JWT_SECRET_KEY=jwt_secret_key:latest
```

**Stop here and confirm:** Gateway `/health` OK; a test chat request works if DB/Redis/secrets are correct.

---

## Phase 6 — Frontend (optional)

Build with **Docker** in Cloud Build or locally; set **`NEXT_PUBLIC_API_URL`** to the **gateway** URL at build time. Dockerfile context is the `frontend/` directory (see `frontend/Dockerfile`).

---

## Optional — Local Docker smoke test

If you **do** have Docker, you can build from repo root:

```bash
docker build -f services/api_gateway/Dockerfile -t cybmas-api:local .
docker build -f services/orchestrator/Dockerfile -t cybmas-orchestrator:local .
```

Skip if policy forbids Docker.

---

## Changelog

- Dockerfiles expect build context **`.`** (repo root); orchestrator = `services.orchestrator.server:app`, gateway = `services.api_gateway.main:app`.
- Root **`.dockerignore`**, **`cloudbuild.yaml`** push to Artifact Registry.
