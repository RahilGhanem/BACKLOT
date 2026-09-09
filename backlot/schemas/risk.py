"""The Risk/Continuity Agent's output contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _require_every_property(schema: dict) -> None:
    """Mark every property as required in the transmitted JSON schema."""
    schema["required"] = list(schema.get("properties", {}).keys())


_SHORT_TEXT = 400
_LONG_TEXT = 600


class RiskFlag(BaseModel):
    model_config = ConfigDict(json_schema_extra=_require_every_property)

    category: str = Field(max_length=60, description="e.g. 'weather', 'permit', 'overtime', 'continuity', 'schedule_feasibility'.")
    severity: str = Field(max_length=10, description="'low', 'medium', or 'high'.")
    description: str = Field(max_length=_SHORT_TEXT)
    affected_scene_numbers: list[str] = Field(default_factory=list)
    affected_shoot_days: list[int] = Field(default_factory=list)
    recommendation: str = Field(default="", max_length=_SHORT_TEXT)


class RiskReport(BaseModel):
    model_config = ConfigDict(json_schema_extra=_require_every_property)

    title: str = Field(max_length=200)
    schedule_feasible: bool = Field(
        description="False if the schedule should be re-planned before proceeding."
    )
    flags: list[RiskFlag] = Field(default_factory=list)
    replan_requested: bool = Field(
        default=False,
        description="True asks the Line Producer to re-run the Scheduler with tightened constraints.",
    )
    replan_reason: str = Field(default="", max_length=_LONG_TEXT)

    @model_validator(mode="after")
    def _replan_or_infeasible_must_be_justified(self) -> "RiskReport":
        """Reject self-contradictory reports."""
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
