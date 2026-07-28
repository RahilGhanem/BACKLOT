"""Calls Imagen (storyboards) and Veo (animatic) via the google-genai
Client, plus a best-effort Lyria temp music cue. This is the generative-
previz component from the architecture (§7) — opt-in (Phase 6, "optional/
last") because it costs real money and a Veo clip can take minutes.

Imagen (`generate_images`) and Veo (`generate_videos`, a long-running
operation) are called through the verified, stable `client.models`
surface. Lyria, in the installed SDK, only exists behind a separate, much
newer "Interactions" API (`client.interactions`) that could not be
exercised against a live billed call in this environment — the shape used
below is a best-effort reading of that API's request/response models, not
something actually run end-to-end. It is wrapped so a Lyria failure
degrades gracefully (storyboards/animatic still complete) rather than
taking down the rest of previz. Verify against current docs before a live
demo.
"""

from __future__ import annotations

import asyncio
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
    client = _build_client(settings)
    response = client.models.generate_images(
        model=settings.imagen_model,
        prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=count),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for i, generated in enumerate(response.generated_images or []):
        image_bytes = generated.image.image_bytes if generated.image else None
        if not image_bytes:
            continue
        path = out_dir / f"storyboard_{i + 1}.png"
        path.write_bytes(image_bytes)
        paths.append(str(path))
    return paths


async def generate_animatic(settings: Settings, prompt: str, out_dir: Path) -> str | None:
    client = _build_client(settings)
    operation = client.models.generate_videos(
        model=settings.veo_model,
        prompt=prompt,
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
        # A GCS URI, not local bytes: record the reference rather than
        # silently claiming a local file that doesn't exist.
        path = out_dir / "animatic.uri.txt"
        path.write_text(video.uri, encoding="utf-8")
    else:
        return None
    return str(path)


async def generate_music_cue(settings: Settings, prompt: str, out_dir: Path) -> str | None:
    """Best-effort Lyria temp cue — see module docstring. Never raises;
    returns None and logs a warning on any failure."""
    try:
        client = _build_client(settings)
        interaction = client.interactions.create(
            model=settings.lyria_model,
            input=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )
        for step in getattr(interaction, "steps", None) or []:
            for item in getattr(step, "content", None) or []:
                audio_bytes = getattr(item, "audio_bytes", None) or getattr(item, "data", None)
                if audio_bytes:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    path = out_dir / "temp_cue.mp3"
                    path.write_bytes(audio_bytes)
                    return str(path)
        logger.warning("Lyria interaction completed but returned no audio content.")
        return None
    except Exception as exc:  # noqa: BLE001 - intentionally broad, see docstring
        logger.warning("Lyria music cue generation failed (non-fatal): %s", exc)
        return None
