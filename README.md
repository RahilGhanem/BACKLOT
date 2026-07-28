# BACKLOT

**An autonomous pre-production crew**, built for the *Agentic Cinema: The
Blockbuster Hackathon* (Google Cloud + Gemini Enterprise Agent Platform,
IBM MCP partner track).

Drop in a screenplay. A network of specialised agents — orchestrated with
Google's Agent Development Kit (ADK) — returns a complete, shootable
production package: a scene-by-scene breakdown, an optimised shooting
schedule, a budget grounded in a studio's own historical data (via an IBM
MCP server), a ranked risk report, and (later) generative previz. Every
budget/resource number the crew produces is grounded and cites its source —
never invented by the model.

## Status

This repo is being built phase by phase. Each phase is runnable end-to-end
before the next one starts.

- [x] **Phase 0** — scaffold, license, sample data
- [x] **Phase 1** — Script Supervisor: screenplay → structured breakdown JSON
- [ ] **Phase 2** — Line Producer orchestrator + 1st-AD Scheduler (the
      end-to-end spine: script → breakdown → schedule)
- [ ] **Phase 3** — IBM MCP grounding (Budget + Resource agents)
- [ ] **Phase 4** — Risk/Continuity agent, human approval gate, governance
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
 LINE PRODUCER (orchestrator, ADK SequentialAgent)
   ├─ Script Supervisor   (screenplay → breakdown JSON)          [Phase 1 ✅]
   ├─ 1st-AD Scheduler    (breakdown → stripboard schedule)       [Phase 2]
   ├─ Budget Agent        (grounded via IBM MCP)                  [Phase 3]
   ├─ Resource Agent      (grounded via IBM MCP)                  [Phase 3]
   ├─ Risk/Continuity     (critique + bounded reflection loop)     [Phase 4]
   └─ Previz Agent        (Imagen / Veo 3.1 / Lyria 3)              [Phase 6]
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

## Repo structure

```
backlot/
  config.py            # the only place that reads os.getenv — see .env.example
  schemas/              # pydantic contracts agents hand off between each other
  agents/               # one LlmAgent factory per specialist
  orchestrator/          # Line Producer (Phase 2+)
  tools/                 # custom tools, e.g. the scheduling solver (Phase 2+)
  mcp_shim/               # local synthetic MCP server (Phase 3+)
data/
  screenplays/            # sample screenplay(s) used for local dev/tests
  studio_dataset/          # synthetic historical costs, rates, crew, locations,
                            # past schedules — served by mcp_shim in Phase 3
tests/                     # pytest; schema tests always run, live-model tests
                            # skip automatically without credentials
run_local.py                # CLI entrypoint for local, in-memory runs
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

```bash
python run_local.py
```

This parses `data/screenplays/sample_screenplay.txt` with the Script
Supervisor agent and writes the resulting breakdown to
`output/breakdown.json`. Pass `--screenplay` / `--out` to use a different
file.

## Testing

```bash
pytest -v
```

Schema and agent-configuration tests run with no credentials and no network
access. The one end-to-end test that actually calls Gemini
(`test_script_supervisor_breaks_down_sample_screenplay`) is skipped
automatically if `.env` has no Gemini credentials configured, and runs (and
must pass) once you add one.

## Data note

Everything under `data/studio_dataset/` is **synthetic** — fabricated
numbers for demo and development, clearly marked with a `"_synthetic": true`
flag in each file. It exists to exercise the IBM MCP grounding path (Phase 3)
without needing a live IBM connection during development; pointing at the
real IBM watsonx.data remote MCP server in production is a `.env` change
(`MCP_SERVER_URL`, `MCP_AUTH_TOKEN`), not a code change.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
