#!/usr/bin/env bash
# Deploys the BACKLOT FastAPI backend + web UI (Dockerfile at repo root)
# to Cloud Run. This is the recommended default demo path — it's the one
# deployment that keeps the full human-in-the-loop approval flow (see
# docs/DEPLOYMENT.md).
#
# Untested against a live project (no GCP billing available while writing
# this) — verify against `gcloud run deploy --help` and current docs
# before a real deploy. Run from the repo root.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
: "${REGION:?Set REGION, e.g. us-central1}"
: "${MCP_SERVER_URL:?Set MCP_SERVER_URL — the real IBM watsonx.data endpoint, or a deployed mcp_shim's public URL + /mcp}"
SERVICE_NAME="${SERVICE_NAME:-backlot}"

# One-time setup, if you haven't already:
#   gcloud secrets create mcp-auth-token --project="$PROJECT_ID"
#   echo -n "<the real IBM MCP credential>" | \
#     gcloud secrets versions add mcp-auth-token --project="$PROJECT_ID" --data-file=-

gcloud run deploy "$SERVICE_NAME" \
  --source=. \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},MCP_SERVER_URL=${MCP_SERVER_URL},BACKLOT_APP_NAME=backlot" \
  --set-secrets="MCP_AUTH_TOKEN=mcp-auth-token:latest"

# Notes:
# - --allow-unauthenticated is for demo convenience; drop it (and front the
#   service with IAP or a signed-in-only invoker policy) for anything real.
# - The deployed service account needs roles/aiplatform.user (Vertex AI) at
#   minimum; scope it further per backlot/agents/*.py's tool_filter
#   boundaries if you split agents into separate services later.
