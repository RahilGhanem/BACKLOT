"""The Script Supervisor's output contract.

This is the first compact artifact in the crew's shared state. Downstream
agents (Scheduler, Budget, Resource, Risk) consume ScriptBreakdown JSON only —
never the raw screenplay — which is the token-efficiency story: the whole
script is read once, by one agent.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IntExt(str, Enum):
    INT = "INT"
    EXT = "EXT"
    INT_EXT = "INT/EXT"


class TimeOfDay(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    DAWN = "DAWN"
    DUSK = "DUSK"
    CONTINUOUS = "CONTINUOUS"
    UNSPECIFIED = "UNSPECIFIED"


class SceneBreakdown(BaseModel):
    scene_number: str = Field(
        description="Slugline scene number as printed in the script, e.g. '1' or '12A'."
    )
    sequence_index: int = Field(
        description="0-based order of this scene in the script, for stable sorting."
    )
    slugline: str = Field(description="The full scene heading as written, e.g. 'INT. WAREHOUSE - NIGHT'.")
    int_ext: IntExt
    time_of_day: TimeOfDay
    location: str = Field(description="Normalized location name, e.g. 'WAREHOUSE'.")
    synopsis: str = Field(description="One-sentence summary of what happens in the scene.")
    cast: list[str] = Field(default_factory=list, description="Speaking/featured character names.")
    props: list[str] = Field(default_factory=list)
    vehicles: list[str] = Field(default_factory=list)
    vfx: list[str] = Field(default_factory=list, description="VFX/SFX needs, e.g. 'muzzle flash', 'rain'.")
    stunts: list[str] = Field(default_factory=list)
    estimated_page_count: float = Field(
        description="Screenplay page length in eighths (e.g. 1.125 = 1 1/8 pages)."
    )
    notes: str = Field(default="", description="Anything a 1st AD would flag: night exterior, minors, animals, etc.")


class ScriptBreakdown(BaseModel):
    title: str
    total_estimated_pages: float
    scenes: list[SceneBreakdown]
    unique_cast: list[str] = Field(default_factory=list)
    unique_locations: list[str] = Field(default_factory=list)
