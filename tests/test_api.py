"""FastAPI backend tests.

Routing/validation tests always run (no network, no live model). The
full-flow test exercises the actual HTTP approval relay (POST /approve
unblocking the async decider awaited inside the running pipeline task) end
to end and is skipped without Gemini credentials + the MCP shim, same as
the other live-gated tests.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backlot.api.app import app
from backlot.config import get_settings


def test_sample_screenplay_endpoint_returns_text():
    with TestClient(app) as client:
        res = client.get("/api/sample-screenplay")
        assert res.status_code == 200
        assert "THE HANDOFF" in res.json()["screenplay"]


def test_create_run_rejects_empty_screenplay():
    with TestClient(app) as client:
        res = client.post("/api/runs", json={"screenplay": "   "})
        assert res.status_code == 400


def test_unknown_run_id_returns_404():
    with TestClient(app) as client:
        assert client.get("/api/runs/does-not-exist").status_code == 404
        assert (
            client.post("/api/runs/does-not-exist/approve", json={"approved": True}).status_code
            == 404
        )


def test_index_html_is_served():
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "BACKLOT" in res.text


def _has_llm_credentials() -> bool:
    settings = get_settings()
    try:
        settings.require_llm_credentials()
        return True
    except RuntimeError:
        return False


@pytest.mark.skipif(
    not _has_llm_credentials(),
    reason="No Gemini credentials in .env — skipping live API run.",
)
def test_full_run_via_http_including_approval_relay(mcp_shim_process):
    with TestClient(app) as client:
        sample = client.get("/api/sample-screenplay").json()["screenplay"]
        started = client.post("/api/runs", json={"screenplay": sample})
        assert started.status_code == 200
        run_id = started.json()["run_id"]

        deadline = time.monotonic() + 90
        status = None
        while time.monotonic() < deadline:
            status = client.get(f"/api/runs/{run_id}").json()["status"]
            if status in ("awaiting_approval", "completed", "rejected", "error"):
                break
            time.sleep(1)
        assert status == "awaiting_approval", f"expected awaiting_approval, got {status}"

        approved = client.post(f"/api/runs/{run_id}/approve", json={"approved": True})
        assert approved.status_code == 200

        deadline = time.monotonic() + 60
        final = None
        while time.monotonic() < deadline:
            final = client.get(f"/api/runs/{run_id}").json()
            if final["status"] in ("completed", "rejected", "error"):
                break
            time.sleep(1)

        assert final["status"] == "completed", final.get("error")
        assert final["package"]["approval"]["approved"] is True
        assert final["package"]["resources"] is not None
        assert final["metrics"]["task_completed"] is True
