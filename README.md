# BACKLOT

An autonomous pre-production crew for film.

BACKLOT takes a screenplay and returns a production package: a scene
breakdown, a shooting schedule, a costed budget, a risk report, crew and
location picks, and the producer's approval decision. Seven specialised
agents do the work, coordinated by a Line Producer that holds shared state
and enforces the order they run in.

The budget and resource agents don't estimate from the model's priors. They
query the studio's own cost history in ClickHouse through the official MCP
server, and every figure they return carries the row it came from. Values
they couldn't match to a record are marked ungrounded rather than filled in.

---

## Why BACKLOT

Pre-production decides a film's schedule and budget, and it's the cheapest
place to catch a mistake. A 1st AD packs scenes into shoot days. A line
producer costs those days against what comparable productions actually
spent. Somebody has to notice that four consecutive night exteriors will
exhaust the crew before the schedule gets locked.

Tools exist for each of those jobs individually. What doesn't exist is a
system that runs the whole sequence, checks its own output, and costs the
plan against the studio's real numbers instead of a plausible guess.

## The production spine

```
                SCREENPLAY
                    │
             SCRIPT BREAKDOWN
                    │
                 SCHEDULE ◀────────────┐
                    │                  │
                  BUDGET ──────────┐   │  bounded
                    │              │   │  re-plan
                   RISK ───────────┴───┘  (max 2)
                    │
             HUMAN APPROVAL          ← execution stops here
                    │
                RESOURCES
                    │
            PRODUCTION PACKAGE
```

Budget and Resources are the two grounded steps. Both read the studio
dataset in ClickHouse over MCP and carry the source record forward with the
value.

## Design notes

Four things distinguish this from a linear agent chain:

**Adversarial review.** The Risk agent reads the Scheduler's and Budget
agent's output and can reject the plan. It isn't a summariser at the end of
the pipeline; its verdict changes what happens next.

**A real second planning pass.** A rejection returns the plan to the
Scheduler with a widened pages-per-day target, then re-costs and re-reviews
it. The loop is capped and the constraint change is deterministic.

**A blocking human decision.** The Resource agent proposes actual crew and
locations, so it doesn't run until a producer approves the budget band.
Rejection ends the run with `resources: null`.

**Traceable numbers.** Grounded values carry a `source_records` entry naming
the table and row behind them, and the UI walks that back from a decision to
the agent, the tool, the dataset and the record.

## Architecture

```
 Producer (web UI)
   │  uploads screenplay · approves the budget band
   ▼
 FastAPI + web UI          backlot/api/
   ▼
 Line Producer             backlot/orchestrator/line_producer.py
   ├─ Script Supervisor    screenplay → structured breakdown
   ├─ 1st-AD Scheduler     breakdown → stripboard (deterministic solver)
   ├─ Budget Agent         grounded via ClickHouse MCP
   ├─ Risk / Continuity    critiques schedule + budget, may force a re-plan
   ├─ Approval Gate        producer decision, blocks the pipeline
   ├─ Resource Agent       grounded via ClickHouse MCP
   └─ Package Assembler    assembles the final package
   ▼
 mcp-clickhouse (official MCP server) ──▶ ClickHouse
```

Agents hand each other compact JSON artifacts rather than transcripts. Only
the Script Supervisor ever sees the full screenplay, which keeps the token
cost of a run roughly flat as the script gets longer.

The Line Producer is a custom ADK `BaseAgent` rather than a
`SequentialAgent`, because the control flow isn't linear: it needs a capped
retry loop around Scheduler/Budget/Risk, a conditional skip of the Resource
agent when a budget is rejected, and an optional previz step.

## The agents

| Agent | Role | Grounded |
|---|---|---|
| **Script Supervisor** | Parses the screenplay into scenes: slugline, INT/EXT, time of day, cast, props, vehicles, VFX, stunts, page count | — |
| **1st-AD Scheduler** | Packs scenes into shoot days by location and continuity. A solver, not a model | — |
| **Budget Agent** | Costs each shoot day and vendor line against historical studio data | ClickHouse |
| **Risk / Continuity** | Reviews the plan for weather, permit, overtime, continuity and feasibility problems; can demand a re-plan | — |
| **Approval Gate** | Presents the costed budget to a human and waits | — |
| **Resource Agent** | Proposes crew and locations from the studio libraries | ClickHouse |
| **Package Assembler** | Combines every artifact into the deliverable | — |

Scheduling is deterministic on purpose. The same breakdown always produces
the same stripboard, which is what lets the re-plan loop detect that a
second pass changed nothing and stop early.

## Grounded studio data

The Budget and Resource agents issue SQL against the studio's tables through
the official [mcp-clickhouse](https://github.com/ClickHouse/mcp-clickhouse)
server:

| Table | Contents |
|---|---|
| `historical_costs` | Day rates by scene profile from comparable productions |
| `vendor_rates` | Camera, grip/electric, catering, picture vehicles, FX, security |
| `crew_library` | Crew with day rate, union, region and availability |
| `location_library` | Locations with permit cost, night-shoot support, power access |
| `past_schedules` | Realised pages/day from previous productions |

Each agent is scoped to two tools, `run_query` and `list_tables`, through a
`tool_filter`. Neither can reach anything else on the server.

A grounded value looks like this in the package:

```json
{
  "label": "Shoot Day 1: EXT. INDUSTRIAL LOT - NIGHT (Scene 1)",
  "amount": 38500.0,
  "grounded": true,
  "source_records": [{
    "record_id": "EXT_NIGHT_INDUSTRIAL",
    "summary": "Historical average cost of $38,500/day based on 6 comparable productions.",
    "source": "clickhouse:backlot_studio.historical_costs"
  }]
}
```

When no row matches, `grounded` is `false` and `source_records` is empty.
The UI lists those separately instead of burying them.

## Human-in-the-loop

The Approval Gate sits between costing and commitment. Everything before it
is analysis; the Resource agent after it proposes real crew and locations,
so a producer approves the budget band first.

The gate takes an injectable decider. On the CLI it blocks on stdin; in the
web UI it blocks until an HTTP approve or reject arrives. The orchestrator
doesn't know or care which.

## Re-planning

If the Risk agent judges a schedule infeasible it sets `replan_requested`,
and the schema requires it to justify that with a high-severity flag
carrying both a description and a recommendation. An unjustified re-plan
request fails validation.

The Line Producer then re-runs Scheduler → Budget → Risk with a widened
pages-per-day target. Three things bound the loop: a cap of two re-plans, a
deterministic constraint change on each pass, and a fixed-point check that
stops early if the new schedule matches the previous one.

## The production package

A run produces one JSON document: breakdown, schedule, budget with per-line
provenance, risk report, approval decision, resource picks, and previz if it
was enabled. You can download it from the UI and reopen it later to review a
run without executing the crew again.

The web UI presents this as a control room. A live pipeline shows each agent
station and the value it produced, with the re-plan drawn as an actual loop
back to the Scheduler when one happens. Below that: a stripboard in the
standard 1st-AD colour convention, a shooting board, budget composition, a
risk map linked to the scenes and days each flag affects, and a grounding
ledger naming every claim that couldn't be grounded.

## Screenshots and demo

_Demo video: (add link)_

_Hosted instance: (add link)_

## Technology

- **Gemini** via the **Google Agent Development Kit** (ADK 2.5.0)
- **Model Context Protocol**, using `mcp-clickhouse` 0.6.0
- **ClickHouse** for the studio dataset
- **FastAPI** for the backend and static hosting
- Plain HTML, CSS and JavaScript on the frontend. No framework, no build step
- **Cloud Run** as the container target (`Dockerfile` at the repo root)

## Local development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)
source .venv/bin/activate          # macOS/Linux
pip install -r requirements.txt
cp .env.example .env
```

Set one model credential in `.env`:

- `GOOGLE_API_KEY` for AI Studio, which is quickest for local work, or
- `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` plus `GOOGLE_CLOUD_PROJECT` for Vertex
  AI, which is what the Cloud Run deployment uses. Needs
  `gcloud auth application-default login` or a service account.

`backlot/config.py` is the only module that reads environment variables.

### Running against ClickHouse

`mcp-clickhouse` requires `mcp` 2.x, and this application pins `mcp` 1.29.0
for ADK. They cannot share a virtual environment, so the MCP server runs as
its own process:

```bash
python -m venv .mcp-clickhouse-venv
.mcp-clickhouse-venv/Scripts/python.exe -m pip install mcp-clickhouse==0.6.0
```

Load the dataset into your cluster, either from the ClickHouse Cloud SQL
console or with `clickhouse-client --multiquery < scripts/clickhouse_load.sql`.
It creates `backlot_studio` and mirrors `data/studio_dataset/*.json`: 6
`historical_costs`, 12 `vendor_rates`, 10 `crew_library`, 6
`location_library`, 5 `past_schedules`.

Fill in the `CLICKHOUSE_*` block in `.env`, then start the MCP server in its
own terminal:

```powershell
.\scripts\start_mcp_clickhouse.ps1
```

Set `MCP_MODE=clickhouse` and `CLICKHOUSE_MCP_URL=http://127.0.0.1:8766/mcp`,
then run the crew:

```bash
python run_local.py --auto-approve      # CLI
python run_server.py                    # web UI at http://127.0.0.1:8000
```

`run_local.py` also takes `--screenplay`, `--out`, `--stage breakdown` (the
Script Supervisor alone, no MCP server needed) and `--with-previz`.

### Without a ClickHouse cluster

`MCP_MODE=shim` runs a local MCP server carrying the same synthetic dataset
(`python -m backlot.mcp_shim.server`), so the repository works with no
external services. It's there for offline development. The ClickHouse path
above is the real integration.

## Testing

```bash
pytest -q
```

With no credentials and no external services running: **87 passed, 11
skipped**. Start the ClickHouse MCP server and the three MCP integration
tests run too: **90 passed, 8 skipped**. The remaining skips need Gemini
credentials, and skip cleanly without them.

- Schema, solver, MCP, metrics, API and agent-configuration tests run with
  no credentials.
- `tests/test_clickhouse_integration.py` runs against a real cluster through
  the real MCP server when `BACKLOT_TEST_CLICKHOUSE_MCP_URL` is set. It
  checks row counts, tool scoping, and that every grounded budget amount
  actually exists in ClickHouse.
- Previz is the only path that spends money on generative media, and it
  needs a second opt-in beyond credentials (`RUN_PREVIZ_LIVE_TESTS=1`). A
  normal `pytest` run never triggers a billed call.

## Deployment

The application is containerised and targets Cloud Run.
`deploy/cloud_run/deploy.sh` deploys the full FastAPI application, which is
the deployment that keeps the human-in-the-loop approval flow intact.
`deploy/agent_engine/deploy.sh` deploys the crew alone to Vertex AI Agent
Engine and auto-approves, since Agent Engine's session API has nowhere to
relay an HTTP approval.

> **Status:** these scripts have not been run against a live GCP project and
> there is no hosted instance yet. The Dockerfile is build- and run-tested
> locally and respects the `$PORT` Cloud Run injects. Check
> `gcloud run deploy --help` against your CLI version before the first
> deploy. Details in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

The Cloud Run configuration sets `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` so every
agent routes through Vertex AI, with no API key in the container. The
ClickHouse password never reaches this application; it's configured only on
whatever process runs `mcp-clickhouse`.

## Optional: generative previz

Storyboard frames, a short animatic and a temp music cue for the opening
scene, using Gemini image generation, Veo and Lyria. Off by default and not
part of the core workflow, since these are billed calls and a Veo clip can
take several minutes. Turn it on with `--with-previz` or the checkbox in the
UI.

`VEO_MODEL` defaults to the Vertex AI GA identifier to match the deployment
target. The AI Studio surface exposes preview identifiers instead, so a
local API-key previz run needs one of those.

## Data

Everything in `data/studio_dataset/` is synthetic. The figures are
fabricated for demonstration and each file carries a `"_synthetic": true`
flag. Real historical cost data is exactly the sort of thing a studio would
never publish, so this stands in for it.

The integration itself is real. `scripts/clickhouse_load.sql` loads this
dataset into actual ClickHouse tables, and the agents query it over MCP at
runtime. Swapping in a studio's real tables is a configuration change, not a
code change.

## License

Apache License 2.0. See [LICENSE](LICENSE).
