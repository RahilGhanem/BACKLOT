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

from ..schemas import (
    BudgetEstimate,
    ProductionPackage,
    ResourcePlan,
    Schedule,
    ScriptBreakdown,
)


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

        # Budget/resources are optional in state: earlier phases (or a
        # Line Producer configured without the MCP-grounded agents) may
        # not have produced them yet.
        budget_data = ctx.session.state.get("budget")
        resources_data = ctx.session.state.get("resources")
        budget = BudgetEstimate.model_validate(budget_data) if budget_data else None
        resources = ResourcePlan.model_validate(resources_data) if resources_data else None

        package = ProductionPackage(
            title=breakdown.title,
            breakdown=breakdown,
            schedule=schedule,
            budget=budget,
            resources=resources,
        )

        summary = (
            f"Assembled production package for '{package.title}': "
            f"{len(breakdown.scenes)} scenes, {schedule.total_shoot_days} shoot days"
            + (f", ${budget.total_estimated_cost:,.0f} estimated" if budget else "")
            + "."
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
        description="Combines breakdown, schedule, budget, and resources (+ later: risk) into the final package.",
    )
