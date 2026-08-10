"""The Risk/Continuity Agent's output contract.

This is one of only two agents in the crew doing open-ended reasoning
(the other is the Script Supervisor) — everything else is either
deterministic or a grounded, tool-scoped lookup.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


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

    @model_validator(mode="after")
    def _replan_or_infeasible_must_be_justified(self) -> "RiskReport":
        """Structurally rules out the exact contradiction this schema used to
        allow: schedule_feasible=False and/or replan_requested=True with
        zero supporting flags (see backlot/agents/risk.py's INSTRUCTION,
        which tells the model these rules exist so a well-behaved model
        should never actually trip this).
        """
        if (self.replan_requested or not self.schedule_feasible) and not self.flags:
            raise ValueError(
                "schedule_feasible=False or replan_requested=True requires at "
                "least one flag in `flags` justifying it -- zero flags is a "
                "contradictory report."
            )
        if self.replan_requested:
            justifying = [
                f
                for f in self.flags
                if f.severity == "high" and f.description.strip() and f.recommendation.strip()
            ]
            if not justifying:
                raise ValueError(
                    "replan_requested=True requires at least one flag with "
                    "severity='high', a non-empty description, and a "
                    "non-empty recommendation -- a re-plan request must be "
                    "justified by a concrete, actionable flag."
                )
        return self
