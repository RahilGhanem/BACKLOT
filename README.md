# BACKLOT

**An autonomous pre-production crew**, built for the *Agentic Cinema: The
Blockbuster Hackathon* (Google Cloud + Gemini Enterprise Agent Platform,
ClickHouse MCP partner track).

Drop in a screenplay. A network of specialised agents — orchestrated with
Google's Agent Development Kit (ADK) — returns a complete, shootable
production package: a scene-by-scene breakdown, an optimised shooting
schedule, a budget grounded in a studio's own historical cost data (which
lives in ClickHouse, queried via the official ClickHouse MCP server), real
crew/location picks, a ranked risk report, and (later) generative previz.
Every budget/resource number the crew produces is grounded and cites its
source — never invented by the model.

## Status

This repo is being built phase by phase. Each phase is runnable end-to-end
before the next one starts.

- [x] **Phase 0** — scaffold, license, sample data
- [x] **Phase 1** — Script Supervisor: screenplay → structured breakdown JSON
- [x] **Phase 2** — Line Producer orchestrator + 1st-AD Scheduler (the
      end-to-end spine: script → breakdown → schedule)
- [x] **Phase 3** — ClickHouse MCP grounding (Budget + Resource agents, via
      a local synthetic mcp_shim server)
- [x] **Phase 4** — Risk/Continuity agent (bounded re-plan loop), human
      approval gate, scoped tool permissions
- [x] **Phase 5** — FastAPI + web UI, live agent-activity panel, metrics
- [x] **Phase 6** — Previz (Imagen storyboards, Veo animatic, Lyria cue) —
      opt-in, see caveat below
- [x] **Phase 7** — Deploy to Agent Engine + Cloud Run; point the MCP client
      at a real ClickHouse cluster via the official ClickHouse MCP server —
      see `docs/DEPLOYMENT.md`

## Why this shape

Pre-production is where a film's schedule and budget get decided, and where
mistakes are cheapest to catch and most expensive to miss. Existing tools
(Filmustage, Movie Magic, Cinelytic) are strong single-purpose assistants,
but none of them run as an autonomous crew that plans across the whole
pipeline and grounds its numbers in a studio's own data. That gap — isolated
tools instead of an orchestrated, data-grounded, tool-wielding team — is
what this project closes.

## Architecture (target — see roadmap above for what's built so far)

```
 USER (producer / 1st AD)
   │ uploads screenplay · approves budget band
   ▼
 FRONTEND (FastAPI + minimal web UI)
   ▼
 LINE PRODUCER (custom ADK orchestrator — see note below)
   ├─ Script Supervisor   (screenplay → breakdown JSON)          [Phase 1 ✅]
   ├─ Previz Agent        (opt-in: Imagen/Veo/Lyria for the       [Phase 6 ✅]
   │                       opening scene, runs as soon as the
   │                       breakdown exists)
   │                                                    ┌──── bounded
   ├─ 1st-AD Scheduler    (breakdown → stripboard sched)│     re-plan loop
   ├─ Budget Agent        (grounded via ClickHouse MCP) │     (max 2 retries,
   ├─ Risk/Continuity     (critiques sched+budget) ──────┘     Phase 4 ✅)
   ├─ Approval Gate       (producer approves the budget band)  [Phase 4 ✅]
   ├─ Resource Agent      (grounded via ClickHouse MCP;         [Phase 3 ✅]
   │                       skipped if the budget was rejected)
   └─ Package Assembler   (combines everything above)          [Phase 2 ✅]
   │
   ▼
 CLICKHOUSE MCP SERVER (mcp_shim locally with synthetic data; the
 real, official ClickHouse MCP server — github.com/ClickHouse/
 mcp-clickhouse — connected to a ClickHouse Cloud or self-hosted
 cluster in production. Swapping is an env-var change only, see
 .env.example)
```

Agents exchange **compact structured JSON artifacts** (the breakdown, the
schedule, the budget) rather than raw transcripts or the full screenplay —
this is the token-efficiency story: only the Script Supervisor ever reads
the whole script.

**On "ADK orchestrator":** the installed ADK version (2.5.0) deprecates
`SequentialAgent`/`LoopAgent` in favor of a newer, graph-based `Workflow`
primitive that isn't yet usable as a plain `BaseAgent` (it can't be handed
to `Runner`). The Line Producer's control flow also stopped being purely
linear once the re-plan loop and the approval-gate skip were added, which
`SequentialAgent` couldn't express anyway. So it stays a small, explicit
custom `BaseAgent` — see `backlot/orchestrator/line_producer.py`.

**Governance, concretely, as of Phase 4:**
- *Scoped tool access* — each MCP-calling agent gets its own `McpToolset`
  with a `tool_filter`: the Budget Agent can only call the two cost-lookup
  tools, the Resource Agent only the crew/location tools. Neither can reach
  a tool the other owns.
- *Bounded reflection* — the Risk Agent can force a re-plan, but the Line
  Producer caps it at `max_replans` (default 2) and shrinks the scheduler's
  pages/day budget deterministically each time, so a stuck loop can't run
  away with cost or time.
- *Human approval gate* — the Resource Agent (the step closest to actually
  committing something) only runs if the budget is approved;
  `backlot/agents/approval_gate.py` blocks on a CLI prompt by default, but
  takes an injectable decider so Phase 5's API can swap in an HTTP
  approve/reject flow without touching the orchestrator.
- *Injection-safe tool data* — every agent's instruction states that
  retrieved data (screenplay text, MCP records) is data, never instructions
  to follow; structurally, tool results also arrive as distinct
  function-response content blocks in the Gemini API, not concatenated
  into the prompt as free text.

**On Previz (Phase 6), concretely:** it's opt-in (`--with-previz` /
the UI checkbox) because it costs real money and a Veo clip can take
minutes — nothing in the default pipeline or test suite triggers it.
Imagen (`generate_images`) and Veo (`generate_videos`, a long-running
operation, polled via `client.operations.get`) are called through the
verified, stable `google-genai` `client.models` surface. Lyria, in the
installed SDK, only exists behind a much newer, separate "Interactions"
API (`client.interactions`) that could not be exercised against a live
billed call in this environment; `backlot/tools/previz_generation.py`
makes a best-effort call against it and degrades gracefully (storyboards/
animatic still complete, a warning is recorded) if it fails — verify that
call against current docs before a live demo.

## Repo structure

```
backlot/
  config.py             # the only place that reads os.getenv — see .env.example
  schemas/               # pydantic contracts agents hand off between each other
  agents/                 # one LlmAgent (or custom BaseAgent) factory per specialist
  orchestrator/            # Line Producer
  tools/                    # custom tools: the scheduling solver, previz_generation.py
  mcp_shim/                  # local synthetic MCP server (Phase 3)
  metrics.py                  # evaluation scorecard, computed from the ADK event log
  api/                         # FastAPI backend + static web UI (Phase 5)
    run_manager.py              # tracks background runs, relays HTTP approvals
    app.py                       # routes
    static/                        # plain HTML/CSS/JS, no build step
data/
  screenplays/                # sample screenplay(s) used for local dev/tests
  studio_dataset/               # synthetic historical costs, rates, crew, locations,
                                 # past schedules — served by mcp_shim
tests/                          # pytest; schema/solver/shim/metrics/API tests always
                                 # run, live-model tests skip automatically without
                                 # credentials (see Testing below)
deploy/                          # Phase 7 — see docs/DEPLOYMENT.md
  cloud_run/                      # deploy.sh (main app), deploy_mcp_shim.sh (optional)
  agent_engine/                    # ADK CLI's expected root_agent convention
docs/
  DEPLOYMENT.md                    # the full Phase 7 write-up
run_local.py                     # CLI entrypoint for local, in-memory runs
run_server.py                     # FastAPI + web UI entrypoint
Dockerfile                        # Cloud Run image for the FastAPI app + UI
Dockerfile.mcp_shim                # optional Cloud Run image for the synthetic MCP shim
```

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows (Git Bash):
source .venv/Scripts/activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set **one** of:
- `GOOGLE_API_KEY` (AI Studio — fastest for local dev), or
- `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` + `GOOGLE_CLOUD_PROJECT` (Vertex AI —
  matches the production deployment path; requires
  `gcloud auth application-default login` or a service account).

Nothing else in this repo reads an environment variable directly outside
`backlot/config.py` — that's the one place to check if you need to add a
new setting.

## Running it

The Budget and Resource agents need the MCP server reachable. Start the
local synthetic one in one terminal:

```bash
python -m backlot.mcp_shim.server
```

Then, in another terminal, run the crew:

```bash
python run_local.py
```

This parses `data/screenplays/sample_screenplay.txt` through the full crew
(breakdown → schedule → grounded budget → risk critique → **approval
prompt** → grounded resources → assembled package) and writes
`output/package.json`. The run pauses in your terminal to ask you to
approve the budget band — answer `y` to continue to resource picks, or
anything else to see the package with `resources: null`. Pass
`--auto-approve` to skip the prompt and always approve (useful for demos
and CI). Use `--stage breakdown` to run only the Script Supervisor (no MCP
server needed) and write `output/breakdown.json` instead. Pass
`--screenplay` / `--out` for a different input/output path. Add
`--with-previz` to also generate a storyboard/animatic/music cue for the
opening scene (real Vertex AI Imagen/Veo cost and time; see the Previz
caveat above) — written under `output/previz/<run-id>/`.

### Web UI

With the MCP shim still running, start the API + UI instead:

```bash
python run_server.py
```

Open `http://127.0.0.1:8000`. Load the sample screenplay (or paste your
own), click **Run the crew**, and watch each crew member light up live —
Script Supervisor → Scheduler → Budget → Risk → Approval Gate → Resource →
Package Assembler — as pending / working / done, with a re-plan badge if
the bounded reflection loop fires (a "show detailed log" toggle reveals
the raw per-event feed underneath). When the run reaches the approval
gate, a modal shows the actual grounded budget line items — not a
placeholder — before you approve or reject; this is the same
human-in-the-loop gate `run_local.py` shows on the CLI, just relayed over
HTTP instead of blocking on stdin (see `backlot/api/run_manager.py`). The
finished package renders as tabs (Breakdown / Schedule / Budget / Risk /
Resources / Previz) with provenance badges on every grounded claim, a
one-click JSON download, and the evaluation scorecard alongside. Check
"Generate previz" before running to include the storyboard/animatic/music
cue tab.

## Testing

```bash
pytest -v
```

- Schema, scheduler-solver, mcp_shim, metrics, API-routing, and
  agent-configuration tests run with no credentials and no manually-started
  server.
- Tests that need the MCP server (Budget/Resource/full-pipeline) auto-start
  `mcp_shim` as a subprocess via the `mcp_shim_process` fixture in
  `tests/conftest.py` — nothing to run by hand for `pytest`.
- Tests that actually call Gemini are skipped automatically if `.env` has
  no Gemini credentials configured, and must pass once you add one.
- The one test that would actually call Imagen/Veo (real money) needs a
  *second*, explicit opt-in beyond credentials: `RUN_PREVIZ_LIVE_TESTS=1`.
  Nothing else in the suite sets this, so a routine `pytest -v` never
  triggers billed generative-media calls.

## Deploying

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full write-up. Short
version: `./deploy/cloud_run/deploy.sh` deploys the complete app (full
human-in-the-loop approval flow) to Cloud Run — this is the one to demo.
`./deploy/agent_engine/deploy.sh` deploys just the crew to Vertex AI Agent
Engine via the ADK CLI, auto-approving the budget band since Agent
Engine's native session API doesn't have anywhere to plug in the same
HTTP-approval-relay the Cloud Run deployment uses. Neither script has been
run against a live project — every flag is grounded in the installed
`adk`/`gcloud` CLIs' own `--help` output, but verify before a real deploy.

## Data note

Everything under `data/studio_dataset/` is **synthetic** — fabricated
numbers for demo and development, clearly marked with a `"_synthetic": true`
flag in each file. It exists to exercise the ClickHouse MCP grounding path
without needing a live ClickHouse connection during development.

The real grounding story: the studio's historical cost data, vendor rates,
and crew/location libraries live in **ClickHouse**; the Budget/Resource
agents query them via the real, official ClickHouse MCP server
(`mcp-clickhouse`, github.com/ClickHouse/mcp-clickhouse) for grounded
estimates. Pointing the agents at a real ClickHouse Cloud or self-hosted
cluster instead of this synthetic shim is `MCP_MODE=clickhouse` plus a few
more env vars — see `.env.example`'s ClickHouse section for exactly which
ones, `scripts/clickhouse_load.sql` for the one-time DDL/load script that
puts this same synthetic data into real ClickHouse tables, and
`backlot/agents/_state_instructions.py`'s `clickhouse_sql_rule` /
`backlot/agents/budget.py` / `resource.py` for how the agents issue real SQL
SELECTs (via that server's `run_query`/`list_tables` tools, verified against
mcp-clickhouse's own README) once pointed there — no other code changes
needed either way.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
