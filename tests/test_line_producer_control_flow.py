"""Deterministic tests of the Line Producer's control flow: the bounded
re-plan loop and the approval-gate skip of the Resource Agent.

These use fake, non-LLM stand-ins for the LLM-backed steps (script
supervisor, budget, risk, resource) so the loop/branching logic itself is
covered without needing Gemini credentials or a running MCP server —
Budget/Resource/Risk's *content* is covered separately by the live-gated
tests in test_grounded_agents.py and test_line_producer.py.
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import InMemoryRunner
from google.genai import types

from backlot.agents.approval_gate import build_approval_gate
from backlot.agents.package_assembler import build_package_assembler
from backlot.agents.scheduler import FirstADScheduler
from backlot.config import get_settings
from backlot.orchestrator.line_producer import MAX_REPLANS, REPLAN_SHRINK_FACTOR, LineProducer


class _FakeStateAgent(BaseAgent):
    """Writes a fixed state_delta each call. Repeats the last value once
    `values` is exhausted, so a single-entry list means "always this"."""

    state_key: str
    values: list[dict]
    call_count: int = 0

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        value = self.values[min(self.call_count, len(self.values) - 1)]
        self.call_count += 1
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=f"{self.name} ran")]),
            actions=EventActions(state_delta={self.state_key: value}),
        )


def _night_scene(number: str, seq: int, pages: float) -> dict:
    return {
        "scene_number": number,
        "sequence_index": seq,
        "slugline": "EXT. LOT - NIGHT",
        "int_ext": "EXT",
        "time_of_day": "NIGHT",
        "location": "LOT",
        "synopsis": "test",
        "cast": ["MARA"],
        "estimated_page_count": pages,
    }


# One oversized scene (6.0 pages, always > any cap the shrink lever
# produces below) keeps _has_overloaded_day() true every attempt so the
# loop always has a lever to pull; the three smaller scenes re-group
# differently as the cap shrinks from 5.0 -> 4.25 (one day of 3 -> a
# 2-and-1 split), which changes the schedule's fingerprint between attempt
# 0 and 1 so the loop doesn't hit the fixed-point break before the cap.
_BREAKDOWN = {
    "title": "TEST",
    "total_estimated_pages": 10.5,
    "scenes": [
        _night_scene("1", 0, 6.0),
        _night_scene("2", 1, 1.5),
        _night_scene("3", 2, 1.5),
        _night_scene("4", 3, 1.5),
    ],
    "unique_cast": ["MARA"],
    "unique_locations": ["LOT"],
}

_BUDGET = {"title": "TEST", "currency": "USD", "total_estimated_cost": 1000.0, "line_items": []}

_RISK_REPLAN = {
    "title": "TEST",
    "schedule_feasible": False,
    # A real RiskReport can't have replan_requested=True with zero flags
    # (see backlot/schemas/risk.py's validator) -- this fixture carries the
    # same high-severity, justified flag every attempt so it forces a
    # replan every time without being the exact contradiction Gap 3 outlaws.
    "flags": [
        {
            "category": "schedule_feasibility",
            "severity": "high",
            "description": "test forces a replan every time",
            "recommendation": "re-pack shoot days under a different pages-per-day budget",
        }
    ],
    "replan_requested": True,
    "replan_reason": "test forces a replan every time",
}

_RESOURCES = {"title": "TEST", "crew_picks": [], "location_picks": []}


def _build_test_line_producer(*, approved: bool) -> tuple[LineProducer, FirstADScheduler]:
    scheduler = FirstADScheduler(name="first_ad_scheduler", max_pages_per_day=5.0)
    decider = (lambda budget: (True, "test auto-approve")) if approved else (
        lambda budget: (False, "test auto-reject")
    )
    line_producer = LineProducer(
        name="line_producer",
        max_replans=MAX_REPLANS,
        sub_agents=[
            _FakeStateAgent(name="script_supervisor", state_key="breakdown", values=[_BREAKDOWN]),
            scheduler,
            _FakeStateAgent(name="budget_agent", state_key="budget", values=[_BUDGET]),
            _FakeStateAgent(name="risk_agent", state_key="risk_report", values=[_RISK_REPLAN]),
            build_approval_gate(decider=decider),
            _FakeStateAgent(name="resource_agent", state_key="resources", values=[_RESOURCES]),
            build_package_assembler(),
        ],
    )
    return line_producer, scheduler


async def _run(line_producer: LineProducer) -> dict:
    settings = get_settings()
    runner = InMemoryRunner(agent=line_producer, app_name=settings.app_name)
    await runner.session_service.create_session(
        app_name=settings.app_name, user_id="u", session_id="s"
    )
    message = types.Content(role="user", parts=[types.Part(text="go")])
    async for _event in runner.run_async(user_id="u", session_id="s", new_message=message):
        pass
    session = await runner.session_service.get_session(
        app_name=settings.app_name, user_id="u", session_id="s"
    )
    return session.state


@pytest.mark.asyncio
async def test_replan_loop_is_capped_and_shrinks_scheduler_budget():
    line_producer, scheduler = _build_test_line_producer(approved=True)
    initial_budget = scheduler.max_pages_per_day

    state = await _run(line_producer)

    # risk always requests a replan, so the loop must run exactly
    # max_replans + 1 times (capped), not forever.
    budget_agent = line_producer.sub_agents[2]
    assert budget_agent.call_count == MAX_REPLANS + 1

    expected_budget = initial_budget * (REPLAN_SHRINK_FACTOR ** MAX_REPLANS)
    assert scheduler.max_pages_per_day == pytest.approx(expected_budget)

    assert state["package"]["risk_report"]["replan_requested"] is True


@pytest.mark.asyncio
async def test_approved_budget_runs_resource_agent():
    line_producer, _scheduler = _build_test_line_producer(approved=True)
    state = await _run(line_producer)

    assert state["approval"]["approved"] is True
    assert state["package"]["resources"] is not None


@pytest.mark.asyncio
async def test_rejected_budget_skips_resource_agent():
    line_producer, _scheduler = _build_test_line_producer(approved=False)
    resource_agent = line_producer.sub_agents[5]

    state = await _run(line_producer)

    assert state["approval"]["approved"] is False
    assert resource_agent.call_count == 0
    assert state["package"]["resources"] is None
