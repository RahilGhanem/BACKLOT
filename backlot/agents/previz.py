"""The Previz Agent: generates a storyboard, a short animatic, and a
best-effort temp music cue for the opening scene, straight from the breakdown."""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import ConfigDict

from ..config import OUTPUT_DIR, Settings
from ..schemas import ScriptBreakdown
from ..schemas.breakdown import SceneBreakdown
from ..schemas.previz import PrevizAsset
from ..tools import previz_generation


def _build_prompt(scene: SceneBreakdown, title: str) -> str:
    parts = [
        f"Cinematic storyboard frame for the film '{title}'.",
        f"{scene.slugline}.",
        scene.synopsis,
    ]
    if scene.cast:
        parts.append(f"Featuring: {', '.join(scene.cast)}.")
    if scene.props:
        parts.append(f"Props: {', '.join(scene.props)}.")
    if scene.vehicles:
        parts.append(f"Vehicles: {', '.join(scene.vehicles)}.")
    parts.append("Photorealistic film still, moody lighting, widescreen.")
    return " ".join(parts)


class PrevizAgent(BaseAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    settings: Settings

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        breakdown_data = ctx.session.state.get("breakdown")
        if not breakdown_data:
            raise RuntimeError(f"{self.name} requires 'breakdown' in session state.")
        breakdown = ScriptBreakdown.model_validate(breakdown_data)
        opening_scene = min(breakdown.scenes, key=lambda s: s.sequence_index)

        prompt = _build_prompt(opening_scene, breakdown.title)
        out_dir = OUTPUT_DIR / "previz" / ctx.session.id

        warnings: list[str] = []
        storyboard_paths: list[str] = []
        animatic_path: str | None = None

        try:
            storyboard_paths = previz_generation.generate_storyboards(
                self.settings, prompt, out_dir
            )
        except Exception as exc:
            warnings.append(f"Storyboard generation failed: {exc}")

        try:
            animatic_path = await previz_generation.generate_animatic(
                self.settings, prompt, out_dir
            )
        except Exception as exc:
            warnings.append(f"Animatic generation failed: {exc}")

        music_path = await previz_generation.generate_music_cue(self.settings, prompt, out_dir)
        if music_path is None:
            warnings.append("Music cue not generated (see logs; Lyria call is best-effort).")

        asset = PrevizAsset(
            scene_number=opening_scene.scene_number,
            storyboard_paths=storyboard_paths,
            animatic_path=animatic_path,
            music_cue_path=music_path,
            prompts={"storyboard": prompt, "animatic": prompt, "music": prompt},
            warnings=warnings,
        )

        summary = (
            f"Previz for scene {opening_scene.scene_number}: "
            f"{len(storyboard_paths)} storyboard frame(s), "
            + ("animatic generated, " if animatic_path else "animatic skipped, ")
            + ("music cue generated" if music_path else "music cue skipped")
        )
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=summary)]),
            actions=EventActions(state_delta={"previz": asset.model_dump()}),
        )


def build_previz_agent(settings: Settings) -> PrevizAgent:
    return PrevizAgent(
        name="previz_agent",
        description=(
            "Generates a storyboard, animatic, and temp music cue for the "
            "opening scene via Imagen/Veo/Lyria."
        ),
        settings=settings,
    )
