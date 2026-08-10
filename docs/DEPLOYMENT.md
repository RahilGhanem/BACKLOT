# Deployment (Phase 7)

This covers moving BACKLOT from "runs on my machine" to Google Cloud, and
pointing the MCP client at the real, official ClickHouse MCP server
(`mcp-clickhouse`) connected to a ClickHouse Cloud or self-hosted cluster,
instead of the local synthetic `mcp_shim`.

**Important caveat up front:** none of this has been executed against a
live GCP project or a real ClickHouse cluster — there was no billing-enabled
project or ClickHouse credential available while writing it. What COULD be
verified locally, was: both Dockerfiles build and their containers
correctly bind to whatever `$PORT` is injected (`docker build`/`docker
run`, not just read), the `adk deploy agent_engine`/`adk deploy cloud_run`
flags were checked against the installed `adk` 2.5.0 CLI's own `--help`
output (not guessed), and the Vertex/Enterprise routing claims above were
traced through the installed `google-adk`/`google-genai` source, not
assumed. `gcloud` itself was not installed in the environment this was
written in, so the `gcloud run deploy` flags are a careful manual audit
against gcloud's long-stable, well-documented surface rather than a literal
`--help` run — re-verify with `gcloud run deploy --help` yourself before a
real deploy, same as always for anything this hasn't been run against.

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

Shim mode (default — the local synthetic dataset, deployed alongside so
the cloud demo works before a real ClickHouse cluster is set up):

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export MCP_SERVER_URL=https://mcp-shim-xyz-uc.a.run.app/mcp  # a deployed mcp_shim's URL, see below
./deploy/cloud_run/deploy.sh
```

Real ClickHouse mode, once you've created the cluster, run
`scripts/clickhouse_load.sql`, and have a real mcp-clickhouse endpoint
reachable:

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export MCP_MODE=clickhouse
export CLICKHOUSE_MCP_URL=https://your-mcp-clickhouse-endpoint/mcp
export CLICKHOUSE_DATABASE=backlot_studio
./deploy/cloud_run/deploy.sh
```

(the mcp-clickhouse server's own `CLICKHOUSE_MCP_AUTH_TOKEN` value should
already be seeded into Secret Manager per the snippet below before you run
this — this script reads it from there, it isn't passed as a plain env var)

See `deploy/cloud_run/deploy.sh` for the full `gcloud run deploy`
invocation and its comments (its `MCP_MODE` branch picks between the two
examples above). It builds from the repo-root `Dockerfile` (Cloud Build via
`--source=.`) and wires:

- `GOOGLE_GENAI_USE_ENTERPRISE=TRUE`, `GOOGLE_CLOUD_PROJECT`,
  `GOOGLE_CLOUD_LOCATION` — Gemini calls go through Vertex AI in
  production rather than an AI Studio API key. Verified end to end against
  the installed google-adk 2.5.0 / google-genai source
  (`google.genai._api_client.BaseApiClient.__init__`): with no
  `GOOGLE_API_KEY` reaching the container's environment at all (true here
  — this script never sets one), there is nothing for any agent to
  silently fall back to; and even if one were present, the client library
  prioritizes `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` over a
  leftover API key once Enterprise mode is on.
- `MCP_SERVER_URL` (shim mode) or `CLICKHOUSE_MCP_URL`/
  `CLICKHOUSE_DATABASE` (clickhouse mode) as plain env vars — none of
  these are secrets, just endpoints/identifiers.
- The one real secret — `MCP_AUTH_TOKEN` (shim mode) or
  `CLICKHOUSE_MCP_AUTH_TOKEN` (clickhouse mode, must match whatever the
  mcp-clickhouse server itself was started with) — from Secret Manager
  (`--set-secrets`), never as a plain env var. Create it once first:

  ```bash
  # shim mode:
  gcloud secrets create mcp-auth-token --project="$PROJECT_ID"
  echo -n "<the mcp_shim auth token, if any>" | \
    gcloud secrets versions add mcp-auth-token --project="$PROJECT_ID" --data-file=-

  # clickhouse mode:
  gcloud secrets create clickhouse-mcp-auth-token --project="$PROJECT_ID"
  echo -n "<the mcp-clickhouse server's own auth token>" | \
    gcloud secrets versions add clickhouse-mcp-auth-token --project="$PROJECT_ID" --data-file=-
  ```

  Note this is the **MCP server's** auth token, not your ClickHouse
  Cloud cluster password — that (`CLICKHOUSE_HOST`/`PORT`/`USER`/
  `PASSWORD`) is configured only on whoever runs the mcp-clickhouse
  process, never on this BACKLOT deployment.

The deployed service account needs at least `roles/aiplatform.user`. If
you later split Budget/Resource into separately-deployed services, scope
each service account's IAM roles to match its `tool_filter` boundary
(`backlot/agents/_mcp.py`) — the same least-privilege story Phase 4
already applies at the MCP-tool level, extended to infrastructure
identity.

Build/runtime were verified locally (not just read): `docker build` on both
`Dockerfile` and `Dockerfile.mcp_shim` succeeds, and running each image
with an arbitrary `PORT` confirms the process actually binds to it — the
exact contract Cloud Run relies on.

## mcp_shim in the cloud (optional, until a real ClickHouse cluster is wired up)

If you want the grounded Budget/Resource agents to work in a cloud demo
*before* real ClickHouse access is available, deploy the synthetic shim
too:

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
./deploy/cloud_run/deploy_mcp_shim.sh
```

Read the warning comment in that script first — it deploys
`--allow-unauthenticated`, which is only acceptable because the data
behind it is fabricated (`data/studio_dataset/*.json`'s `"_synthetic"`
flag), never for anything real. Once a real ClickHouse cluster +
mcp-clickhouse server exist, set `MCP_MODE=clickhouse` and point the main
deploy's `CLICKHOUSE_MCP_URL` at that server instead and delete this shim
service — no BACKLOT code changes either way (only which mode's env vars
are set), per `backlot/mcp_shim/server.py`'s module docstring.

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

**Credentials for this path work differently than Cloud Run.** `adk deploy
agent_engine` has no `--set-env-vars`/`--set-secrets` flags — verified
directly in the installed CLI's source
(`google.adk.cli.cli_deploy.to_agent_engine`): unless you pass `--env_file`
explicitly (a separate, deprecated flag this repo's script doesn't use),
it automatically looks for and reads a plain dotenv file at
`deploy/agent_engine/.env` and ships every key in it as a real env var on
the deployed Reasoning Engine. `GOOGLE_CLOUD_PROJECT`/
`GOOGLE_CLOUD_LOCATION` are handled specially there and yield to this
script's `--project`/`--region` flags; everything else (
`GOOGLE_GENAI_USE_ENTERPRISE`, `MCP_MODE`, `MCP_SERVER_URL`/
`MCP_AUTH_TOKEN` or the `CLICKHOUSE_*` vars, model routing) passes
through untouched. So before running `deploy/agent_engine/deploy.sh`:

```bash
cp .env.example deploy/agent_engine/.env
# then fill deploy/agent_engine/.env in with real production values —
# never commit it (it matches this repo's .gitignore ".env" rule already)
```

Skip this and the deployed agent has no Gemini/MCP credentials at all —
`deploy/agent_engine/deploy.sh` prints a warning if the file is missing,
but still proceeds (deploying a crew that will fail on its first LLM call
is still sometimes useful to confirm the deploy mechanics themselves work).

## Switching to a real ClickHouse cluster (MCP_MODE=clickhouse)

Selected by `MCP_MODE=clickhouse` (default is `MCP_MODE=shim`) — see
`.env.example`'s ClickHouse section for the full list of variables and
`backlot/config.py`'s `_resolve_mcp_mode()`. Steps:

1. Create a ClickHouse Cloud cluster (or point at a self-hosted one), note
   its host, port, a user + password (ideally a read-only user), and pick a
   database name (default `backlot_studio`, matching `CLICKHOUSE_DATABASE`).
2. Run `scripts/clickhouse_load.sql` once (by hand, e.g. via the
   ClickHouse Cloud SQL console, or `clickhouse-client --multiquery <
   scripts/clickhouse_load.sql`) against that cluster — it creates and
   populates `historical_costs`, `vendor_rates`, `crew_library`,
   `location_library`, and `past_schedules` tables from the same synthetic
   data mcp_shim serves locally, and prints a row-count sanity check.
3. Run the real, official ClickHouse MCP server
   (github.com/ClickHouse/mcp-clickhouse) somewhere reachable over
   streamable HTTP, pointed at that cluster — e.g. `uvx --from
   mcp-clickhouse mcp-clickhouse --transport http` deployed to Cloud Run
   the same way `deploy_mcp_shim.sh` deploys the synthetic shim today, with
   its own `CLICKHOUSE_HOST`/`PORT`/`USER`/`PASSWORD`/`SECURE`/`DATABASE`
   and `CLICKHOUSE_MCP_AUTH_TOKEN` env vars set server-side (see
   `.env.example`'s "reference only" block for the full list). Tool names
   (`run_query`, `list_tables`) verified against that repo's own README —
   not guessed.
4. Store that server's `CLICKHOUSE_MCP_AUTH_TOKEN` value in Secret Manager
   (see the `clickhouse-mcp-auth-token` snippet above) — never in `.env`
   committed anywhere, never as a plain Cloud Run env var. Your ClickHouse
   Cloud password never leaves the mcp-clickhouse process's own
   environment; it never reaches this BACKLOT deployment.
5. Set `MCP_MODE=clickhouse` plus `CLICKHOUSE_MCP_URL`/
   `CLICKHOUSE_MCP_AUTH_TOKEN`/`CLICKHOUSE_DATABASE` on whichever
   deployment(s) you run (Cloud Run: this script's clickhouse-mode example
   above; Agent Engine: in `deploy/agent_engine/.env`, per above).
6. Retire `mcp_shim` (stop pointing anything at it; delete the Cloud Run
   service if you deployed one).

Nothing in `backlot/agents/budget.py`, `backlot/agents/resource.py`, or
`backlot/agents/_mcp.py`'s connection wiring changes structurally — they
still only ever know about `settings.mcp_server_url` /
`settings.mcp_auth_token`; `MCP_MODE` just picks which tool names/SQL
instructions the agents are built with (real ClickHouse SQL tools vs.
mcp_shim's fuzzy-matched tools) and which env vars those two settings
resolve from.

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
