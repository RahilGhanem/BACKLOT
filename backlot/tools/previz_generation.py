"""Calls Imagen (storyboards) and Veo (animatic) via the google-genai
Client, plus a best-effort Lyria temp music cue. This is the generative-
previz component from the architecture (§7) — opt-in (Phase 6, "optional/
last") because it costs real money and a Veo clip can take minutes.

Every call shape below was checked against the installed google-genai
2.14.0 package's own source (not just docs, not guessed) — see each
function's docstring for what was verified and how.
"""

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
    """Storyboard frames via Gemini's native image generation ("Nano
    Banana"), not the discontinued Imagen `generate_images()` endpoint.

    Why the old implementation stopped being valid: every Imagen 4
    generate-family model — including "imagen-4.0-generate-001", the old
    settings.imagen_model default — has a "Discontinuation date: June 30,
    2026" per Google Cloud's own Vertex AI docs, already past as of this
    writing. `client.models.generate_images()` therefore has no
    currently-valid Imagen model left to call it with.

    The migration, verified against the installed google-genai 2.14.0
    source, not guessed:
    - "gemini-2.5-flash-image" is confirmed a real, valid `Model` value in
      google/genai/_gaos/types/interactions/model.py.
    - It is NOT callable via generate_images() — it goes through the same
      client.interactions.create() surface generate_music_cue() below
      uses, with response_modalities=["image"] (valid values, from
      responsemodality.py: "text"/"image"/"audio"/"video"/"document").
    - The image comes back on a single `interaction.output_image`
      (ImageContent, imagecontent.py) — singular, not a list — whose
      `.data` is a *base64-encoded str*, the same convention as
      AudioContent.data verified for the Lyria fix. One create() call
      therefore returns at most one image; `count` images means `count`
      calls, same total image count the old single multi-image call
      produced, just issued as `count` separate requests.
    - input=prompt as a plain string is confirmed valid against
      interactionsinput.py's InteractionsInputParam, same as the Lyria fix.

    Public signature/return type (list[str] of written file paths) is
    unchanged, so backlot/agents/previz.py needs no changes. Error handling
    is unchanged too: a failure still propagates out of this function
    exactly as the old generate_images() call would have, for previz.py's
    existing try/except to turn into a warning — nothing here swallows an
    exception that used to surface.
    """
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
    """Veo animatic clip.

    Verified against the installed google-genai 2.14.0 source
    (google/genai/models.py's Models.generate_videos / operations.py's
    Operations.get / types.py's GenerateVideosOperation/Video):
    - The long-running-operation call/poll shape (generate_videos ->
      operation.done -> client.operations.get(operation)) matches exactly.
    - `prompt=` is accepted but the source marks it "deprecated, please use
      source instead" -- switched to
      source=types.GenerateVideosSource(prompt=prompt) below.
    - settings.veo_model's default was "veo-3.1-generate-preview". Per
      Google Cloud's Vertex AI release notes, that PREVIEW endpoint was
      deprecated with a migration deadline of April 2, 2026 (already past)
      -- the stable GA id is "veo-3.1-generate-001" (see config.py).
    - CRITICAL fix: on Vertex, Video.video_bytes is commonly absent and
      Video.uri (a GCS object, e.g. "gs://...") is set instead -- the old
      code wrote a plain-text ".uri.txt" file that the UI silently skipped
      (renderPrevizTab() in app.js checks
      `!animatic_path.endsWith(".uri.txt")` before rendering a <video>),
      so the animatic "succeeded" but could never actually play. Fixed by
      downloading that GCS object to a real local animatic.mp4 via
      client.files.download(file=video) -- verified in the installed SDK's
      google/genai/files.py: Files.download() explicitly accepts a `Video`
      or `GeneratedVideo` object (not just a `File`) and returns its
      content as bytes. If the download itself fails (e.g. an IAM/network
      issue distinct from generation itself failing), falls back to the
      old .uri.txt reference rather than losing the URI entirely -- the
      caller (previz.py) still sees a real path either way and the UI
      still correctly skips a .uri.txt it can't play.
    """
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
    warning on any failure (storyboards/animatic still complete either way).

    Verified against the installed google-genai 2.14.0 source
    (google/genai/_gaos/types/interactions/*.py) -- the OLD code here had
    two real bugs, now fixed:
    1. response_modalities was never passed, so the model had no signal to
       return audio at all (valid values, from responsemodality.py:
       "text"/"image"/"audio"/"video"/"document" -- lowercase).
    2. Audio was read from `interaction.steps[*].content[*].audio_bytes`,
       which doesn't exist on the real Interaction type. The real shape
       (interaction.py) is a top-level `interaction.output_audio`
       (AudioContent), whose `.data` (audiocontent.py) is a *base64-encoded
       str*, not raw bytes -- needs base64.b64decode(), same encoding
       convention as `output_image.data` for image-modality interactions.
    "lyria-3-clip-preview" (settings.lyria_model's default) is confirmed
    valid: it's one of the literal values in google/genai/_gaos/types/
    interactions/model.py's Model type, so no id change needed here.
    input=prompt as a plain string is also confirmed valid --
    interactionsinput.py's InteractionsInputParam accepts `str` directly,
    simpler and more clearly-correct than the old role/content list shape
    (which didn't match any of that type's confirmed accepted shapes).
    """
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
