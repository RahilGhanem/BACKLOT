#!/usr/bin/env bash
# Deploys the auto-approving BACKLOT crew to Vertex AI Agent Engine via the
# ADK CLI. See docs/DEPLOYMENT.md for what this variant is/isn't (no HTTP
# approval relay — see deploy/agent_engine/agent.py's docstring), and for
# why the Cloud Run deployment is the recommended default demo path.
#
# Untested against a live project (no GCP billing available while writing
# this) — verify against `adk deploy agent_engine --help` and current docs
# before a real deploy. Run from the repo root with the venv activated and
# `pip install -e .` already done.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
: "${REGION:?Set REGION, e.g. us-central1}"

adk deploy agent_engine \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --display_name=backlot \
  deploy/agent_engine
