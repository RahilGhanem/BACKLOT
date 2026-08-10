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
from google.adk.events import Event, EventActions
from google.genai import types

from ..agents.approval_gate import ApprovalDecider, build_approval_gate, cli_approval_decider
from ..agents.budget import build_budget_agent
from ..agents.package_assembler import build_package_assembler
from ..agents.previz import build_previz_agent
from ..agents.resource import build_resource_agent
from ..agents.risk import build_risk_agent
from ..agents.script_supervisor import build_script_supervisor
from ..agents.scheduler import FirstADScheduler, build_first_ad_scheduler
from ..config import Settings
from ..schemas import Schedule, TimeOfDay
from ..tools.scheduler_solver import DEFAULT_MAX_PAGES_PER_DAY

MIN_PAGES_PER_DAY = 2.0
MAX_PAGES_PER_DAY_CEILING = 8.0
REPLAN_SHRINK_FACTOR = 0.85
MAX_REPLANS = 2

_NIGHT_BUCKET = {TimeOfDay.NIGHT, TimeOfDay.DUSK}


def _has_overloaded_day(schedule: Schedule) -> bool:
    return any(day.total_pages > schedule.max_pages_per_day for day in schedule.days)


def _longest_consecutive_night_run(schedule: Schedule) -> int:
    best = current = 0
    for day in schedule.days:
        current = current + 1 if day.time_of_day in _NIGHT_BUCKET else 0
        best = max(best, current)
    return best


def _schedule_fingerprint(schedule: Schedule) -> tuple:
    """A cheap structural signature for fixed-point detection: same day
    count, same location/time-of-day per day, same scenes per day. Two
    fingerprints matching means the last re-plan attempt was a no-op."""
    return tuple((day.location, day.time_of_day, tuple(day.scene_numbers)) for day in schedule.days)


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

        previous_fingerprint: tuple | None = None
        replan_log: list[str] = []

        for attempt in range(self.max_replans + 1):
            async for event in scheduler.run_async(ctx):
                yield event
            async for event in budget_agent.run_async(ctx):
                yield event
            async for event in risk_agent.run_async(ctx):
                yield event

            risk_data = ctx.session.state.get("risk_report") or {}
            schedule = Schedule.model_validate(ctx.session.state["schedule"])
            high_severity_open = any(
                flag.get("severity") == "high" for flag in risk_data.get("flags", [])
            )

            # Converge rather than run to a fixed count: stop as soon as
            # Risk stops asking for a re-plan, or has no high-severity item
            # left to justify one.
            if not risk_data.get("replan_requested") or not high_severity_open:
                break

            fingerprint = _schedule_fingerprint(schedule)
            if previous_fingerprint is not None and fingerprint == previous_fingerprint:
                # The last attempt's lever produced an identical schedule
                # (e.g. it already hit the min/max pages-per-day bound).
                # Looping again would just repeat the same no-op up to the
                # cap, so stop and say why instead of silently shipping a
                # schedule that still contradicts the open critique.
                replan_log.append(
                    "Re-plan requested again, but the schedule was unchanged from "
                    "the previous attempt (fixed point) -- stopping rather than "
                    "repeating a no-op."
                )
                break
            previous_fingerprint = fingerprint

            if attempt == self.max_replans:
                replan_log.append(
                    f"Hit the {self.max_replans}-replan cap without clearing every "
                    "high-severity flag. Last request: "
                    f"{risk_data.get('replan_reason') or '(no reason given)'}"
                )
                break

            # Pick the lever from what the produced schedule actually shows,
            # not from the Risk agent's free-text category -- this is a
            # deterministic solver problem, so it gets a deterministic fix.
            # Shrinking the per-day cap forces the Scheduler to split an
            # overloaded day, but it can only ever produce *more* days, so
            # it's the wrong lever for a long run of night days: that needs
            # a *larger* cap so a location's scenes can consolidate into
            # fewer, bigger days (distinct locations still never share a
            # day -- see scheduler_solver.py).
            night_run = _longest_consecutive_night_run(schedule)
            if _has_overloaded_day(schedule):
                scheduler.max_pages_per_day = max(
                    scheduler.max_pages_per_day * REPLAN_SHRINK_FACTOR, MIN_PAGES_PER_DAY
                )
                replan_log.append(
                    f"Attempt {attempt + 1}: an overloaded shoot day was found; "
                    f"shrinking the per-day cap to {scheduler.max_pages_per_day:.2f} pages."
                )
            elif night_run > 3:
                scheduler.max_pages_per_day = min(
                    scheduler.max_pages_per_day / REPLAN_SHRINK_FACTOR,
                    MAX_PAGES_PER_DAY_CEILING,
                )
                replan_log.append(
                    f"Attempt {attempt + 1}: {night_run} consecutive night days found; "
                    f"growing the per-day cap to {scheduler.max_pages_per_day:.2f} pages "
                    "so same-location night scenes can consolidate."
                )
            else:
                replan_log.append(
                    "Risk requested a re-plan, but the schedule shows neither an "
                    "overloaded day nor a long run of consecutive night days -- no "
                    "scheduling knob left to pull; stopping."
                )
                break

        if replan_log:
            # Surface the loop's own reasoning on the artifact itself
            # rather than dropping it once the next agent overwrites
            # 'schedule' in state -- this is what makes the difference
            # between "silently shipped a stale schedule" and "here's why".
            schedule_data = dict(ctx.session.state.get("schedule") or {})
            note = " | ".join(replan_log)
            schedule_data["solver_notes"] = f"{schedule_data.get('solver_notes', '')} {note}".strip()
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                content=types.Content(role="model", parts=[types.Part(text=note)]),
                actions=EventActions(state_delta={"schedule": schedule_data}),
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
