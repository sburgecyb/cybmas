# CI/CD pipeline setup — GitHub Actions → GCP (Cloud Build + Cloud Run)

This document is a **standalone runbook** for configuring automated **build and deploy** of the cybmas stack to **Google Cloud** using **GitHub Actions**. Follow it top to bottom when onboarding a **new GCP project** or a **new GitHub repository**.

**What the pipeline does**

- On **push** to `main` or `master`, or on **manual “Run workflow”**, it:
  1. Checks out the repo.
  2. Authenticates to GCP with **Workload Identity Federation** (no JSON key in GitHub).
  3. Runs **`gcloud builds submit`** with root **`cloudbuild.yaml`** (builds and pushes three images: `api-gateway`, `orchestrator`, `frontend`).
  4. Deploys new revisions to Cloud Run: **`cybmas-api`**, **`cybmas-orchestrator`**, **`cybmas-frontend`** (names configurable via GitHub Variables).

**What it does *not* do**

- It does **not** create Cloud Run services, VPC connectors, secrets, or databases. You must complete a **first-time manual deploy** (or Terraform) so each service exists and has the right env, secrets, and networking. The pipeline only **updates the container image** on existing services.

**Related files**

- Workflow: `.github/workflows/gcp-deploy.yml`
- Build definition: `cloudbuild.yaml` (repository root)
- **GCP configuration + manual build/deploy (prerequisite stack):** [`docs/GCP_SETUP_AND_DEPLOY.md`](GCP_SETUP_AND_DEPLOY.md)
- Phased detail and extras: `deploy/README.md`

---

## 1. Prerequisites checklist

| # | Item |
|---|------|
| 1 | **GCP project** with billing enabled; note **project ID** (e.g. `mycompany-cybmas-dev`). |
| 2 | **GitHub repository** containing this codebase; note **`owner/repo`** (e.g. `acme/cybmas`) — must match WIF later (**case-sensitive**). |
| 3 | **gcloud** CLI installed locally or use **Cloud Shell**. |
| 4 | Cloud Run services **`cybmas-api`**, **`cybmas-orchestrator`**, **`cybmas-frontend`** already deployed once with correct configuration (`deploy/README.md` Phases 4–6). |
| 5 | **HTTPS URL** of the dev API gateway for the Next.js build: `DEV_API_GATEWAY_URL` (no trailing slash). |

---

## 2. Enable APIs and Artifact Registry

Enable required APIs (see `scripts/gcp_enable_apis.ps1` / `.sh` in the repo, or enable in Console): Cloud Build, Artifact Registry, Cloud Run, IAM, Service Usage, Storage, etc.

**Create a Docker Artifact Registry repository** (name `cybmas` unless you change `ARTIFACT_REGISTRY_REPO`):

```bash
gcloud artifacts repositories create cybmas \
  --repository-format=docker \
  --location=us-central1 \
  --project=PROJECT_ID \
  --description="cybmas images"
```

**Allow Cloud Build’s service account to push images** (replace `PROJECT_ID` and `PROJECT_NUMBER`):

```bash
PROJECT_ID=YOUR_PROJECT_ID
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

gcloud artifacts repositories add-iam-policy-binding cybmas \
  --location=us-central1 \
  --member="serviceAccount:${CLOUDBUILD_SA}" \
  --role="roles/artifactregistry.writer" \
  --project="$PROJECT_ID"
```

**Naming note:** `AR_REPO` / `_REPO` in `cloudbuild.yaml` is this **Artifact Registry repository id** (`cybmas`). It is **not** the GitHub repo (`owner/cybmas`).

---

## 3. Workload Identity Federation (GitHub → GCP)

Run in **Cloud Shell** (bash) or **PowerShell** on Windows. Use the **same** `PROJECT_ID` and GitHub repo string `OWNER/REPO` everywhere.

### 3.1 Variables to set

- `PROJECT_ID` — GCP project ID.
- `REPO` — GitHub repository as **`owner/repo`** (must match Actions, e.g. `sburgecyb/cybmas`).
- Pool id **`github`** and provider id **`github`** (must match commands below if you change them).

### 3.2 PowerShell (Windows) — full bootstrap

Use a **backtick** `` ` `` as the **last character** on continued lines (no space after it). Do **not** paste bash `\` continuations into PowerShell 5.1.

```powershell
$PROJECT_ID = "YOUR_PROJECT_ID"
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$POOL = "github"
$REPO = "GITHUB_OWNER/GITHUB_REPO"

gcloud iam workload-identity-pools create github `
  --location=global `
  --project=$PROJECT_ID `
  --display-name="GitHub"

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
```

**Important:** GCP requires **`--attribute-condition`** for the GitHub OIDC provider. If you created the provider **without** it, delete and recreate the provider:

```powershell
gcloud iam workload-identity-pools providers delete github `
  --location=global --workload-identity-pool=github --project=$PROJECT_ID
```

Then run the `create-oidc` block again.

### 3.3 Get the provider resource name (for GitHub Secret)

```powershell
gcloud iam workload-identity-pools providers describe github `
  --location=global `
  --workload-identity-pool=github `
  --project=$PROJECT_ID `
  --format="value(name)"
```

Example output: `projects/123456789012/locations/global/workloadIdentityPools/github/providers/github`  
→ store as secret **`GCP_WORKLOAD_IDENTITY_PROVIDER`**.

Service account email → secret **`GCP_SERVICE_ACCOUNT_EMAIL`**:  
`github-actions-cybmas@PROJECT_ID.iam.gserviceaccount.com`

---

## 4. IAM for `github-actions-cybmas` (project roles)

Grant these **project-level** roles to **`github-actions-cybmas@PROJECT_ID.iam.gserviceaccount.com`**:

| Role | Why |
|------|-----|
| `roles/cloudbuild.builds.editor` | Start `gcloud builds submit`. |
| `roles/run.developer` | Deploy Cloud Run revisions. |
| `roles/serviceusage.serviceUsageConsumer` | `serviceusage.services.use` (required with `X-Goog-User-Project` during submit/deploy). |
| `roles/artifactregistry.reader` | Resolve/pull images during `gcloud run deploy` as the GitHub identity. |
| `roles/storage.objectAdmin` | Baseline access for Cloud Build source staging (may be insufficient alone — see §7). |

**PowerShell loop:**

```powershell
$PROJECT_ID = "YOUR_PROJECT_ID"
$GHA_SA = "github-actions-cybmas@${PROJECT_ID}.iam.gserviceaccount.com"
foreach ($ROLE in @(
    "roles/cloudbuild.builds.editor",
    "roles/storage.objectAdmin",
    "roles/run.developer",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/artifactregistry.reader"
  )) {
  gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$GHA_SA" --role=$ROLE
}
```

### 4.1 `roles/iam.serviceAccountUser` on **runtime** service accounts

Cloud Run runs as a **runtime** service account per service. The GitHub SA must be allowed to **act as** that identity when creating new revisions.

List each service’s runtime SA:

```powershell
$REGION = "us-central1"
foreach ($svc in @("cybmas-api", "cybmas-orchestrator", "cybmas-frontend")) {
  gcloud run services describe $svc --region=$REGION --project=$PROJECT_ID `
    --format="value(spec.template.spec.serviceAccountName)"
}
```

For **each distinct** email returned (must be **one full address** — do not concatenate two emails):

```powershell
gcloud iam service-accounts add-iam-policy-binding RUNTIME_SA_EMAIL `
  --project=$PROJECT_ID `
  --member="serviceAccount:$GHA_SA" `
  --role="roles/iam.serviceAccountUser"
```

If all three services share one SA, one binding is enough.

---

## 5. GitHub configuration

### 5.1 GitHub Environment

The workflow sets **`environment: GCP_CICD`**. In the GitHub repo:

**Settings → Environments → New environment → name `GCP_CICD`**

- Add **Secrets** and/or **Variables** here **or** use repository-level Actions secrets/variables (both can work; environment is required so the job resolves that environment).
- If you set **required reviewers** on `GCP_CICD`, every run waits for approval — remove that for fully automatic dev deploys.

### 5.2 Secrets (Actions → Secrets, and/or Environment `GCP_CICD`)

| Secret | Value |
|--------|--------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full provider name from §3.3 |
| `GCP_SERVICE_ACCOUNT_EMAIL` | `github-actions-cybmas@PROJECT_ID.iam.gserviceaccount.com` |

### 5.3 Variables

| Variable | Required | Example |
|----------|----------|---------|
| `GCP_PROJECT_DEV` | Yes | GCP project ID |
| `DEV_API_GATEWAY_URL` | Yes | `https://cybmas-api-xxxxx-uc.a.run.app` (no trailing slash) |
| `GCP_REGION` | No | Default in workflow: `us-central1` |
| `ARTIFACT_REGISTRY_REPO` | No | Default: `cybmas` |
| `CLOUD_RUN_SERVICE_*_DEV` | No | Override only if service names differ |

**Note:** `vars.GCP_PROJECT_DEV` is **not** in a file — it is defined only in GitHub’s Variables UI.

### 5.4 Push the workflow

Ensure `.github/workflows/gcp-deploy.yml` is on the default branch (`main` or `master`). The workflow triggers on both.

---

## 6. Verification

1. **Actions** → **GCP build and deploy (Dev)** → **Run workflow**.
2. Confirm steps: Checkout → Check secrets → Authenticate → setup-gcloud → Cloud Build → Deploy Cloud Run.
3. Open Cloud Run URLs and smoke-test the app.

---

## 7. Problems we hit and how we fixed them

| Symptom | Cause | Fix |
|---------|--------|-----|
| `auth@v2` — must specify `workload_identity_provider` or `credentials_json` | Secret empty or not visible to the job | Add repository/environment secrets with **exact** names; ensure workflow runs on the **same** repo where secrets exist (not a fork). If secrets live only under **Environment**, job must declare `environment: GCP_CICD` (or the env name you use). |
| GitHub text: secrets not passed to workflows from **forks** | Normal policy | Push to **upstream** repo or duplicate secrets on the fork; do not rely on fork PRs for deploy secrets. |
| PowerShell: `export` / `\` / `\|\|` errors | Bash vs PowerShell | Use the **PowerShell** blocks in this doc; use backticks for line continuation; no `export` or bash `\`. |
| `WORKLOAD_IDENTITY_POOL must be specified` | Pool id not passed to `gcloud create` | Use **one-line** `gcloud ... create github ...` or ensure `$POOL` is set; no stray space after line-continuation backtick. |
| `attribute condition must reference provider's claims` | Missing `--attribute-condition` on OIDC provider | Add `--attribute-condition="assertion.repository=='OWNER/REPO'"` (or `repository_owner` for org-wide). Delete provider and recreate if needed. |
| `INVALID_ARGUMENT` on `add-iam-policy-binding` for runtime SA | **Two** emails concatenated in one string | Use **one** email per binding — exactly as returned by `gcloud run services describe ... serviceAccountName`. Default compute SA ends with `@developer.gserviceaccount.com` — do not append `@project.iam.gserviceaccount.com`. |
| Forbidden **`PROJECT_ID_cloudbuild`** / `serviceusage.services.use` | GitHub SA cannot use staging bucket / APIs | Grant `roles/serviceusage.serviceUsageConsumer`. If still failing, grant **`roles/storage.admin`** on the project (Cloud Build submit often needs bucket metadata, not only `objectAdmin`). Optionally bind `roles/storage.objectAdmin` on `gs://PROJECT_ID_cloudbuild`. |
| `artifactregistry.repositories.downloadArtifacts` denied on deploy | GitHub SA cannot read Artifact Registry | Grant **`roles/artifactregistry.reader`** on the project to `github-actions-cybmas@...`. Ensure runtime SAs can pull images too. |
| `.git/index.lock` exists | Stale Git lock | Delete `.git/index.lock` when no other `git` process is running. |

---

## 8. Quick reference — image URLs and bucket

- **Artifact Registry image:**  
  `{REGION}-docker.pkg.dev/{GCP_PROJECT_ID}/{AR_REPO}/{image}:{TAG}`  
  e.g. `us-central1-docker.pkg.dev/myproj/cybmas/api-gateway:abc1234`

- **Cloud Build default source bucket:**  
  `gs://{GCP_PROJECT_ID}_cloudbuild`

---

## 9. Changing names later

- **GitHub Environment:** Rename in GitHub and set `environment: ...` in `.github/workflows/gcp-deploy.yml` to match.
- **WIF pool/provider ids:** If not `github`/`github`, update all `gcloud` commands and the **describe** command for the provider name.
- **Default branch:** Workflow listens to `main` and `master`; add others in `on.push.branches` if needed.

---

*Last aligned with repo workflow: `.github/workflows/gcp-deploy.yml` (Dev, `environment: GCP_CICD`).*
