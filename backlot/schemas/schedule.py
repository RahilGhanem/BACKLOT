"""The 1st-AD Scheduler's output contract — a stripboard-style shoot schedule."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .breakdown import IntExt, TimeOfDay


class ShootDay(BaseModel):
    day_number: int
    location: str
    int_ext: IntExt
    time_of_day: TimeOfDay
    scene_numbers: list[str] = Field(description="SceneBreakdown.scene_number values shot this day.")
    total_pages: float
    cast_called: list[str] = Field(default_factory=list)
    notes: str = ""


class Schedule(BaseModel):
    title: str
    max_pages_per_day: float
    total_shoot_days: int
    days: list[ShootDay]
    unscheduled_scenes: list[str] = Field(
        default_factory=list,
        description="Scene numbers the solver could not place — should be empty in normal operation.",
    )
    solver_notes: str = ""
