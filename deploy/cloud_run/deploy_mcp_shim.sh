#!/usr/bin/env bash
# Optional: deploys the synthetic mcp_shim (Dockerfile.mcp_shim) to Cloud
# Run, so the grounded Budget/Resource agents have something to call from
# a cloud-hosted BACKLOT before real IBM watsonx.data access is wired up.
# Once IBM access is available, point the main deploy's MCP_SERVER_URL at
# IBM's endpoint instead and retire this service.
#
# Requires local `docker` (this Dockerfile has a non-default name, and a
# plain `gcloud run deploy --source=.` only ever looks for ./Dockerfile).
# Untested against a live project — verify before a real deploy.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
: "${REGION:?Set REGION, e.g. us-central1}"
SERVICE_NAME="${SERVICE_NAME:-backlot-mcp-shim}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/backlot/mcp-shim:latest"

docker build -f Dockerfile.mcp_shim -t "$IMAGE" .
docker push "$IMAGE"

gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --allow-unauthenticated

# WARNING: mcp_shim does not itself check MCP_AUTH_TOKEN server-side (see
# backlot/mcp_shim/server.py) — it's a placeholder the *client* sends,
# meant for the real IBM server, which presumably validates it on IBM's
# side. --allow-unauthenticated here means this deployment is reachable by
# anyone with the URL. Acceptable only because the data behind it is
# fabricated/synthetic (see data/studio_dataset/*.json's "_synthetic"
# flag) — never deploy it this way with anything real behind it. Prefer
# `--no-allow-unauthenticated` plus Cloud Run service-to-service IAM auth
# if you want to lock this down further even for the demo.
#
# Then, on the main deploy: MCP_SERVER_URL=https://<this-service-url>/mcp
# (gcloud prints the service URL after deploy completes).
