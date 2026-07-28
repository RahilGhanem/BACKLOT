"""Builds InstructionProvider callables that inject compact JSON state.

ADK's built-in `{var_name}` instruction templating stringifies session
state via Python's str(dict) (single-quoted repr), not proper JSON. For
agents that need to reason over structured upstream artifacts (Budget,
Resource), a hand-rolled json.dumps gives the model cleaner, more reliably
parsed input.
"""

from __future__ import annotations

import json
from typing import Callable

from google.adk.agents.readonly_context import ReadonlyContext


def with_state_json(base_instruction: str, *state_keys: str) -> Callable[[ReadonlyContext], str]:
    def _build(ctx: ReadonlyContext) -> str:
        sections = [base_instruction]
        for key in state_keys:
            value = ctx.state.get(key)
            if value is not None:
                sections.append(f"\n## {key} (JSON)\n{json.dumps(value, indent=2)}")
        return "\n".join(sections)

    return _build
