"""The 1st-AD Scheduler: a deterministic, non-LLM agent."""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..schemas import ScriptBreakdown
from ..tools.scheduler_solver import DEFAULT_MAX_PAGES_PER_DAY, solve_schedule


class FirstADScheduler(BaseAgent):
    max_pages_per_day: float = DEFAULT_MAX_PAGES_PER_DAY

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        breakdown_data = ctx.session.state.get("breakdown")
        if breakdown_data is None:
            raise RuntimeError(
                f"{self.name} requires 'breakdown' in session state — run "
                "the Script Supervisor first."
            )

        breakdown = ScriptBreakdown.model_validate(breakdown_data)
        schedule = solve_schedule(breakdown, max_pages_per_day=self.max_pages_per_day)

        summary = (
            f"Scheduled {len(breakdown.scenes)} scene(s) across "
            f"{schedule.total_shoot_days} shoot day(s) "
            f"(target {self.max_pages_per_day} pages/day)."
        )
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=summary)]),
            actions=EventActions(state_delta={"schedule": schedule.model_dump()}),
        )


def build_first_ad_scheduler(
    max_pages_per_day: float = DEFAULT_MAX_PAGES_PER_DAY,
) -> FirstADScheduler:
    return FirstADScheduler(
        name="first_ad_scheduler",
        description=(
            "Builds an optimised stripboard shoot schedule from the scene "
            "breakdown by grouping scenes by location and day/night "
            "continuity under a pages-per-day budget."
        ),
        max_pages_per_day=max_pages_per_day,
    )
