# Enable GCP APIs for cybmas.
# Usage: .\scripts\gcp_enable_apis.ps1 -ProjectId YOUR_PROJECT_ID
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId
)

$ErrorActionPreference = "Stop"
gcloud config set project $ProjectId

$apis = @(
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com",
    "vpcaccess.googleapis.com",
    "compute.googleapis.com"
)

Write-Host "Enabling APIs on project $ProjectId ..."
foreach ($api in $apis) {
    Write-Host "  - $api"
    gcloud services enable $api --project=$ProjectId
}

Write-Host "Done. Next: deploy/README.md Phase 2 (Artifact Registry)."
