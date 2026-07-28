"""The Resource Agent's output contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .provenance import GroundedRecord


class ResourcePick(BaseModel):
    need: str = Field(description="e.g. 'Gaffer, shoot days 1-2' or 'Location: industrial lot exterior'.")
    recommendation: str = Field(description="e.g. 'J. Alvarez (CR-101), $950/day, available in window'.")
    grounded: bool = Field(description="True only if source_records cites at least one real MCP record.")
    source_records: list[GroundedRecord] = Field(default_factory=list)
    notes: str = ""


class ResourcePlan(BaseModel):
    title: str
    crew_picks: list[ResourcePick]
    location_picks: list[ResourcePick]
