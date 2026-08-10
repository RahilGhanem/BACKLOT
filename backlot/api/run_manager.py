"""Tracks background pipeline runs for the API layer.

Runs live in an in-memory dict — this is a local-dev/demo simplification,
not a production run store. Phase 7's deploy notes cover what changes for
Agent Engine (managed sessions) and Firestore-backed run state.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from google.adk.agents import RunConfig
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..agents._mcp import check_mcp_reachable
from ..config import get_settings
from ..metrics import compute_run_metrics
from ..orchestrator import build_line_producer

# Every key an agent might write into shared session state, in pipeline
# order — snapshotted after every event so the UI can render each crew
# member's output the moment it's ready, not just once the whole run ends.
_ARTIFACT_KEYS = [
    "breakdown",
    "previz",
    "schedule",
    "budget",
    "risk_report",
    "approval",
    "resources",
]


@dataclass
class RunState:
    run_id: str
    status: str = "running"  # running | awaiting_approval | completed | rejected | error
    events: list[dict] = field(default_factory=list)
    partial_state: dict = field(default_factory=dict)  # live snapshot, see _ARTIFACT_KEYS
    package: dict | None = None
    metrics: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    approval_event: asyncio.Event = field(default_factory=asyncio.Event)
    approval_result: tuple[bool, str] | None = None
    pending_budget: dict | None = None  # so the UI can show real line items at the gate

    def resolve_approval(self, approved: bool, reason: str) -> None:
        self.approval_result = (approved, reason)
        self.approval_event.set()


_RUNS: dict[str, RunState] = {}


def get_run(run_id: str) -> RunState | None:
    return _RUNS.get(run_id)


def _summarize_event(event: Event) -> dict:
    text = None
    if event.content and event.content.parts:
        for part in event.content.parts:
            if part.text:
                text = part.text
                break
    return {
        "author": event.author,
        "timestamp": event.timestamp,
        "text": text,
        "tool_calls": [fc.name for fc in event.get_function_calls()],
    }


def _make_http_decider(state: RunState):
    async def _decider(budget: dict) -> tuple[bool, str]:
        state.status = "awaiting_approval"
        state.pending_budget = budget
        state.approval_event.clear()
        await state.approval_event.wait()
        state.status = "running"
        assert state.approval_result is not None
        return state.approval_result

    return _decider


async def _execute(state: RunState, screenplay_text: str, with_previz: bool) -> None:
    settings = get_settings()
    try:
        settings.require_llm_credentials()
        # check_mcp_reachable does a blocking socket connect; run it off the
        # event loop thread so it can't stall other in-flight requests/runs
        # for up to its timeout.
        await asyncio.to_thread(check_mcp_reachable, settings)
    except RuntimeError as exc:
        state.status = "error"
        state.error = str(exc)
        return

    agent = build_line_producer(
        settings, approval_decider=_make_http_decider(state), include_previz=with_previz
    )
    runner = InMemoryRunner(agent=agent, app_name=settings.app_name)
    user_id = "web-user"
    await runner.session_service.create_session(
        app_name=settings.app_name, user_id=user_id, session_id=state.run_id
    )
    message = types.Content(role="user", parts=[types.Part(text=screenplay_text)])

    # Hard safety cap: a runaway tool-calling loop shouldn't be able to
    # burn through a whole day's free-tier quota in a single run (default
    # RunConfig.max_llm_calls is 500 — far too loose for e.g. a
    # 20-requests/day account).
    run_config = RunConfig(max_llm_calls=settings.max_llm_calls_per_run)

    raw_events: list[Event] = []
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=state.run_id, new_message=message, run_config=run_config
        ):
            raw_events.append(event)
            state.events.append(_summarize_event(event))
            # Cheap (in-memory session service): snapshot known artifact
            # keys after every event so the UI can render each crew
            # member's output the moment it lands, not just at the end.
            session = await runner.session_service.get_session(
                app_name=settings.app_name, user_id=user_id, session_id=state.run_id
            )
            if session:
                state.partial_state = {
                    key: session.state[key] for key in _ARTIFACT_KEYS if key in session.state
                }
    except Exception as exc:  # surface to the UI rather than losing the run silently
        state.status = "error"
        state.error = str(exc)
        state.metrics = compute_run_metrics(raw_events, state.partial_state)
        return

    session = await runner.session_service.get_session(
        app_name=settings.app_name, user_id=user_id, session_id=state.run_id
    )
    package = session.state.get("package") if session else None
    state.package = package
    state.metrics = compute_run_metrics(raw_events, package or state.partial_state)

    if package is None:
        state.status = "error"
        state.error = state.error or "Pipeline finished without producing a package."
        return

    approval = package.get("approval") or {}
    state.status = "completed" if approval.get("approved") else "rejected"


def start_run(screenplay_text: str, with_previz: bool = False) -> RunState:
    run_id = str(uuid.uuid4())
    state = RunState(run_id=run_id)
    _RUNS[run_id] = state
    asyncio.create_task(_execute(state, screenplay_text, with_previz))
    return state
