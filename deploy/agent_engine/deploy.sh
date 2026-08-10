#!/usr/bin/env bash
# Deploys the auto-approving BACKLOT crew to Vertex AI Agent Engine via the
# ADK CLI. See docs/DEPLOYMENT.md for what this variant is/isn't (no HTTP
# approval relay — see deploy/agent_engine/agent.py's docstring), and for
# why the Cloud Run deployment is the recommended default demo path.
#
# Flags below verified against `adk deploy agent_engine --help` on the
# installed google-adk 2.5.0 — --project/--region/--display_name all match
# current usage exactly (`adk deploy agent_engine [OPTIONS] AGENT`).
# Untested against a live project (no GCP billing available while writing
# this) — re-run `adk deploy agent_engine --help` yourself before a real
# deploy in case a newer CLI version changed something. Run from the repo
# root with the venv activated and `pip install -e .` already done.
#
# IMPORTANT — env vars/credentials: this command has no Cloud-Run-style
# --set-env-vars/--set-secrets flags. Verified in the installed CLI's own
# source (google.adk.cli.cli_deploy.to_agent_engine): if you don't pass
# --env_file (a separate, deprecated-but-still-functional flag this script
# does NOT use), it automatically looks for and reads a plain dotenv file
# at deploy/agent_engine/.env and ships every key in it as a real env var
# on the deployed Reasoning Engine (GOOGLE_CLOUD_PROJECT/
# GOOGLE_CLOUD_LOCATION are handled specially and yield to --project/
# --region above; everything else — GOOGLE_GENAI_USE_ENTERPRISE, MCP_MODE,
# MCP_SERVER_URL/MCP_AUTH_TOKEN or the CLICKHOUSE_* vars, model routing —
# passes straight through). Before running this script:
#   cp .env.example deploy/agent_engine/.env
#   # then fill it in with real production values (never commit it —
#   # deploy/agent_engine/.env matches this repo's .gitignore .env rule).
# Without that file, the deployed agent has no Gemini/MCP credentials at
# all and every LlmAgent call will fail at runtime.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
: "${REGION:?Set REGION, e.g. us-central1}"

if [ ! -f "deploy/agent_engine/.env" ]; then
  echo "WARNING: deploy/agent_engine/.env not found — the deployed agent" >&2
  echo "will have no Gemini/MCP credentials. See this script's header comment." >&2
fi

adk deploy agent_engine \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --display_name=backlot \
  deploy/agent_engine
