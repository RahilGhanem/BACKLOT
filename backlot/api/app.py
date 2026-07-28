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
def sample_screenplay() -> dict:
    path = DATA_DIR / "screenplays" / "sample_screenplay.txt"
    return {"screenplay": path.read_text(encoding="utf-8")}


@app.post("/api/runs")
def create_run(req: StartRunRequest) -> dict:
    if not req.screenplay.strip():
        raise HTTPException(400, "screenplay text is required")
    state = start_run(req.screenplay, with_previz=req.with_previz)
    return {"run_id": state.run_id, "status": state.status}


@app.get("/api/runs/{run_id}")
def read_run(run_id: str) -> dict:
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
def approve_run(run_id: str, req: ApprovalRequest) -> dict:
    state = get_run(run_id)
    if state is None:
        raise HTTPException(404, "unknown run_id")
    if state.status != "awaiting_approval":
        raise HTTPException(409, f"run is not awaiting approval (status={state.status})")
    default_reason = "approved via UI" if req.approved else "rejected via UI"
    state.resolve_approval(req.approved, req.reason or default_reason)
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# Serves generated storyboards/animatics so the UI can render them by URL
# (paths in PrevizAsset are server-local; this exposes them at
# /previz/<run_id>/<filename>). Registered before the catch-all static
# mount below.
app.mount("/previz", StaticFiles(directory=str(PREVIZ_DIR)), name="previz")

# Registered last: falls through to serving the static UI (index.html at
# "/") for anything the /api routes above didn't already match.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
