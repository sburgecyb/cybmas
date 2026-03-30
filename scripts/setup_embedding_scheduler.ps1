# One-time setup: Cloud Scheduler runs cybmas-embedding-worker on a schedule.
# Requires: gcloud, Cloud Scheduler API, existing Cloud Run Job, CALLER_SA with run.invoker.
#
#   $env:PROJECT_ID = "your-project"
#   $env:CALLER_SA = "cybmas-scheduler@$($env:PROJECT_ID).iam.gserviceaccount.com"
#   .\scripts\setup_embedding_scheduler.ps1

$ErrorActionPreference = "Stop"

$ProjectId = if ($env:PROJECT_ID) { $env:PROJECT_ID } else { gcloud config get-value project }
$Region = if ($env:REGION) { $env:REGION } else { "us-central1" }
$JobName = if ($env:JOB_NAME) { $env:JOB_NAME } else { "cybmas-embedding-worker" }
$SchedulerJobId = if ($env:SCHEDULER_JOB_ID) { $env:SCHEDULER_JOB_ID } else { "embedding-worker-delta" }
$Schedule = if ($env:SCHEDULE) { $env:SCHEDULE } else { "*/15 * * * *" }

if (-not $env:CALLER_SA) {
    Write-Error "Set environment variable CALLER_SA to the scheduler caller service account email."
}

$Uri = "https://$Region-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$ProjectId/locations/$Region/jobs/${JobName}:run"

gcloud run jobs add-iam-policy-binding $JobName `
    --project=$ProjectId `
    --region=$Region `
    --member="serviceAccount:$($env:CALLER_SA)" `
    --role="roles/run.invoker"

gcloud scheduler jobs create http $SchedulerJobId `
    --project=$ProjectId `
    --location=$Region `
    --schedule=$Schedule `
    --uri=$Uri `
    --http-method=POST `
    --oauth-service-account-email=$env:CALLER_SA `
    --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" `
    --description="Delta JIRA embedding sync ($JobName)"

Write-Host "Scheduler job $SchedulerJobId created. URI: $Uri"
