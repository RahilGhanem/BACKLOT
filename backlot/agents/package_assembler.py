"""Assembles the compact per-stage state into the final ProductionPackage.

Also deterministic/non-LLM: by the time this agent runs, every value it
needs is already validated JSON sitting in session state.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..schemas import ProductionPackage, Schedule, ScriptBreakdown


class PackageAssembler(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        breakdown_data = ctx.session.state.get("breakdown")
        schedule_data = ctx.session.state.get("schedule")
        missing = [
            name
            for name, value in (("breakdown", breakdown_data), ("schedule", schedule_data))
            if value is None
        ]
        if missing:
            raise RuntimeError(
                f"{self.name} is missing required session state: {missing}. "
                "Run the earlier crew members first."
            )

        breakdown = ScriptBreakdown.model_validate(breakdown_data)
        schedule = Schedule.model_validate(schedule_data)
        package = ProductionPackage(
            title=breakdown.title, breakdown=breakdown, schedule=schedule
        )

        summary = (
            f"Assembled production package for '{package.title}': "
            f"{len(breakdown.scenes)} scenes, {schedule.total_shoot_days} shoot days."
        )
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=summary)]),
            actions=EventActions(state_delta={"package": package.model_dump()}),
        )


def build_package_assembler() -> PackageAssembler:
    return PackageAssembler(
        name="package_assembler",
        description="Combines breakdown + schedule (+ later: budget, resources, risk) into the final package.",
    )
