"""The Line Producer: plans, sequences specialists, holds shared state.

ADK ships `SequentialAgent` for exactly this shape, but in the installed
ADK version (2.5.0) it is deprecated in favor of a newer graph-based
`Workflow` primitive that is not yet a drop-in `BaseAgent` (it can't be
handed to `Runner` or nested as a sub-agent the way `SequentialAgent` can).
Rather than build on a deprecated class or an early-stage API, the Line
Producer implements the same "run sub-agents in order, sharing session
state" behavior directly as a small custom `BaseAgent` — a few lines of
code, and it is exactly the "orchestrator holds shared state" role the
architecture assigns it, which also makes it the natural place to add the
human approval gate in Phase 4.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from ..agents.package_assembler import build_package_assembler
from ..agents.script_supervisor import build_script_supervisor
from ..agents.scheduler import build_first_ad_scheduler
from ..config import Settings
from ..tools.scheduler_solver import DEFAULT_MAX_PAGES_PER_DAY


class LineProducer(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        if not self.sub_agents:
            raise RuntimeError(f"{self.name} has no sub_agents configured.")

        for sub_agent in self.sub_agents:
            async for event in sub_agent.run_async(ctx):
                yield event


def build_line_producer(
    settings: Settings,
    max_pages_per_day: float = DEFAULT_MAX_PAGES_PER_DAY,
) -> LineProducer:
    return LineProducer(
        name="line_producer",
        description=(
            "Runs the deterministic pre-production spine: screenplay -> "
            "breakdown -> schedule -> assembled package."
        ),
        sub_agents=[
            build_script_supervisor(settings),
            build_first_ad_scheduler(max_pages_per_day=max_pages_per_day),
            build_package_assembler(),
        ],
    )
