"""The final artifact the Line Producer assembles and returns to the user.

Grows with each phase: Phase 2 adds breakdown + schedule; Phase 3 adds
budget/resources; Phase 4 adds the risk report.
"""

from __future__ import annotations

from pydantic import BaseModel

from .breakdown import ScriptBreakdown
from .schedule import Schedule


class ProductionPackage(BaseModel):
    title: str
    breakdown: ScriptBreakdown
    schedule: Schedule
