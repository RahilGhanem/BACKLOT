# BACKLOT

### An agentic pre-production crew for film.

**BACKLOT** turns a screenplay into a structured production plan through a coordinated team of specialized AI agents.

Instead of asking a single model to generate a complete production plan, BACKLOT separates the workflow into production roles: screenplay breakdown, scheduling, budgeting, risk analysis, human approval, resource selection, and final package assembly.

The result is a **traceable, reviewable production workflow** where agents can challenge earlier decisions, re-plan when necessary, and ground production costs and resources in structured studio data.

> **Live Demo:** [backlot-t4u7.onrender.com](https://backlot-t4u7.onrender.com)

---

## Why BACKLOT?

Pre-production is where creative decisions become operational constraints.

A screenplay has to become:

* scenes that can actually be scheduled
* shoot days that respect production constraints
* a budget grounded in available data
* a plan that survives risk and continuity review
* resources that match the approved production scope

Traditional software usually handles these tasks separately.

BACKLOT connects them into a single **agentic production workflow**.

The system doesn't simply generate a plan and stop. It can:

1. Break down the screenplay.
2. Build a deterministic shooting schedule.
3. Cost the resulting production plan.
4. Critically review the schedule and budget.
5. Trigger a bounded re-plan when the plan is infeasible.
6. Stop at a human approval gate.
7. Select crew and locations after approval.
8. Assemble the final production package.

---

## The Production Spine

```text
                         SCREENPLAY
                              │
                              ▼
                     SCRIPT BREAKDOWN
                              │
                              ▼
                         SCHEDULE ◀──────────┐
                              │              │
                              ▼              │
                          BUDGET             │  bounded
                              │              │  re-plan
                              ▼              │
                            RISK ────────────┘
                              │
                              ▼
                     HUMAN APPROVAL
                              │
                              ▼
                         RESOURCES
                              │
                              ▼
                  PRODUCTION PACKAGE
```

The planning loop is intentionally **bounded**. Risk can send the plan back through scheduling, budgeting, and review, but the orchestrator prevents uncontrolled iteration.

---

## What Makes BACKLOT Agentic?

BACKLOT is designed as a coordinated production crew rather than a single LLM prompt.

### Specialized roles

Each agent has a focused responsibility and produces a structured artifact for the next stage.

### Shared state

The Line Producer orchestrates the workflow and maintains the state connecting the different production stages.

### Adversarial review

The Risk / Continuity agent evaluates the schedule and budget instead of simply summarizing them.

A plan can be rejected when production constraints make it infeasible.

### Autonomous re-planning

When Risk requests a re-plan, the Line Producer sends the workflow back through the relevant planning stages with a deterministic constraint adjustment.

The loop is bounded and includes a fixed-point check so the system does not repeatedly produce the same plan.

### Human control

The system does not silently commit the production plan.

A producer must approve the budget before the Resource Agent proceeds with crew and location recommendations.

### Grounded decisions

Where structured studio data is available, budget and resource decisions carry provenance back to their underlying records.

When a value cannot be grounded, BACKLOT explicitly marks it as **ungrounded** instead of fabricating supporting evidence.

---

## Architecture

```text
                    ┌──────────────────────┐
                    │      Producer        │
                    │       Web UI         │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │       FastAPI        │
                    │     Web Backend      │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    Line Producer     │
                    │    Orchestrator      │
                    └──────────┬───────────┘
                               │
   ┌───────────────┬───────────┼───────────────┬───────────────┐
   ▼               ▼           ▼               ▼               ▼
Script         1st-AD       Budget          Risk /          Package
Supervisor     Scheduler    Agent           Continuity      Assembler
                               │               │
                               ▼               ▼
                          MCP server      Approval Gate
                               │               │
                               ▼               ▼
                         ClickHouse       Resource Agent
                      or local dataset         │
                               ▲               │
                               └───────────────┘
```

The orchestrator is intentionally not a simple sequential chain. It controls conditional execution, bounded re-planning, human approval, and optional production extensions.

Agents exchange **compact structured artifacts** rather than passing entire conversation transcripts between every stage.

---

## The Agents

| Agent | Responsibility |
| --- | --- |
| **Script Supervisor** | Converts the screenplay into structured scene information including sluglines, locations, time of day, cast, props, vehicles, VFX, stunts, and page information. |
| **1st-AD Scheduler** | Converts the breakdown into a shooting schedule using deterministic scheduling logic. |
| **Budget Agent** | Produces a costed production plan using available structured cost data. |
| **Risk / Continuity Agent** | Reviews the schedule and budget for feasibility, continuity, weather, permits, overtime, and other production risks. |
| **Approval Gate** | Pauses execution and waits for a producer decision. |
| **Resource Agent** | Recommends crew and locations using available structured studio data. |
| **Package Assembler** | Combines the outputs into the final production package. |

### Deterministic scheduling

Scheduling is deliberately separated from generative reasoning.

The scheduler uses deterministic logic to transform the structured breakdown into a repeatable shooting plan. This makes it possible to compare planning passes and reliably detect whether a re-plan actually changed the schedule.

---

## Grounded Studio Data

BACKLOT grounds production decisions in structured studio data through the **Model Context Protocol (MCP)**.

The project includes a synthetic studio dataset representing:

| Dataset | Purpose |
| --- | --- |
| `historical_costs` | Historical production cost information |
| `vendor_rates` | Vendor and production equipment rates |
| `crew_library` | Crew information and rates |
| `location_library` | Location information and production constraints |
| `past_schedules` | Historical scheduling information |

The same dataset is served two ways:

* **`MCP_MODE=clickhouse`** — the dataset is loaded into ClickHouse by `scripts/clickhouse_load.sql`, and the Budget and Resource agents issue real SQL against it through the official [`mcp-clickhouse`](https://github.com/ClickHouse/mcp-clickhouse) server. Provenance reads `clickhouse:backlot_studio.<table>`.
* **`MCP_MODE=shim`** — a bundled MCP server answers from the same JSON files, so the project runs with no external infrastructure. Provenance reads `mcp_shim:<file>`.

The UI reports whichever store actually produced the records, so the grounding label always reflects the run rather than the configuration.

### MCP tool scoping

Agents do not receive unrestricted access to the MCP server.

The data agents are scoped to exactly the tools required for their job:

```text
run_query
list_tables
```

The Budget Agent and the Resource Agent each receive their own scoped toolset, so neither can reach beyond its remit.

---

## Provenance and Grounding

Grounding is treated as a first-class part of the production package.

A data-backed value carries the record behind it:

```json
{
  "label": "Shoot Day 1: EXT. INDUSTRIAL LOT - NIGHT (Scene 1)",
  "amount": 38500.0,
  "grounded": true,
  "source_records": [
    {
      "record_id": "EXT_NIGHT_INDUSTRIAL",
      "summary": "Historical average cost of $38,500/day based on 6 comparable productions.",
      "source": "clickhouse:backlot_studio.historical_costs"
    }
  ]
}
```

The important distinction is between:

**Grounded** — the system can associate the value with a supporting record.

**Ungrounded** — no supporting record was found.

Ungrounded values are not silently presented as verified studio data. The UI lists them explicitly so a producer can see exactly which figures still need confirming.

---

## Human-in-the-Loop

BACKLOT deliberately keeps the producer in control of the commitment point.

The workflow performs analysis first:

```text
Breakdown
    ↓
Schedule
    ↓
Budget
    ↓
Risk
    ↓
┌─────────────────────┐
│   PRODUCER APPROVAL │
└─────────────────────┘
    ↓
Resources
    ↓
Production Package
```

The Resource Agent does not proceed until the approval stage has been resolved. Rejecting the budget ends the run with no resource recommendations rather than continuing anyway.

The approval mechanism is implemented as an injectable decision point, allowing the same orchestration logic to operate through different interfaces: the CLI blocks on standard input, and the web UI blocks until an HTTP approve or reject arrives.

---

## Re-planning

Risk analysis is an active part of the workflow.

When the Risk agent determines that the production plan is infeasible, it can request a re-plan with a structured justification.

A valid re-plan request must be supported by a sufficiently severe risk finding containing both:

* a description of the problem
* a recommended corrective action

An unjustified re-plan request fails schema validation.

The Line Producer then re-runs the relevant planning stages. The loop is protected by multiple constraints:

* a maximum number of re-planning passes
* deterministic constraint changes on each pass
* validation of re-plan requests
* fixed-point detection to stop when a new pass produces the same schedule

This prevents an uncontrolled agent loop while still allowing the system to respond to its own analysis.

---

## The Production Package

A completed run produces a structured production package containing the outputs of the workflow:

* screenplay breakdown
* shooting schedule
* budget
* budget provenance
* risk report
* approval decision
* crew recommendations
* location recommendations
* optional previz outputs

The web interface presents these artifacts as a production control room rather than a generic chat interface.

The interface exposes:

* agent pipeline state, with the re-plan drawn as an actual loop back to the Scheduler when one occurs
* schedule and shooting board
* budget composition
* risk information linked to the scenes and days each finding affects
* grounding information, including every claim that could not be grounded
* approval state
* production resources
* final package output

Completed runs can be downloaded and reopened later for review without executing the entire workflow again.

---

## Live Demo

**Try BACKLOT:** [backlot-t4u7.onrender.com](https://backlot-t4u7.onrender.com)

The live application demonstrates the complete production workflow through a browser-based control room.

The intended flow is:

```text
Open BACKLOT
      ↓
Provide a screenplay
      ↓
Run the production crew
      ↓
Review breakdown
      ↓
Review schedule
      ↓
Review budget
      ↓
Review risk analysis
      ↓
Observe re-planning when required
      ↓
Approve / reject
      ↓
Review resources
      ↓
Inspect production package
```

The hosted instance runs in `MCP_MODE=shim`, so the demo is self-contained and needs no external database. The ClickHouse integration is exercised locally and by the integration test suite described under [Testing](#testing).

---

## Technology

BACKLOT is built around an agentic backend with a lightweight web interface.

### AI & orchestration

* **Gemini**
* **Google Agent Development Kit (ADK)**
* Custom ADK agent orchestration
* Structured agent artifacts

### Data & integration

* **Model Context Protocol (MCP)**
* **mcp-clickhouse**
* **ClickHouse**
* Synthetic studio dataset for development and demonstration

### Backend

* **Python**
* **FastAPI**
* **Uvicorn**

### Frontend

* HTML
* CSS
* JavaScript
* No frontend framework
* No frontend build step

### Deployment

* Docker
* Render for the current live deployment
* Google Cloud deployment configuration is also included in the repository

---

## Local Development

BACKLOT requires **Python 3.11+**.

### 1. Create a virtual environment

```bash
python -m venv .venv
```

### 2. Activate it

**Windows / Git Bash:**

```bash
source .venv/Scripts/activate
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Configure the Gemini credentials in `.env`: either `GOOGLE_API_KEY` for AI Studio, or `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` plus `GOOGLE_CLOUD_PROJECT` for Vertex AI.

`backlot/config.py` is the only module that reads environment variables.

**Never commit API keys or other secrets to the repository.**

---

## Running with the MCP Shim

For development without an external ClickHouse cluster, BACKLOT provides a local MCP server backed by the included synthetic dataset.

Start it with:

```bash
python -m backlot.mcp_shim.server
```

Then start the application using the normal local server or CLI entry point.

This mode is useful for development, testing, and environments where an external ClickHouse service is not available.

---

## Running with ClickHouse

`mcp-clickhouse` requires `mcp` 2.x while this application pins `mcp` 1.29.0 for ADK, so the MCP server runs as its own process in its own environment:

```bash
python -m venv .mcp-clickhouse-venv
.mcp-clickhouse-venv/Scripts/python.exe -m pip install mcp-clickhouse==0.6.0
```

Load the dataset into your cluster, either from the ClickHouse Cloud SQL console or with:

```bash
clickhouse-client --multiquery < scripts/clickhouse_load.sql
```

It creates `backlot_studio` and mirrors `data/studio_dataset/*.json`. The script is safe to re-run: each table is truncated before it is loaded.

Fill in the `CLICKHOUSE_*` block in `.env`, start the MCP server, then run BACKLOT with:

```text
MCP_MODE=clickhouse
```

---

## CLI

The repository includes a CLI entry point for running the production crew locally:

```bash
python run_local.py --auto-approve
```

Additional options are available for running individual stages, supplying a screenplay, exporting results, and enabling optional functionality:

```bash
python run_local.py --help
```

---

## Web Application

Start the local web server with:

```bash
python run_server.py
```

The application is then available at:

```text
http://127.0.0.1:8000
```

---

## Testing

Run the test suite with:

```bash
pytest -q
```

With no credentials and no external services running: **87 passed, 11 skipped**. Start the ClickHouse MCP server and the integration tests run as well: **90 passed, 8 skipped**. The remaining skips require Gemini credentials and skip cleanly without them.

The suite covers:

* schemas and structured-output contracts
* deterministic scheduling
* MCP integration and tool scoping
* metrics
* API behaviour
* agent configuration
* ClickHouse integration

`tests/test_clickhouse_integration.py` runs against a real cluster through the real MCP server when `BACKLOT_TEST_CLICKHOUSE_MCP_URL` is set. It verifies row counts, tool scoping, and that every grounded budget amount actually exists in ClickHouse.

Generative previz is the only path that spends money on media generation, and it requires a second explicit opt-in beyond credentials (`RUN_PREVIZ_LIVE_TESTS=1`). A normal `pytest` run never triggers a billed call.

---

## Deployment

### Current deployment: Render

BACKLOT is deployed as a containerized application on **Render**:

https://backlot-t4u7.onrender.com

The container starts the web backend together with the MCP server required by the hosted configuration, and respects the platform-provided `PORT` environment variable.

### Alternative deployment targets

The repository also contains deployment configuration for Google Cloud Run and Vertex AI Agent Engine. These are **alternative deployment paths**, not the current hosting environment for the public demo.

Refer to:

```text
docs/DEPLOYMENT.md
```

for deployment-specific details.

---

## Data and Privacy

The repository's included studio dataset is **synthetic**.

It does not represent proprietary production-company records. Each file is explicitly flagged with `"_synthetic": true` and carries a disclaimer.

The synthetic data demonstrates the grounding architecture, MCP integration, budgeting workflow, resource selection, and provenance tracking.

The architecture is designed so that a studio could replace the demonstration dataset with its own authorized data sources. Swapping in real tables is a configuration change, not a code change.

No private studio data is included in this repository.

---

## Optional Generative Previz

BACKLOT optionally supports generative previsualization: storyboard frames, a short animatic, and a temp music cue for the opening scene.

This functionality is separate from the core production-planning workflow and is disabled by default, since these are billed calls and video generation can take several minutes.

The core BACKLOT pipeline does not depend on generated storyboards, animatics, or music cues.

---

## Project Structure

```text
BACKLOT/
├── backlot/
│   ├── agents/            one factory per specialist agent
│   ├── api/               FastAPI backend and the web UI
│   ├── orchestrator/      the Line Producer
│   ├── schemas/           typed artifacts agents hand each other
│   ├── tools/             deterministic scheduler, previz generation
│   └── mcp_shim/          local MCP server over the synthetic dataset
├── data/
│   ├── studio_dataset/    synthetic cost, crew and location data
│   ├── screenplays/       sample and re-plan demo screenplays
│   └── icons/             UI assets
├── tests/
├── scripts/               ClickHouse load script, MCP server launcher
├── deploy/                Cloud Run and Agent Engine configuration
├── docs/
├── Dockerfile
├── docker-entrypoint.sh
├── requirements.txt
├── run_local.py
└── run_server.py
```

---

## Design Principles

BACKLOT is built around a few principles:

### Specialized intelligence

Give each production responsibility to an agent designed for that role rather than relying on one general-purpose prompt.

### Deterministic operations

Use deterministic logic where consistency matters, particularly for scheduling and workflow control.

### Evidence over invention

When production data is available, connect decisions to source records. When evidence is unavailable, expose that limitation.

### Controlled autonomy

Agents can analyze, challenge, and re-plan the production, but the workflow remains bounded and the producer retains control over commitment.

### Structured collaboration

Agents exchange compact, typed artifacts instead of relying on long conversational transcripts.

---

## License

BACKLOT is released under the **Apache License 2.0**.

See [`LICENSE`](LICENSE) for the full license text.
