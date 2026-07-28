"""The Risk/Continuity Agent's output contract.

This is one of only two agents in the crew doing open-ended reasoning
(the other is the Script Supervisor) — everything else is either
deterministic or a grounded, tool-scoped lookup.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskFlag(BaseModel):
    category: str = Field(description="e.g. 'weather', 'permit', 'overtime', 'continuity', 'schedule_feasibility'.")
    severity: str = Field(description="'low', 'medium', or 'high'.")
    description: str
    affected_scene_numbers: list[str] = Field(default_factory=list)
    affected_shoot_days: list[int] = Field(default_factory=list)
    recommendation: str = ""


class RiskReport(BaseModel):
    title: str
    schedule_feasible: bool = Field(
        description="False if the schedule should be re-planned before proceeding."
    )
    flags: list[RiskFlag] = Field(default_factory=list)
    replan_requested: bool = Field(
        default=False,
        description="True asks the Line Producer to re-run the Scheduler with tightened constraints.",
    )
    replan_reason: str = ""
