#!/usr/bin/env bash
# Deploys the BACKLOT FastAPI backend + web UI (Dockerfile at repo root)
# to Cloud Run. This is the recommended default demo path — it's the one
# deployment that keeps the full human-in-the-loop approval flow (see
# docs/DEPLOYMENT.md).
#
# Flags below verified against the installed `adk`/`gcloud` CLIs where
# available in this environment: `adk deploy cloud_run --help` was checked
# directly (this script deliberately does NOT use that command — see
# docs/DEPLOYMENT.md's "why both exist" table — it deploys the whole custom
# FastAPI app via plain `gcloud run deploy`, not just the bare ADK agent).
# `gcloud` itself was not installed in the environment this was verified
# in, so the `gcloud run deploy` flags below are a careful manual audit
# against gcloud's documented, long-stable surface, not a literal --help
# run — re-run `gcloud run deploy --help` yourself before a live deploy.
# Both Dockerfile and Dockerfile.mcp_shim were build- and run-tested
# locally (confirmed each listens on whatever $PORT is injected, matching
# Cloud Run's contract) — see docs/DEPLOYMENT.md.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
: "${REGION:?Set REGION, e.g. us-central1}"
SERVICE_NAME="${SERVICE_NAME:-backlot}"

# 'shim' (default) or 'clickhouse' — see .env.example and backlot/config.py's
# MCP_MODE. Picks which block below actually gets used.
MCP_MODE="${MCP_MODE:-shim}"

if [ "$MCP_MODE" = "shim" ]; then
  : "${MCP_SERVER_URL:?MCP_MODE=shim requires MCP_SERVER_URL — a deployed mcp_shim's public URL + /mcp (see deploy_mcp_shim.sh)}"
  ENV_VARS="GOOGLE_GENAI_USE_ENTERPRISE=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},BACKLOT_APP_NAME=backlot,MCP_MODE=shim,MCP_SERVER_URL=${MCP_SERVER_URL}"
  # One-time setup, if you haven't already:
  #   gcloud secrets create mcp-auth-token --project="$PROJECT_ID"
  #   echo -n "<the mcp_shim auth token, if any>" | \
  #     gcloud secrets versions add mcp-auth-token --project="$PROJECT_ID" --data-file=-
  SECRETS="MCP_AUTH_TOKEN=mcp-auth-token:latest"
else
  : "${CLICKHOUSE_MCP_URL:?MCP_MODE=clickhouse requires CLICKHOUSE_MCP_URL — your mcp-clickhouse server's streamable-http URL (see deploy_mcp_shim.sh-style deployment, or a managed one)}"
  CLICKHOUSE_DATABASE="${CLICKHOUSE_DATABASE:-backlot_studio}"
  ENV_VARS="GOOGLE_GENAI_USE_ENTERPRISE=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},BACKLOT_APP_NAME=backlot,MCP_MODE=clickhouse,CLICKHOUSE_MCP_URL=${CLICKHOUSE_MCP_URL},CLICKHOUSE_DATABASE=${CLICKHOUSE_DATABASE}"
  # One-time setup, if you haven't already — the mcp-clickhouse server's
  # own auth token (CLICKHOUSE_MCP_AUTH_TOKEN on that server), NEVER a
  # plain env var here (see .env.example's ClickHouse section). This is
  # NOT your ClickHouse Cloud cluster password — that lives only on
  # whoever runs mcp-clickhouse, never on this BACKLOT deployment.
  #   gcloud secrets create clickhouse-mcp-auth-token --project="$PROJECT_ID"
  #   echo -n "<the mcp-clickhouse server's own auth token, if it has one>" | \
  #     gcloud secrets versions add clickhouse-mcp-auth-token --project="$PROJECT_ID" --data-file=-
  SECRETS="CLICKHOUSE_MCP_AUTH_TOKEN=clickhouse-mcp-auth-token:latest"
fi

gcloud run deploy "$SERVICE_NAME" \
  --source=. \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --allow-unauthenticated \
  --set-env-vars="$ENV_VARS" \
  --set-secrets="$SECRETS"

# Notes:
# - GOOGLE_GENAI_USE_ENTERPRISE=TRUE (not the older, deprecated
#   GOOGLE_GENAI_USE_VERTEXAI) routes every LlmAgent through Vertex AI —
#   verified end to end against the installed google-adk 2.5.0 / google-genai
#   source: with no API key reaching the container's env at all (the case
#   here — GOOGLE_API_KEY is never set by this script), there's nothing for
#   any agent to silently fall back to.
# - --allow-unauthenticated is for demo convenience; drop it (and front the
#   service with IAP or a signed-in-only invoker policy) for anything real.
# - The deployed service account needs roles/aiplatform.user (Vertex AI) at
#   minimum; scope it further per backlot/agents/*.py's tool_filter
#   boundaries if you split agents into separate services later.
