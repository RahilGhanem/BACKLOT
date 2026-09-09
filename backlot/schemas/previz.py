"""The Previz Agent's output contract."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PrevizAsset(BaseModel):
    scene_number: str
    storyboard_paths: list[str] = Field(default_factory=list)
    animatic_path: str | None = None
    music_cue_path: str | None = None
    prompts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal generation problems, e.g. a failed Lyria call.",
    )
