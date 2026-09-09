"""The human approval gate: a producer signs off the budget band before
resources are committed (in this system, before the Resource Agent proposes
concrete crew/vendor/location picks)."""

from __future__ import annotations

import inspect
from typing import Awaitable, AsyncGenerator, Callable, Union

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import ConfigDict

ApprovalDecider = Callable[[dict], Union["tuple[bool, str]", Awaitable["tuple[bool, str]"]]]


def cli_approval_decider(budget: dict) -> tuple[bool, str]:
    print("\n--- APPROVAL GATE ---")
    total = budget.get("total_estimated_cost", 0)
    currency = budget.get("currency", "USD")
    print(f"Estimated total cost: {currency} {total:,.2f}")
    ungrounded = [li for li in budget.get("line_items", []) if not li.get("grounded")]
    if ungrounded:
        print(f"WARNING: {len(ungrounded)} line item(s) are NOT grounded in MCP data:")
        for li in ungrounded:
            print(f"  - {li.get('label')}: {li.get('notes')}")
    answer = input(
        "Approve this budget band and proceed to resource booking? [y/N]: "
    ).strip().lower()
    approved = answer in ("y", "yes")
    reason = "approved by producer via CLI" if approved else "rejected by producer via CLI"
    return approved, reason


def auto_approve_decider(budget: dict) -> tuple[bool, str]:
    """Always approves — for tests, CI, and non-interactive demo runs."""
    return True, "auto-approved (non-interactive mode)"


class ApprovalGate(BaseAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    decider: ApprovalDecider

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        budget_data = ctx.session.state.get("budget") or {}
        result = self.decider(budget_data)
        if inspect.isawaitable(result):
            approved, reason = await result
        else:
            approved, reason = result

        summary = f"Budget {'APPROVED' if approved else 'REJECTED'}: {reason}"
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=summary)]),
            actions=EventActions(
                state_delta={"approval": {"approved": approved, "reason": reason}}
            ),
        )


def build_approval_gate(decider: ApprovalDecider = cli_approval_decider) -> ApprovalGate:
    return ApprovalGate(
        name="approval_gate",
        description=(
            "Human approval gate: a producer signs off the budget band "
            "before the crew proposes concrete resource picks."
        ),
        decider=decider,
    )
