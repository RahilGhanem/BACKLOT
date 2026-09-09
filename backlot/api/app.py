"""FastAPI backend: upload a screenplay, watch the crew work live, approve the
budget band, get the assembled package back."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import DATA_DIR, OUTPUT_DIR
from .run_manager import get_run, start_run

STATIC_DIR = Path(__file__).resolve().parent / "static"
PREVIZ_DIR = OUTPUT_DIR / "previz"
PREVIZ_DIR.mkdir(parents=True, exist_ok=True)

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
    path = DATA_DIR / "screenplays" / "replan_demo_screenplay.txt"
    return {"screenplay": path.read_text(encoding="utf-8")}


@app.post("/api/runs")
async def create_run(req: StartRunRequest) -> dict:
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


app.mount("/icons", StaticFiles(directory=str(DATA_DIR / "icons")), name="icons")

app.mount("/previz", StaticFiles(directory=str(PREVIZ_DIR)), name="previz")

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
