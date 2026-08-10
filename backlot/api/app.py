"""FastAPI backend: upload a screenplay, watch the crew work live, approve
the budget band, get the assembled package back.

Run with `python run_server.py` (see repo root). The Budget/Resource agents
still need the MCP shim reachable — start it separately, same as
run_local.py: `python -m backlot.mcp_shim.server`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import DATA_DIR, OUTPUT_DIR
from .run_manager import get_run, start_run

STATIC_DIR = Path(__file__).resolve().parent / "static"
PREVIZ_DIR = OUTPUT_DIR / "previz"
PREVIZ_DIR.mkdir(parents=True, exist_ok=True)  # StaticFiles requires the dir to exist at mount time

app = FastAPI(title="BACKLOT")


class StartRunRequest(BaseModel):
    screenplay: str
    with_previz: bool = False


class ApprovalRequest(BaseModel):
    approved: bool
    reason: str = ""


@app.get("/api/sample-screenplay")
async def sample_screenplay() -> dict:
    path = DATA_DIR / "screenplays" / "sample_screenplay.txt"
    return {"screenplay": path.read_text(encoding="utf-8")}


@app.get("/api/replan-demo-screenplay")
async def replan_demo_screenplay() -> dict:
    # Purpose-built to trigger the Line Producer's bounded re-plan loop
    # (six consecutive EXT/NIGHT locations -> six consecutive night shoot
    # days, past the Risk agent's >3-consecutive-nights bar) -- see the
    # file's own header comment and backlot/orchestrator/line_producer.py.
    path = DATA_DIR / "screenplays" / "replan_demo_screenplay.txt"
    return {"screenplay": path.read_text(encoding="utf-8")}


@app.post("/api/runs")
async def create_run(req: StartRunRequest) -> dict:
    # Must be async: start_run() calls asyncio.create_task(), which needs a
    # running event loop on the CURRENT thread. FastAPI runs plain `def`
    # path operations in a worker thread via anyio.to_thread.run_sync,
    # which has no running loop of its own — that mismatch is exactly what
    # raised "RuntimeError: no running event loop" here before this fix.
    if not req.screenplay.strip():
        raise HTTPException(400, "screenplay text is required")
    state = start_run(req.screenplay, with_previz=req.with_previz)
    return {"run_id": state.run_id, "status": state.status}


@app.get("/api/runs/{run_id}")
async def read_run(run_id: str) -> dict:
    state = get_run(run_id)
    if state is None:
        raise HTTPException(404, "unknown run_id")
    return {
        "run_id": state.run_id,
        "status": state.status,
        "events": state.events,
        "package": state.package,
        "metrics": state.metrics,
        "error": state.error,
        "pending_budget": state.pending_budget,
    }


@app.post("/api/runs/{run_id}/approve")
async def approve_run(run_id: str, req: ApprovalRequest) -> dict:
    state = get_run(run_id)
    if state is None:
        raise HTTPException(404, "unknown run_id")
    if state.status != "awaiting_approval":
        raise HTTPException(409, f"run is not awaiting approval (status={state.status})")
    default_reason = "approved via UI" if req.approved else "rejected via UI"
    state.resolve_approval(req.approved, req.reason or default_reason)
    return {"ok": True}


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


# Serves icon files from the repo data directory so the UI can use
# the provided agent icons instead of inline SVGs.
app.mount("/icons", StaticFiles(directory=str(DATA_DIR / "icons")), name="icons")

# Serves generated storyboards/animatics so the UI can render them by URL
# (paths in PrevizAsset are server-local; this exposes them at
# /previz/<run_id>/<filename>). Registered before the catch-all static
# mount below.
app.mount("/previz", StaticFiles(directory=str(PREVIZ_DIR)), name="previz")

# Registered last: falls through to serving the static UI (index.html at
# "/") for anything the /api routes above didn't already match.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
