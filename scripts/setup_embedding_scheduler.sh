#!/usr/bin/env bash
# One-time setup: Cloud Scheduler calls the Cloud Run Jobs API to run cybmas-embedding-worker.
#
# Prereqs: Cloud Scheduler API enabled; job cybmas-embedding-worker already deployed;
# CALLER_SA exists and can be granted roles/run.invoker on the job.
#
# Usage:
#   export PROJECT_ID=your-project
#   export CALLER_SA=cybmas-scheduler@${PROJECT_ID}.iam.gserviceaccount.com
#   ./scripts/setup_embedding_scheduler.sh
#
# If the scheduler job ID already exists, delete or rename SCHEDULER_JOB_ID, or use:
#   gcloud scheduler jobs update http ...

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project)}"
REGION="${REGION:-us-central1}"
JOB_NAME="${JOB_NAME:-cybmas-embedding-worker}"
SCHEDULER_JOB_ID="${SCHEDULER_JOB_ID:-embedding-worker-delta}"
SCHEDULE="${SCHEDULE:-*/15 * * * *}"

CALLER_SA="${CALLER_SA:?Set CALLER_SA to a service account email that will invoke the job}"

URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member="serviceAccount:${CALLER_SA}" \
  --role="roles/run.invoker"

gcloud scheduler jobs create http "${SCHEDULER_JOB_ID}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --schedule="${SCHEDULE}" \
  --uri="${URI}" \
  --http-method=POST \
  --oauth-service-account-email="${CALLER_SA}" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --description="Delta JIRA embedding sync (${JOB_NAME})"

echo "Scheduler job ${SCHEDULER_JOB_ID} created. URI: ${URI}"
