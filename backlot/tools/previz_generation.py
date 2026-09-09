"""Generative previz: storyboard frames, an animatic clip, and a temp music
cue for the opening scene."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path

from google import genai
from google.genai import types

from ..config import Settings

logger = logging.getLogger(__name__)

VEO_POLL_INTERVAL_SECONDS = 10
VEO_POLL_TIMEOUT_SECONDS = 300


def _build_client(settings: Settings) -> genai.Client:
    if settings.use_vertexai:
        return genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
    return genai.Client(api_key=settings.google_api_key)


def generate_storyboards(
    settings: Settings, prompt: str, out_dir: Path, count: int = 2
) -> list[str]:
    """Storyboard frames via Gemini's native image generation."""
    client = _build_client(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for i in range(count):
        interaction = client.interactions.create(
            model=settings.imagen_model,
            input=prompt,
            response_modalities=["image"],
        )
        image = interaction.output_image
        if not image or not image.data:
            continue
        path = out_dir / f"storyboard_{i + 1}.png"
        path.write_bytes(base64.b64decode(image.data))
        paths.append(str(path))
    return paths


async def generate_animatic(settings: Settings, prompt: str, out_dir: Path) -> str | None:
    """Veo animatic clip, written to animatic.mp4."""
    client = _build_client(settings)
    operation = client.models.generate_videos(
        model=settings.veo_model,
        source=types.GenerateVideosSource(prompt=prompt),
        config=types.GenerateVideosConfig(number_of_videos=1, duration_seconds=8),
    )

    deadline = time.monotonic() + VEO_POLL_TIMEOUT_SECONDS
    while not operation.done:
        if time.monotonic() > deadline:
            raise TimeoutError("Veo video generation did not finish in time.")
        await asyncio.sleep(VEO_POLL_INTERVAL_SECONDS)
        operation = client.operations.get(operation)

    if operation.error:
        raise RuntimeError(f"Veo video generation failed: {operation.error}")

    result = operation.result
    if not result or not result.generated_videos:
        return None

    video = result.generated_videos[0].video
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "animatic.mp4"
    if video.video_bytes:
        path.write_bytes(video.video_bytes)
    elif video.uri:
        try:
            video_bytes = client.files.download(file=video)
        except Exception as exc:
            logger.warning(
                "Veo returned a GCS URI (%s) but downloading it failed (%s); "
                "falling back to recording the URI reference only, which "
                "won't be playable in the UI.",
                video.uri,
                exc,
            )
            path = out_dir / "animatic.uri.txt"
            path.write_text(video.uri, encoding="utf-8")
            return str(path)
        path.write_bytes(video_bytes)
    else:
        return None
    return str(path)


async def generate_music_cue(settings: Settings, prompt: str, out_dir: Path) -> str | None:
    """Best-effort Lyria temp cue — never raises; returns None and logs a
    warning on any failure (storyboards/animatic still complete either way)."""
    try:
        client = _build_client(settings)
        interaction = client.interactions.create(
            model=settings.lyria_model,
            input=prompt,
            response_modalities=["audio"],
        )
        audio = interaction.output_audio
        if audio and audio.data:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / "temp_cue.mp3"
            path.write_bytes(base64.b64decode(audio.data))
            return str(path)
        logger.warning("Lyria interaction completed but returned no audio content.")
        return None
    except Exception as exc:  # noqa: BLE001 - intentionally broad, see docstring
        logger.warning("Lyria music cue generation failed (non-fatal): %s", exc)
        return None
