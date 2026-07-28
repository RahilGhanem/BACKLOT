# BACKLOT

**An autonomous pre-production crew**, built for the *Agentic Cinema: The
Blockbuster Hackathon* (Google Cloud + Gemini Enterprise Agent Platform,
IBM MCP partner track).

Drop in a screenplay. A network of specialised agents — orchestrated with
Google's Agent Development Kit (ADK) — returns a complete, shootable
production package: a scene-by-scene breakdown, an optimised shooting
schedule, a budget grounded in a studio's own historical data (via an IBM
MCP server), real crew/location picks, a ranked risk report, and (later)
generative previz. Every budget/resource number the crew produces is
grounded and cites its source — never invented by the model.

## Status

This repo is being built phase by phase. Each phase is runnable end-to-end
before the next one starts.

- [x] **Phase 0** — scaffold, license, sample data
- [x] **Phase 1** — Script Supervisor: screenplay → structured breakdown JSON
- [x] **Phase 2** — Line Producer orchestrator + 1st-AD Scheduler (the
      end-to-end spine: script → breakdown → schedule)
- [x] **Phase 3** — IBM MCP grounding (Budget + Resource agents, via a local
      synthetic mcp_shim server)
- [x] **Phase 4** — Risk/Continuity agent (bounded re-plan loop), human
      approval gate, scoped tool permissions
- [ ] **Phase 5** — FastAPI + web UI, live agent-activity panel, metrics
- [ ] **Phase 6** — Previz (Imagen storyboards, Veo animatic, Lyria cue)
- [ ] **Phase 7** — Deploy to Agent Engine + Cloud Run; point MCP client at
      the real IBM watsonx.data server

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
   │                                                    ┌──── bounded
   ├─ 1st-AD Scheduler    (breakdown → stripboard sched)│     re-plan loop
   ├─ Budget Agent        (grounded via IBM MCP)        │     (max 2 retries,
   ├─ Risk/Continuity     (critiques sched+budget) ──────┘     Phase 4 ✅)
   ├─ Approval Gate       (producer approves the budget band)  [Phase 4 ✅]
   ├─ Resource Agent      (grounded via IBM MCP; skipped if     [Phase 3 ✅]
   │                       the budget was rejected)
   ├─ Package Assembler   (combines everything above)          [Phase 2 ✅]
   └─ Previz Agent        (Imagen / Veo 3.1 / Lyria 3)          [Phase 6]
   │
   ▼
 IBM MCP SERVER (mcp_shim locally with synthetic data; real
 IBM watsonx.data remote MCP server in production — swapping is
 an env-var change only, see .env.example)
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

## Repo structure

```
backlot/
  config.py             # the only place that reads os.getenv — see .env.example
  schemas/               # pydantic contracts agents hand off between each other
  agents/                 # one LlmAgent (or custom BaseAgent) factory per specialist
  orchestrator/            # Line Producer
  tools/                    # custom tools, e.g. the scheduling solver
  mcp_shim/                  # local synthetic MCP server (Phase 3)
data/
  screenplays/                # sample screenplay(s) used for local dev/tests
  studio_dataset/               # synthetic historical costs, rates, crew, locations,
                                 # past schedules — served by mcp_shim
tests/                          # pytest; schema/solver/shim tests always run,
                                 # live-model tests skip automatically without
                                 # credentials (see Testing below)
run_local.py                     # CLI entrypoint for local, in-memory runs
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
- `GOOGLE_GENAI_USE_VERTEXAI=TRUE` + `GOOGLE_CLOUD_PROJECT` (Vertex AI —
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
`--screenplay` / `--out` for a different input/output path.

## Testing

```bash
pytest -v
```

- Schema, scheduler-solver, mcp_shim, and agent-configuration tests run
  with no credentials and no manually-started server.
- Tests that need the MCP server (Budget/Resource/full-pipeline) auto-start
  `mcp_shim` as a subprocess via the `mcp_shim_process` fixture in
  `tests/conftest.py` — nothing to run by hand for `pytest`.
- Tests that actually call Gemini are skipped automatically if `.env` has
  no Gemini credentials configured, and must pass once you add one.

## Data note

Everything under `data/studio_dataset/` is **synthetic** — fabricated
numbers for demo and development, clearly marked with a `"_synthetic": true`
flag in each file. It exists to exercise the IBM MCP grounding path without
needing a live IBM connection during development; pointing at the real IBM
watsonx.data remote MCP server in production is a `.env` change
(`MCP_SERVER_URL`, `MCP_AUTH_TOKEN`), not a code change — see
`backlot/mcp_shim/` for the tool interface the real server needs to match.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
