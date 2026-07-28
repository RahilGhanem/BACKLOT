"""The Line Producer: plans, sequences specialists, holds shared state,
enforces the human approval gate, and assembles the final package.

ADK ships `SequentialAgent`/`LoopAgent` for pieces of this shape, but in the
installed ADK version (2.5.0) they are deprecated in favor of a newer
graph-based `Workflow` primitive that is not yet a drop-in `BaseAgent` (it
can't be handed to `Runner` or nested as a sub-agent). The Line Producer's
control flow is also no longer purely linear as of Phase 4 — it needs a
capped retry loop around Scheduler/Budget/Risk, a conditional skip of the
Resource Agent if the approval gate rejects the budget, and (Phase 6) an
optional Previz step — which a plain SequentialAgent couldn't express
anyway. So it stays a small, explicit custom `BaseAgent` that drives its
sub-agents directly, looked up by name rather than position so an optional
member (Previz) doesn't break positional unpacking.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from ..agents.approval_gate import ApprovalDecider, build_approval_gate, cli_approval_decider
from ..agents.budget import build_budget_agent
from ..agents.package_assembler import build_package_assembler
from ..agents.previz import build_previz_agent
from ..agents.resource import build_resource_agent
from ..agents.risk import build_risk_agent
from ..agents.script_supervisor import build_script_supervisor
from ..agents.scheduler import FirstADScheduler, build_first_ad_scheduler
from ..config import Settings
from ..tools.scheduler_solver import DEFAULT_MAX_PAGES_PER_DAY

MIN_PAGES_PER_DAY = 2.0
REPLAN_SHRINK_FACTOR = 0.85
MAX_REPLANS = 2


class LineProducer(BaseAgent):
    max_replans: int = MAX_REPLANS

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        by_name = {agent.name: agent for agent in self.sub_agents}
        script_supervisor = by_name["script_supervisor"]
        scheduler = by_name["first_ad_scheduler"]
        budget_agent = by_name["budget_agent"]
        risk_agent = by_name["risk_agent"]
        approval_gate = by_name["approval_gate"]
        resource_agent = by_name["resource_agent"]
        package_assembler = by_name["package_assembler"]
        previz_agent = by_name.get("previz_agent")  # opt-in, Phase 6
        assert isinstance(scheduler, FirstADScheduler)

        async for event in script_supervisor.run_async(ctx):
            yield event

        if previz_agent is not None:
            # Only needs the breakdown, so it runs as soon as that's ready
            # rather than waiting on scheduling/budget/risk.
            async for event in previz_agent.run_async(ctx):
                yield event

        for attempt in range(self.max_replans + 1):
            async for event in scheduler.run_async(ctx):
                yield event
            async for event in budget_agent.run_async(ctx):
                yield event
            async for event in risk_agent.run_async(ctx):
                yield event

            risk_data = ctx.session.state.get("risk_report") or {}
            if not risk_data.get("replan_requested") or attempt == self.max_replans:
                break
            # Bounded reflection loop: tighten the scheduler's constraint
            # and try again, rather than looping indefinitely.
            scheduler.max_pages_per_day = max(
                scheduler.max_pages_per_day * REPLAN_SHRINK_FACTOR, MIN_PAGES_PER_DAY
            )

        async for event in approval_gate.run_async(ctx):
            yield event

        approval = ctx.session.state.get("approval") or {}
        if approval.get("approved", False):
            async for event in resource_agent.run_async(ctx):
                yield event
        # else: resources stays absent from state; the Package Assembler
        # reflects a rejected/ungrounded-resources package rather than
        # silently proceeding to commit anything.

        async for event in package_assembler.run_async(ctx):
            yield event


def build_line_producer(
    settings: Settings,
    max_pages_per_day: float = DEFAULT_MAX_PAGES_PER_DAY,
    approval_decider: ApprovalDecider = cli_approval_decider,
    max_replans: int = MAX_REPLANS,
    include_previz: bool = False,
) -> LineProducer:
    sub_agents: list[BaseAgent] = [
        build_script_supervisor(settings),
        build_first_ad_scheduler(max_pages_per_day=max_pages_per_day),
        build_budget_agent(settings),
        build_risk_agent(settings),
        build_approval_gate(decider=approval_decider),
        build_resource_agent(settings),
        build_package_assembler(),
    ]
    if include_previz:
        sub_agents.insert(1, build_previz_agent(settings))

    return LineProducer(
        name="line_producer",
        description=(
            "Runs the pre-production crew: screenplay -> breakdown -> "
            "(optional previz) -> schedule -> grounded budget -> risk "
            "critique (with a bounded re-plan loop) -> human approval "
            "gate -> grounded resources -> assembled package."
        ),
        max_replans=max_replans,
        sub_agents=sub_agents,
    )
