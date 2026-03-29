#!/usr/bin/env bash
# Usage: ./scripts/gcp_enable_apis.sh YOUR_PROJECT_ID
set -euo pipefail
PROJECT_ID="${1:?Usage: $0 YOUR_PROJECT_ID}"
gcloud config set project "$PROJECT_ID"

for api in \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com
do
  echo "  - $api"
  gcloud services enable "$api" --project="$PROJECT_ID"
done

echo "Done. Next: deploy/README.md Phase 2."
