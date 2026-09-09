# BACKLOT — Detailed Technical Documentation

This document explains how BACKLOT is built and, more importantly, **why it is
built this way**. Every significant decision is recorded together with the
alternatives that were considered and rejected, and with the file where the
decision lives.

The short README describes what the system does. This one is for a reader who
wants to know whether the engineering behind it is sound.

- [1. The problem](#1-the-problem)
- [2. System shape](#2-system-shape)
- [3. Why a custom orchestrator](#3-why-a-custom-orchestrator)
- [4. Why the scheduler is not an LLM](#4-why-the-scheduler-is-not-an-llm)
- [5. Why MCP instead of a database driver](#5-why-mcp-instead-of-a-database-driver)
- [6. Why ClickHouse](#6-why-clickhouse)
- [7. The MCP dependency conflict](#7-the-mcp-dependency-conflict)
- [8. Grounding and provenance](#8-grounding-and-provenance)
- [9. The Risk Agent and structured output](#9-the-risk-agent-and-structured-output)
- [10. The re-plan control loop](#10-the-re-plan-control-loop)
- [11. Human-in-the-loop](#11-human-in-the-loop)
- [12. Token economics](#12-token-economics)
- [13. Frontend decisions](#13-frontend-decisions)
- [14. Testing strategy](#14-testing-strategy)
- [15. Deployment](#15-deployment)
- [16. Failure modes and bounds](#16-failure-modes-and-bounds)
- [17. Security](#17-security)
- [18. Current limitations](#18-current-limitations)
- [19. What we would build next](#19-what-we-would-build-next)

---

## 1. The problem

Pre-production is the phase where a screenplay becomes an operational plan. It
is also where mistakes are cheapest to fix and most expensive to miss: an
unnoticed run of consecutive night exteriors becomes crew fatigue, overtime,
and a blown schedule once the unit is on the floor.

The work decomposes into distinct professional roles:

| Role | Question they answer |
| --- | --- |
| Script supervisor | What is actually in this screenplay? |
| 1st AD | How do these scenes pack into shoot days? |
| Line producer | What does this plan cost? |
| Continuity / risk | What will go wrong with this plan? |
| Producer | Do we commit to it? |
| Resource coordinator | Who and where do we book? |

Software exists for several of these individually. What does not exist is a
system that runs the whole sequence, **evaluates its own output**, and costs
the plan against a studio's actual historical numbers rather than a plausible
guess.

That gap is what BACKLOT addresses, and it is why the project is structured as
a crew rather than a prompt.

### Why this is a good fit for agents specifically

A common failure of agent demos is that the task did not need agents. This one
has three properties that justify the architecture:

1. **Genuine role separation.** The information each stage needs is different.
   The Budget agent does not need the screenplay text; it needs the schedule.
2. **A real evaluation step.** Risk analysis is not a summary of the previous
   steps, it is a judgement that can *reject* them. That is what makes the
   system agentic rather than a pipeline.
3. **A natural human checkpoint.** There is an obvious point where analysis
   becomes spend, which gives the human-in-the-loop gate a reason to exist
   beyond ceremony.

---

## 2. System shape

```
Producer (browser)
      │
      ▼
FastAPI + static web UI                     backlot/api/
      │
      ▼
Line Producer (custom ADK BaseAgent)        backlot/orchestrator/line_producer.py
      ├─ Script Supervisor    LlmAgent      backlot/agents/script_supervisor.py
      ├─ 1st-AD Scheduler     BaseAgent     backlot/agents/scheduler.py
      ├─ Budget Agent         LlmAgent+MCP  backlot/agents/budget.py
      ├─ Risk / Continuity    LlmAgent      backlot/agents/risk.py
      ├─ Approval Gate        BaseAgent     backlot/agents/approval_gate.py
      ├─ Resource Agent       LlmAgent+MCP  backlot/agents/resource.py
      └─ Package Assembler    BaseAgent     backlot/agents/package_assembler.py
      │
      ▼
MCP server ──▶ ClickHouse  (or the bundled synthetic dataset)
```

Note the mix: **only four of the seven agents are LLM agents.** The Scheduler,
Approval Gate and Package Assembler are deterministic `BaseAgent`
implementations. Using a language model for work that is not a language problem
is the most common way agent systems become slow, expensive and unreliable, so
BACKLOT deliberately uses the model only where judgement is required.

### Agent-by-agent

| Agent | Type | Model call? | Tools | Output artifact |
| --- | --- | --- | --- | --- |
| Script Supervisor | `LlmAgent` | Yes | none | `ScriptBreakdown` |
| 1st-AD Scheduler | `BaseAgent` | **No** | none | `Schedule` |
| Budget Agent | `LlmAgent` | Yes | `run_query`, `list_tables` | `BudgetEstimate` |
| Risk / Continuity | `LlmAgent` | Yes | none | `RiskReport` |
| Approval Gate | `BaseAgent` | **No** | none | `ApprovalDecision` |
| Resource Agent | `LlmAgent` | Yes | `run_query`, `list_tables` | `ResourcePlan` |
| Package Assembler | `BaseAgent` | **No** | none | `ProductionPackage` |

Each artifact is a Pydantic model in `backlot/schemas/`. Agents communicate
only through these typed artifacts held in ADK session state — never by passing
conversation transcripts to each other.

---

## 3. Why a custom orchestrator

**Decision:** the Line Producer is a hand-written `BaseAgent`
(`backlot/orchestrator/line_producer.py`) rather than one of ADK's supplied
workflow primitives.

**Alternatives considered:**

| Option | Why it was rejected |
| --- | --- |
| `SequentialAgent` | The control flow is not a sequence. It needs a loop back to the Scheduler, a conditional skip of the Resource agent, and an optional Previz stage. `SequentialAgent` cannot express any of the three. |
| `LoopAgent` | Would cover the re-plan loop, but not the conditional skip after rejection, and it does not give access to the loop state needed for fixed-point detection. |
| ADK `Workflow` (graph primitive) | In the installed ADK 2.5.0 this is not usable as a plain `BaseAgent`: it cannot be handed to `Runner` or nested as a sub-agent, which the API layer requires. |
| A framework like LangGraph | Prohibited by the hackathon's AI-tooling restriction, and would add a dependency to replace roughly 200 lines of explicit, testable control flow. |

The orchestrator is about 300 lines and does four things a generic primitive
could not:

1. Runs a **bounded re-plan loop** over Scheduler → Budget → Risk.
2. **Skips the Resource agent** when the producer rejects the budget.
3. **Retries Risk** on schema-validation failure with corrective guidance.
4. **Resolves sub-agents by name**, not position, so the optional Previz stage
   does not shift the sequence.

The cost of this decision is that the control flow is our own code and must be
tested. That is why `tests/test_line_producer_control_flow.py` exists and drives
the loop with deterministic fake agents rather than live models.

---

## 4. Why the scheduler is not an LLM

**Decision:** shoot-day scheduling is a deterministic solver
(`backlot/tools/scheduler_solver.py`), not a model call.

**Why.** Packing scenes into shoot days is a constraint problem, not a language
problem. Asking a model to do it buys nothing and costs three things:

1. **Non-determinism.** The same breakdown would produce different schedules on
   different runs.
2. **Silent constraint violation.** A model will happily emit a day that
   exceeds the page cap.
3. **Cost and latency** on every re-plan pass.

The algorithm:

```
group scenes by (location, day/night bucket)   preserving first-appearance order
for each group:
    pack scenes into days, greedily, in sequence order
    open a new day when adding a scene would exceed max_pages_per_day
```

Grouping by location is what a 1st AD actually does — you shoot out a location
before moving the unit. Splitting on day/night avoids scheduling a night
exterior and a day interior in the same block.

**The property that matters most:** determinism makes the re-plan loop
meaningful. Because the same input always yields the same stripboard, the
orchestrator can hash the schedule and detect that a second planning pass
produced *the same plan*, then stop instead of looping. With an LLM scheduler
that check would be impossible — output would differ every pass whether or not
anything improved.

---

## 5. Why MCP instead of a database driver

**Decision:** the Budget and Resource agents reach data through the Model
Context Protocol, not through a ClickHouse client library.

**Alternative:** import `clickhouse-connect` and give the agents a Python
function that runs SQL. Simpler, fewer moving parts, one less process.

**Why MCP won:**

1. **Tool scoping is enforced outside the agent.** Each agent gets an
   `McpToolset` with an explicit `tool_filter`. The Budget agent's toolset
   resolves to exactly `run_query` and `list_tables`; it cannot call anything
   else because nothing else is in its tool list. With a direct driver, scoping
   would be a convention inside a prompt.

2. **The credential boundary is real.** The ClickHouse host, user and password
   are configured on the MCP server process only. The BACKLOT application never
   receives them, and cannot, because it only knows an HTTP endpoint. A
   compromised agent cannot leak a database password it was never given.

3. **The data source is swappable without touching agent code.** Switching
   between the bundled dataset and a real cluster is an environment variable
   (`MCP_MODE`), because both speak the same protocol.

4. It is the integration the partner track actually asks for.

The cost is an extra process to run and a network hop per query. For this
workload — a handful of queries per run — that is not a meaningful price.

---

## 6. Why ClickHouse

Beyond it being the chosen partner track, it fits the workload:

- The grounding queries are **analytical aggregates over historical rows**
  ("what did comparable night exteriors cost per day?"), which is exactly what
  a columnar store is for.
- A real studio's cost history is large and append-only — the shape ClickHouse
  is designed around.
- `mcp-clickhouse` is maintained by ClickHouse themselves, so the integration
  is the official path rather than a community wrapper.

The dataset shipped here is small and synthetic, so the performance argument is
not demonstrated by this repository. It is stated as the reason the
architecture points at ClickHouse rather than, say, SQLite.

### Tool choice inside the server

`mcp-clickhouse` exposes several tools. The agents are scoped to two:

```python
CLICKHOUSE_TOOL_FILTER = ["run_query", "list_tables"]
```

`run_query` is the tool name the current server registers. Some third-party
documentation refers to `run_select_query`, which is stale and does not resolve
on 0.6.0 — `tests/test_grounded_agents.py` pins this so the mistake cannot
silently return. `run_chdb_select_query` is deliberately excluded: it targets
an embedded chDB engine, not the real cluster, so allowing it would let an
agent produce a "grounded" number from somewhere other than the studio data.

---

## 7. The MCP dependency conflict

This is the least obvious constraint in the project and it shapes the deployment.

`google-adk` 2.5.0 pins `mcp` **1.29.0**. `mcp-clickhouse` 0.6.0 requires
`mcp` **>= 2.x**. The two cannot coexist in one virtual environment.

**Options considered:**

| Option | Verdict |
| --- | --- |
| Downgrade `mcp-clickhouse` | No release is compatible with `mcp` 1.x. |
| Upgrade `mcp` in the app venv | Breaks ADK's MCP toolset at import. |
| Vendor the ClickHouse client and skip the official server | Defeats the purpose: the partner requirement is the official MCP integration. |
| **Run the MCP server as a separate process in its own environment** | ✅ Chosen. |

This is not a workaround, it is the correct topology anyway: MCP is a
client/server protocol and the server is *supposed* to be a separate process
with its own dependencies and its own credentials. The dependency conflict
simply forces the architecture to be honest about it.

Consequences that show up throughout the repo:

- `scripts/start_mcp_clickhouse.ps1` launches the server from
  `.mcp-clickhouse-venv`, reading `CLICKHOUSE_*` from `.env` without echoing
  the password.
- The README warns explicitly against installing `mcp-clickhouse` into `.venv`.
- `tests/test_clickhouse_integration.py` talks to the server over HTTP, like
  any other client.

---

## 8. Grounding and provenance

The central claim of this project is that a number the system reports can be
traced to the record it came from. That required three design decisions.

### 8.1 Provenance is part of the schema, not a log

`backlot/schemas/provenance.py` defines `GroundedRecord`, and every grounded
value carries a list of them in its `source_records` field:

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

Because provenance is a typed field on the artifact, it survives into the
downloaded package, and it can be asserted on in tests. Had it been emitted as
log output it would have been unverifiable and would have disappeared from the
deliverable.

### 8.2 `grounded: false` is a first-class outcome

The alternative — letting the model estimate when no record matches — was
rejected outright. An estimate that looks like a costed figure is worse than no
figure, because a producer cannot tell them apart.

The agents are instructed to mark a value ungrounded with empty
`source_records` when nothing matches, and the UI lists those separately rather
than burying them. In a real run the model does this correctly, for example on
a picture vehicle with no matching vendor row.

### 8.3 The UI reports the store that actually answered

The grounding label is derived from the `source` prefix present in the records
(`views.js`, `groundingStore`), not from configuration. Running against the
bundled dataset shows "grounded in the local dataset"; running against
ClickHouse shows "grounded in ClickHouse". The interface therefore cannot claim
a data source that did not produce the run.

### 8.4 The strongest test in the suite

`tests/test_clickhouse_integration.py` does not merely check that the Budget
agent produced provenance. It reads every grounded amount, queries ClickHouse
for the full set of legitimate values, and asserts each amount actually exists
in the database:

```python
assert item["amount"] in real_amounts, (
    f"{item['label']}: {item['amount']} is not any value in ClickHouse — "
    "the model invented it"
)
```

If the model ever fabricates a plausible number and attaches a real-looking
record id, this test fails.

---

## 9. The Risk Agent and structured output

This was the hardest engineering problem in the project and the fix is
non-obvious, so it is documented in full.

### 9.1 Symptom

The Risk agent, which returns a `RiskReport` via ADK's `output_schema`, would
intermittently produce a degenerate response: the free-text `replan_reason`
field filled with the same token repeated for thousands of characters
(`"risk. risk. risk. …"`, up to ~175,000 characters observed) while the
`flags` array came back empty. The report then failed the schema's own
validator, because a report that requests a re-plan with zero supporting flags
is self-contradictory.

Retrying did not help. Changing model version did not help. The same agent
worked perfectly with `output_schema` removed.

### 9.2 What was ruled out

- **Not the tools.** The Risk agent has `tools == []`, so no MCP path is
  involved.
- **Not the prompt.** The instruction explicitly asks for flags first, and the
  agent produced correct flags when unconstrained.
- **Not the model.** Reproduced across several Gemini Flash versions.

### 9.3 Root cause

Reading ADK's flow code
(`google/adk/flows/llm_flows/basic.py`, inside the installed ADK package) shows that for an agent **without**
tools, `output_schema` is applied as a native `response_schema` on the request —
constrained decoding. For an agent **with** tools, ADK instead uses a
`set_model_response` function-call workaround. This explains why the Budget
agent, which has tools, never degenerated while the tool-less Risk agent did.

Dumping the schema actually transmitted revealed the mechanism:

```
required: ['title', 'schedule_feasible']
```

`flags` carried a Pydantic default (`default_factory=list`), which made it
**optional** in the emitted JSON schema. Constrained decoding is free to omit
any property absent from `required` — so the decoder could skip `flags`
entirely and continue generating into the next free-text field, where nothing
bounded it.

The validator was never wrong. The schema was under-constrained.

### 9.4 Fix

`backlot/schemas/risk.py` forces every property into `required` on the wire
while keeping the Python-side defaults, so callers and tests are unaffected:

```python
def _require_every_property(schema: dict) -> None:
    schema["required"] = list(schema.get("properties", {}).keys())

class RiskReport(BaseModel):
    model_config = ConfigDict(json_schema_extra=_require_every_property)
```

Free-text fields also carry `max_length`, so a degenerate generation fails
validation quickly rather than consuming the whole output budget.

**Measured:** 0 of 6 valid reports before the change, 3 of 3 after (the fourth
trial hit an API quota error, not a degeneration), with `replan_reason` lengths
of 129–206 characters instead of six figures. Since verified on three Gemini
Flash versions, which is what indicates the fix is structural rather than
model-specific.

`tests/test_risk_schema_contract.py` pins this so the regression cannot return:
it asserts the transmitted schema requires every field, that free-text fields
are bounded, and that a simulated degenerate response is rejected.

### 9.5 Why this matters beyond this project

The general lesson is that with constrained decoding, **a Pydantic default is
not a harmless convenience** — it changes what the model is permitted to omit.
Any optional field in a structured-output schema is a field the model may skip.

---

## 10. The re-plan control loop

The re-plan loop is the system's signature behaviour, and it is a control loop
rather than a retry.

### 10.1 Gating: when a re-plan is allowed

A re-plan runs only when **both** hold:

- the Risk report sets `replan_requested`, and
- at least one **high-severity** flag with a non-empty description and
  recommendation is present.

The second condition is enforced by `RiskReport`'s validator, so an
unjustified re-plan request fails schema validation before the orchestrator
ever sees it. This prevents the loop from being triggered by a vague complaint.

### 10.2 The adjustment is diagnosis-driven

This is the part that distinguishes it from a retry. The orchestrator inspects
the schedule and moves the constraint **in the direction the diagnosis
implies**:

```python
if _has_overloaded_day(schedule):
    # days are too full -> fewer pages per day
    scheduler.max_pages_per_day = max(cap * 0.85, MIN_PAGES_PER_DAY)
elif night_run > 3:
    # too many consecutive nights -> more pages per day, so same-location
    # night scenes consolidate into fewer night days
    scheduler.max_pages_per_day = min(cap / 0.85, MAX_PAGES_PER_DAY_CEILING)
```

Note that these move the cap in **opposite directions**. Shrinking the cap
would make a consecutive-nights problem *worse* by spreading nights across more
days. Recognising that the correct response depends on which problem was found
is why this is a control loop.

Constants: `REPLAN_SHRINK_FACTOR = 0.85`, `MIN_PAGES_PER_DAY = 2.0`,
`MAX_PAGES_PER_DAY_CEILING = 8.0`.

### 10.3 Three independent bounds

| Bound | Value | Purpose |
| --- | --- | --- |
| Re-plan cap | `MAX_REPLANS = 2` | Hard ceiling on planning passes |
| Constraint clamp | 2.0 – 8.0 pages/day | The adjustment cannot run away |
| Fixed-point check | schedule fingerprint | Stops when a pass changes nothing |

The fixed-point check is the interesting one. Before each pass the orchestrator
hashes the schedule (`_schedule_fingerprint`). If a new pass produces a schedule
identical to the previous one, it stops immediately and records why, rather than
burning the remaining budget re-deriving the same plan. This is only possible
because the scheduler is deterministic — see §4.

### 10.4 Separately: bounded validation retries

Distinct from re-planning, the Risk agent gets `MAX_RISK_VALIDATION_RETRIES = 2`
corrective retries if its structured output fails validation. The retry appends
specific guidance about what was wrong. After the final attempt it raises rather
than spinning.

Every loop in this system terminates by construction.

---

## 11. Human-in-the-loop

**Placement.** The gate sits between costing and commitment. Everything before
it is analysis; the Resource agent after it proposes actual crew and locations.
That is the point where the plan starts implying spend, so it is where a human
belongs.

**Design.** The gate is a `BaseAgent` holding an **injectable decider**
(`backlot/agents/approval_gate.py`):

```python
ApprovalDecider = Callable[[dict], Union[tuple[bool, str], Awaitable[tuple[bool, str]]]]
```

- CLI: blocks on `stdin`.
- Web: blocks on an `asyncio.Event` released by `POST /api/runs/{id}/approve`.
- Tests and Agent Engine: `auto_approve_decider`.

The orchestrator does not know which is in use. Adding a Slack approval would
be a new decider, not a change to the pipeline.

**Rejection is a real branch, not an error.** A rejected budget produces a
package with `resources: null` and the run ends. The system does not proceed
with a plan the producer declined.

**The gate shows the real numbers.** The modal renders the actual costed line
items with their grounding badges, not a placeholder — a producer cannot
meaningfully approve a figure they have not seen.

---

## 12. Token economics

Agents exchange **compact structured artifacts**, never transcripts. The
practical consequence:

- Only the Script Supervisor ever receives the full screenplay.
- The Scheduler receives the breakdown, not the script.
- The Budget agent receives the schedule, not the script.
- The Risk agent receives breakdown + schedule + budget — all structured JSON.

So the per-run token cost is roughly **flat in screenplay length** past the
first agent. A feature-length script costs materially more only in the Script
Supervisor stage.

The re-plan loop reinforces this: a second planning pass re-runs Scheduler →
Budget → Risk, none of which re-read the screenplay.

`MAX_LLM_CALLS_PER_RUN` (default 15) is passed to ADK's `RunConfig` as a final
backstop against runaway invocation.

---

## 13. Frontend decisions

**No framework, no build step.** Plain HTML, CSS and JavaScript served by
FastAPI's `StaticFiles`.

The reasoning: the UI needs to poll a JSON endpoint and render structured data.
That is not a problem that requires React, and adding it would mean a build
pipeline, a `node_modules` tree, and a compile step between a judge cloning the
repo and running it. The whole frontend is four files and loads in under
250 KB including fonts.

The trade-off is real — no component model and no reactive state — which is why
rendering is separated into pure string functions (`views.js`) with the run
engine and router kept apart (`app.js`). `views.js` has no DOM dependency at
all, which is what makes it unit-testable in Node without a browser.

**The control room.** The Overview is composed around one idea: a production
pipeline where each station carries the real value it produced, the connector
fills only where data has actually flowed, and a re-plan draws an **actual arc**
back to the Scheduler. Deriving the diagram from real run state rather than
decorating it was the point.

**The provenance drawer** presents a trace — decision → agent → tool → dataset →
record — and marks any step the run did not record rather than inventing one.
A reopened package has no event log, so the "Tool" step honestly reads
"not recorded".

**Accessibility** was kept as a constraint, not an afterthought: skip link as
first tab stop, real focus-visible rings, `aria` on live regions and dialogs,
locked views removed from the tab order, and `prefers-reduced-motion` honoured.

---

## 14. Testing strategy

The suite is layered so that most of it runs with no credentials and no
external services.

| Layer | Runs without credentials | What it protects |
| --- | --- | --- |
| Schema contracts | ✅ | Structured-output invariants (§9) |
| Scheduler solver | ✅ | Determinism, packing, page caps |
| Control flow | ✅ | Re-plan loop, bounds, approval skip |
| MCP surface | needs MCP server | Tool scoping, real SQL, row counts |
| Grounded agents | needs MCP + Gemini | Provenance, no invented values |
| Frontend renderers | ✅ (Node) | Rendering, escaping, empty states — `tests/frontend/test_views.mjs` |

**Control-flow tests use fake agents.** `tests/test_line_producer_control_flow.py`
drives the orchestrator with deterministic stand-ins that reproduce specific
behaviours — including an agent that raises `ValidationError` twice then
succeeds, to prove the bounded retry works. Testing loop bounds against a live
model would be slow, expensive and non-deterministic.

**Integration tests are not mocked.** The ClickHouse tests talk to a real
cluster through the real MCP server. Mocking there would test nothing.

**Billed media generation requires a second opt-in.** Credentials alone are not
enough; the previz live test also needs `RUN_PREVIZ_LIVE_TESTS=1`, so a routine
`pytest` can never trigger a paid Imagen/Veo call by accident.

Current status: **87 passed, 11 skipped** with no services; **90 passed,
8 skipped** with the ClickHouse MCP server running.

---

## 15. Deployment

**Current:** containerised on Render, live at
`https://backlot-t4u7.onrender.com`.

### Why the container starts two processes

The image runs `docker-entrypoint.sh`, which starts the MCP server on loopback
before exec'ing uvicorn. Without it, `check_mcp_reachable` fails and every run
errors immediately — a hosted URL where nothing works.

One subtlety worth recording: `backlot/config.py` prefers `PORT` over `MCP_SHIM_PORT`
so the MCP server *can* be hosted standalone. In a shared container that would
make it bind the same port as the web app, so the entrypoint starts it with
`PORT` unset.

### Why the hosted demo runs the bundled dataset

The public instance runs `MCP_MODE=shim`, so it is self-contained and needs no
external database to stay up. This is stated plainly in the UI, which reports
the store that actually answered (§8.3). The ClickHouse path is exercised
locally and by the integration suite.

### Alternative targets in the repo

| Target | Trade-off |
| --- | --- |
| **Cloud Run** (`deploy/cloud_run/deploy.sh`) | Serves the whole FastAPI app, so the human approval flow survives. Sets `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` to route via Vertex AI with no API key in the container. |
| **Vertex AI Agent Engine** (`deploy/agent_engine/`) | Managed agent runtime, but its session API is stateless request/response with nowhere to relay an HTTP approval — so that variant auto-approves. Kept as a demonstration of the ADK deployment convention, not as the primary path. |

That trade-off is the reason Cloud Run is the recommended target: the
human-in-the-loop gate is a core feature and Agent Engine cannot host it as
built.

---

## 16. Failure modes and bounds

| Failure | Behaviour |
| --- | --- |
| MCP server unreachable | Run fails fast with an actionable message, before any model call |
| ClickHouse table missing | `run_query` error surfaces; the value is left ungrounded |
| Risk output fails validation | Up to 2 corrective retries, then raises |
| Risk demands endless re-plans | Capped at 2 passes |
| Re-plan produces the same schedule | Fixed-point detection stops it |
| Model runs away in a text field | `max_length` rejects it |
| Runaway agent invocation | `MAX_LLM_CALLS_PER_RUN` backstop |
| Budget rejected | Resource agent skipped, `resources: null` |
| No matching data row | `grounded: false`, empty `source_records` |
| Model quota exhausted | Run stops with the API error surfaced to the UI |

There is no unbounded loop in the system.

---

## 17. Security

- **No credentials in the repository.** `.env*` is gitignored except
  `.env.example`, which contains placeholders only.
- **The database password never reaches the application.** It is configured on
  the MCP server process (§5).
- **Tool scoping is structural**, enforced by `tool_filter`, not by prompt
  instruction.
- **Injection posture:** agent instructions state that retrieved data is data,
  never instructions. Structurally, tool results arrive as distinct
  function-response blocks rather than concatenated prompt text.
- **The UI escapes all rendered content**; `tests/frontend/test_views.mjs`
  feeds `<img src=x onerror=...>` through a scene synopsis and asserts it is
  escaped.
- **Deployment secrets** come from the platform's secret store or environment
  variables, never from the image.

---

## 18. Current limitations

Stated plainly, because a reader will find them anyway.

1. **The studio dataset is synthetic.** Real cost history is exactly the kind
   of proprietary data no studio publishes. Every file is flagged
   `"_synthetic": true`. The data path is real; the numbers are invented.
2. **The public demo runs the bundled dataset**, not ClickHouse (§15).
3. **Run state is in memory.** A restart loses in-flight runs, and a
   multi-instance deployment would need a shared store.
4. **Scheduling is greedy, not optimal.** It packs by location and continuity,
   which is what a 1st AD does, but it does not solve for cast availability
   windows or location holds.
5. **Deployment on Google Cloud is configured but not the live path.** The
   scripts exist and the container is build- and run-tested; the public
   instance is on Render.
6. **Previz is optional and off by default.** It is not part of the judged core
   workflow, and the Veo model identifier in the default configuration targets
   the Vertex AI surface rather than the AI Studio one.
7. **A screenplay parse can produce duplicate scene numbers.** The UI detects
   this, disambiguates by location where it can, and surfaces the conflict
   rather than silently mislabelling — but the underlying breakdown is still
   ambiguous.

---

## 19. What we would build next

1. **Persist runs.** Move run state to a shared store so the service can scale
   horizontally and a run survives a restart.
2. **Emit a stable `scene_id`.** Removes the duplicate-scene-number ambiguity
   at the source rather than mitigating it in the UI.
3. **Include the event log in the downloaded package.** The provenance trace
   currently loses the tool step when a package is reopened; carrying the event
   log would close that gap.
4. **Richer scheduling constraints.** Cast availability windows, location
   holds, and company moves would move the solver from greedy packing toward
   something a production office could use directly.
5. **Streaming instead of polling.** Server-sent events would remove the fixed
   1.2 s latency in the live view.
6. **Write-back.** The system currently only reads studio data. Committing an
   approved schedule back would close the loop with production management
   tooling.

---

## Appendix: key constants

| Constant | Value | Location |
| --- | --- | --- |
| `MAX_REPLANS` | 2 | `backlot/orchestrator/line_producer.py` |
| `MAX_RISK_VALIDATION_RETRIES` | 2 | `backlot/orchestrator/line_producer.py` |
| `REPLAN_SHRINK_FACTOR` | 0.85 | `backlot/orchestrator/line_producer.py` |
| `MIN_PAGES_PER_DAY` | 2.0 | `backlot/orchestrator/line_producer.py` |
| `MAX_PAGES_PER_DAY_CEILING` | 8.0 | `backlot/orchestrator/line_producer.py` |
| `MAX_LLM_CALLS_PER_RUN` | 15 | `backlot/config.py` |
| `CLICKHOUSE_TOOL_FILTER` | `run_query`, `list_tables` | `backlot/agents/_state_instructions.py` |
| `google-adk` | 2.5.0 (pins `mcp` 1.29.0) | `requirements.txt` |
| `mcp-clickhouse` | 0.6.0 (requires `mcp` 2.x) | separate environment |
