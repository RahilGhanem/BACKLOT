# Deployment (Phase 7)

This covers moving BACKLOT from "runs on my machine" to Google Cloud, and
pointing the MCP client at the real IBM watsonx.data remote MCP server
instead of the local synthetic `mcp_shim`.

**Important caveat up front:** none of this has been executed against a
live GCP project or a real IBM MCP endpoint — there was no billing-enabled
project or IBM credential available while writing it. Every command below
is grounded in verified tooling (the exact `adk deploy` / `gcloud run
deploy` flags were checked against the installed CLIs' own `--help`
output, not guessed), but treat this as a solid starting point to verify
and adjust against current docs before a real deploy, not a "definitely
already works" script.

## Two deployment paths, and why both exist

| | Cloud Run (`deploy/cloud_run/`) | Agent Engine (`deploy/agent_engine/`) |
|---|---|---|
| What's deployed | The whole `backlot/api/app.py` FastAPI app (Dockerfile at repo root) | Just the `LineProducer` agent, via `adk deploy agent_engine` |
| Human approval gate | Full — the web UI's Approve/Reject buttons work exactly as they do locally (`backlot/api/run_manager.py`'s HTTP-relayed async decider) | Auto-approved (`auto_approve_decider`) — Agent Engine's native session/query API is stateless request/response and doesn't have anywhere to plug in the same HTTP-relay wait |
| Recommended for | **The demo** — this is the full product experience | Showing the crew running on Google's own managed agent runtime specifically, per the hackathon brief's "hosted on Agent Engine" |

Run the Cloud Run deploy for anything you actually want to demo end to
end; the Agent Engine deploy is there to demonstrate that same crew
running on the platform's managed runtime too, with the one documented
simplification above.

## Prerequisites

- A GCP project with billing enabled and the Vertex AI, Cloud Run, Secret
  Manager, and Cloud Build APIs enabled.
- `gcloud` CLI, authenticated (`gcloud auth login`) and configured
  (`gcloud config set project $PROJECT_ID`).
- This repo's dependencies installed locally (`pip install -r
  requirements.txt`), so both the `adk` CLI and `gcloud` are available and
  `backlot` is importable (`pip install -e .` — see README's Setup).

## Cloud Run — the main deployment

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export MCP_SERVER_URL=https://mcp-shim-xyz-uc.a.run.app/mcp  # or IBM's real endpoint
./deploy/cloud_run/deploy.sh
```

See `deploy/cloud_run/deploy.sh` for the full `gcloud run deploy`
invocation and its comments. It builds from the repo-root `Dockerfile`
(Cloud Build via `--source=.`) and wires:

- `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`,
  `GOOGLE_CLOUD_LOCATION` — Gemini calls go through Vertex AI in
  production rather than an AI Studio API key.
- `MCP_SERVER_URL` as a plain env var (it's not a secret — just an
  endpoint).
- `MCP_AUTH_TOKEN` from Secret Manager (`--set-secrets`), never as a plain
  env var. Create the secret once first:

  ```bash
  gcloud secrets create mcp-auth-token --project="$PROJECT_ID"
  echo -n "<the real IBM MCP credential>" | \
    gcloud secrets versions add mcp-auth-token --project="$PROJECT_ID" --data-file=-
  ```

The deployed service account needs at least `roles/aiplatform.user`. If
you later split Budget/Resource into separately-deployed services, scope
each service account's IAM roles to match its `tool_filter` boundary
(`backlot/agents/_mcp.py`) — the same least-privilege story Phase 4
already applies at the MCP-tool level, extended to infrastructure
identity.

## mcp_shim in the cloud (optional, until real IBM access is wired up)

If you want the grounded Budget/Resource agents to work in a cloud demo
*before* IBM watsonx.data access is available, deploy the synthetic shim
too:

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
./deploy/cloud_run/deploy_mcp_shim.sh
```

Read the warning comment in that script first — it deploys
`--allow-unauthenticated`, which is only acceptable because the data
behind it is fabricated (`data/studio_dataset/*.json`'s `"_synthetic"`
flag), never for anything real. Once real IBM access exists, point the
main deploy's `MCP_SERVER_URL` at IBM's endpoint instead and delete this
service — no code changes either way, per the whole point of `mcp_shim`
matching IBM's tool interface (`backlot/mcp_shim/server.py`).

## Agent Engine — the platform-native path

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
./deploy/agent_engine/deploy.sh
```

This wraps `adk deploy agent_engine --project=$PROJECT_ID
--region=$REGION --display_name=backlot deploy/agent_engine`.
`deploy/agent_engine/agent.py` exposes the `root_agent` ADK's CLI expects
(verified by running `adk create` on a scratch folder and matching its
generated convention: an `__init__.py` importing an `agent.py` with a
module-level `root_agent`), built with `auto_approve_decider` for the
reason in the table above.

## Switching MCP_SERVER_URL to the real IBM watsonx.data server

This is deliberately just an environment change, everywhere:

1. Get the real endpoint URL and a credential from IBM watsonx.data /
   watsonx Orchestrate / ContextForge MCP Gateway (whichever IBM surface
   you're integrating with — see README's Phase 3 notes and
   `backlot/mcp_shim/server.py`'s tool signatures, which the real server
   needs to match).
2. Store the credential in Secret Manager (see the `mcp-auth-token`
   snippet above) — never in `.env` committed anywhere, never as a plain
   Cloud Run env var.
3. Set `MCP_SERVER_URL` to IBM's endpoint on whichever deployment(s) you
   run.
4. Retire `mcp_shim` (stop pointing anything at it; delete the Cloud Run
   service if you deployed one).

Nothing in `backlot/agents/budget.py`, `backlot/agents/resource.py`, or
`backlot/agents/_mcp.py` changes — they only ever know about
`settings.mcp_server_url` / `settings.mcp_auth_token`.

## Cost note

Mirroring the research report's own cost note: Agent Engine bills roughly
per vCPU-hour and GB-hour of memory plus session events; Cloud Run bills
per request/CPU-time and scales to zero when idle; Gemini calls bill per
token (Flash is the cheap/high-volume tier, Pro is reserved for
Script Supervisor and Risk/Continuity — see `backlot/config.py`'s model
routing); Imagen/Veo/Lyria (Phase 6, opt-in) are billed per generation and
are the most expensive part of a run by far, which is exactly why they're
gated behind `--with-previz` / the UI checkbox rather than running by
default. New GCP accounts get free-trial credit, which should comfortably
cover hackathon-scale demo traffic.
