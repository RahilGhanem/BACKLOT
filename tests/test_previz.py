"""Previz tests.

Schema, prompt-building, and agent/pipeline wiring tests always run (no
network). The actual Imagen/Veo/Lyria calls cost real money and are never
exercised just because Gemini credentials are present — they require an
explicit second opt-in (RUN_PREVIZ_LIVE_TESTS=1) that nothing in this repo
sets automatically, so a routine `pytest -v` can never trigger billed
generative-media calls.
"""

from __future__ import annotations

import base64
import os

import pytest

from backlot.agents.previz import _build_prompt, build_previz_agent
from backlot.config import get_settings
from backlot.orchestrator import build_line_producer
from backlot.schemas import IntExt, PrevizAsset, TimeOfDay
from backlot.schemas.breakdown import SceneBreakdown
from backlot.tools import previz_generation


def _scene(**overrides) -> SceneBreakdown:
    base = dict(
        scene_number="1",
        sequence_index=0,
        slugline="EXT. INDUSTRIAL LOT - NIGHT",
        int_ext=IntExt.EXT,
        time_of_day=TimeOfDay.NIGHT,
        location="INDUSTRIAL LOT",
        synopsis="Mara waits in a van for Desh's signal.",
        cast=["MARA"],
        props=["WALKIE-TALKIE"],
        vehicles=["CARGO VAN"],
        estimated_page_count=0.5,
    )
    base.update(overrides)
    return SceneBreakdown.model_validate(base)


def test_build_prompt_includes_key_scene_details():
    prompt = _build_prompt(_scene(), "THE HANDOFF")
    assert "THE HANDOFF" in prompt
    assert "INDUSTRIAL LOT" in prompt
    assert "MARA" in prompt
    assert "CARGO VAN" in prompt
    assert "WALKIE-TALKIE" in prompt


def test_build_prompt_omits_empty_sections():
    prompt = _build_prompt(_scene(props=[], vehicles=[]), "THE HANDOFF")
    assert "Props:" not in prompt
    assert "Vehicles:" not in prompt


def test_build_previz_agent_is_configured_correctly():
    settings = get_settings()
    agent = build_previz_agent(settings)
    assert agent.name == "previz_agent"
    assert agent.settings is settings


def test_previz_asset_schema_round_trips():
    asset = PrevizAsset(
        scene_number="1",
        storyboard_paths=["output/previz/x/storyboard_1.png"],
        animatic_path="output/previz/x/animatic.mp4",
        music_cue_path=None,
        prompts={"storyboard": "a prompt"},
        warnings=["Music cue not generated (see logs)."],
    )
    reloaded = PrevizAsset.model_validate(asset.model_dump())
    assert reloaded == asset


def test_line_producer_excludes_previz_by_default():
    settings = get_settings()
    line_producer = build_line_producer(settings)
    names = [a.name for a in line_producer.sub_agents]
    assert "previz_agent" not in names


def test_line_producer_includes_previz_when_opted_in():
    settings = get_settings()
    line_producer = build_line_producer(settings, include_previz=True)
    names = [a.name for a in line_producer.sub_agents]
    assert names == [
        "script_supervisor",
        "previz_agent",
        "first_ad_scheduler",
        "budget_agent",
        "risk_agent",
        "approval_gate",
        "resource_agent",
        "package_assembler",
    ]


class _FakeVideo:
    def __init__(self, uri=None, video_bytes=None):
        self.uri = uri
        self.video_bytes = video_bytes


class _FakeGeneratedVideo:
    def __init__(self, video):
        self.video = video


class _FakeVideosResult:
    def __init__(self, generated_videos):
        self.generated_videos = generated_videos


class _FakeOperation:
    def __init__(self, done=True, error=None, result=None):
        self.done = done
        self.error = error
        self.result = result


class _FakeModels:
    """Fakes the one call generate_animatic() makes; the operation is
    already `done` so the poll loop's client.operations.get() is never
    reached, keeping the fake client minimal."""

    def __init__(self, operation):
        self._operation = operation

    def generate_videos(self, **kwargs):
        return self._operation


class _FakeFiles:
    def __init__(self, download_return=None, download_error=None):
        self._download_return = download_return
        self._download_error = download_error

    def download(self, *, file):
        if self._download_error is not None:
            raise self._download_error
        return self._download_return


class _FakeInteraction:
    def __init__(self, output_audio=None, output_image=None):
        self.output_audio = output_audio
        self.output_image = output_image


class _FakeInteractions:
    def __init__(self, interaction, capture: dict | None = None):
        self._interaction = interaction
        self._capture = capture if capture is not None else {}

    def create(self, **kwargs):
        self._capture.update(kwargs)
        return self._interaction


class _FakeSequencedInteractions:
    """Returns a different image per call, recording every call's kwargs --
    for generate_storyboards(), which calls create() once per requested
    image (see its docstring: output_image is singular, not a list)."""

    def __init__(self, image_data_values: list):
        self._image_data_values = list(image_data_values)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        data = self._image_data_values.pop(0)
        return _FakeInteraction(output_image=_FakeImageContent(data) if data else None)


class _FakeAudioContent:
    def __init__(self, data):
        self.data = data


class _FakeImageContent:
    def __init__(self, data):
        self.data = data


class _FakeGenaiClient:
    def __init__(self, models=None, files=None, interactions=None):
        self.models = models
        self.files = files
        self.interactions = interactions


# ---------- generate_animatic: GCS-URI-to-local-mp4 fix ----------
# These mock the google-genai Client entirely (via _build_client) so they
# run offline, with no network/credentials/billing -- they verify the
# *shape* of the fix (which client methods get called, what gets written to
# disk), not a live Vertex Veo call, which only Vertex billing can confirm.


@pytest.mark.asyncio
async def test_generate_animatic_downloads_gcs_uri_to_playable_local_mp4(tmp_path, monkeypatch):
    video = _FakeVideo(uri="gs://bucket/clip.mp4", video_bytes=None)
    operation = _FakeOperation(result=_FakeVideosResult([_FakeGeneratedVideo(video)]))
    fake_client = _FakeGenaiClient(
        models=_FakeModels(operation), files=_FakeFiles(download_return=b"fake mp4 bytes")
    )
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)

    path = await previz_generation.generate_animatic(get_settings(), "a prompt", tmp_path)

    assert path == str(tmp_path / "animatic.mp4")
    assert (tmp_path / "animatic.mp4").read_bytes() == b"fake mp4 bytes"
    assert not (tmp_path / "animatic.uri.txt").exists()


@pytest.mark.asyncio
async def test_generate_animatic_falls_back_to_uri_reference_if_download_fails(tmp_path, monkeypatch):
    video = _FakeVideo(uri="gs://bucket/clip.mp4", video_bytes=None)
    operation = _FakeOperation(result=_FakeVideosResult([_FakeGeneratedVideo(video)]))
    fake_client = _FakeGenaiClient(
        models=_FakeModels(operation),
        files=_FakeFiles(download_error=RuntimeError("permission denied")),
    )
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)

    path = await previz_generation.generate_animatic(get_settings(), "a prompt", tmp_path)

    assert path == str(tmp_path / "animatic.uri.txt")
    assert (tmp_path / "animatic.uri.txt").read_text(encoding="utf-8") == "gs://bucket/clip.mp4"


@pytest.mark.asyncio
async def test_generate_animatic_writes_inline_bytes_directly_when_present(tmp_path, monkeypatch):
    video = _FakeVideo(uri=None, video_bytes=b"inline bytes")
    operation = _FakeOperation(result=_FakeVideosResult([_FakeGeneratedVideo(video)]))
    fake_client = _FakeGenaiClient(models=_FakeModels(operation), files=_FakeFiles())
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)

    path = await previz_generation.generate_animatic(get_settings(), "a prompt", tmp_path)

    assert path == str(tmp_path / "animatic.mp4")
    assert (tmp_path / "animatic.mp4").read_bytes() == b"inline bytes"


# ---------- generate_music_cue: response_modalities + output_audio fix ----------


@pytest.mark.asyncio
async def test_generate_music_cue_decodes_base64_audio_and_writes_mp3(tmp_path, monkeypatch):
    raw_bytes = b"fake mp3 bytes"
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    capture: dict = {}
    fake_client = _FakeGenaiClient(
        interactions=_FakeInteractions(_FakeInteraction(_FakeAudioContent(encoded)), capture)
    )
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)
    settings = get_settings()

    path = await previz_generation.generate_music_cue(settings, "a prompt", tmp_path)

    assert path == str(tmp_path / "temp_cue.mp3")
    assert (tmp_path / "temp_cue.mp3").read_bytes() == raw_bytes
    # The two real bugs this fix corrects: response_modalities must be
    # passed (verified valid value against responsemodality.py), and input
    # must be the plain prompt string (verified valid against
    # interactionsinput.py), not the old role/content list shape.
    assert capture["response_modalities"] == ["audio"]
    assert capture["input"] == "a prompt"
    assert capture["model"] == settings.lyria_model


@pytest.mark.asyncio
async def test_generate_music_cue_returns_none_and_never_raises_when_no_audio(monkeypatch):
    fake_client = _FakeGenaiClient(interactions=_FakeInteractions(_FakeInteraction(output_audio=None)))
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)

    # out_dir=None is fine here: this path never reaches out_dir.mkdir()
    # since there's no audio to write -- if it did, this test would fail
    # loudly with an AttributeError instead of silently passing.
    path = await previz_generation.generate_music_cue(get_settings(), "a prompt", None)
    assert path is None


# ---------- generate_storyboards: Imagen -> gemini-2.5-flash-image migration ----------
# Same offline-mocking approach as the Veo/Lyria tests above: no network,
# no credentials, no billing. These verify the *shape* of the migration
# (call args, response parsing, file output), not a live call, which only
# Vertex billing can confirm.


def test_generate_storyboards_writes_decoded_images_and_uses_image_modality(tmp_path, monkeypatch):
    raw_bytes_1 = b"fake png bytes 1"
    raw_bytes_2 = b"fake png bytes 2"
    encoded_1 = base64.b64encode(raw_bytes_1).decode("ascii")
    encoded_2 = base64.b64encode(raw_bytes_2).decode("ascii")

    fake_interactions = _FakeSequencedInteractions([encoded_1, encoded_2])
    fake_client = _FakeGenaiClient(interactions=fake_interactions)
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)
    settings = get_settings()

    paths = previz_generation.generate_storyboards(settings, "a prompt", tmp_path, count=2)

    # correct file/output generation
    assert paths == [str(tmp_path / "storyboard_1.png"), str(tmp_path / "storyboard_2.png")]
    # correct base64 decoding + correct extraction of interaction.output_image.data
    assert (tmp_path / "storyboard_1.png").read_bytes() == raw_bytes_1
    assert (tmp_path / "storyboard_2.png").read_bytes() == raw_bytes_2
    # one create() call per requested image (output_image is singular, not a list)
    assert len(fake_interactions.calls) == 2
    for call in fake_interactions.calls:
        # correct response_modalities=["image"]
        assert call["response_modalities"] == ["image"]
        assert call["input"] == "a prompt"
        assert call["model"] == settings.imagen_model


def test_generate_storyboards_skips_images_with_no_output_image(tmp_path, monkeypatch):
    fake_client = _FakeGenaiClient(interactions=_FakeInteractions(_FakeInteraction(output_image=None)))
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)

    paths = previz_generation.generate_storyboards(get_settings(), "a prompt", tmp_path, count=2)

    assert paths == []
    assert list(tmp_path.iterdir()) == []


def test_generate_storyboards_propagates_api_failure_for_caller_to_handle(tmp_path, monkeypatch):
    """API/model failure handling: an error from the model call must
    propagate out of generate_storyboards() unhandled, exactly as the old
    generate_images() call would have -- previz.py's existing try/except
    around this call is what turns it into a warning; nothing here should
    swallow it first."""

    class _FailingInteractions:
        def create(self, **kwargs):
            raise RuntimeError("model unavailable")

    fake_client = _FakeGenaiClient(interactions=_FailingInteractions())
    monkeypatch.setattr(previz_generation, "_build_client", lambda settings: fake_client)

    with pytest.raises(RuntimeError, match="model unavailable"):
        previz_generation.generate_storyboards(get_settings(), "a prompt", tmp_path)


def _previz_live_tests_enabled() -> bool:
    return os.getenv("RUN_PREVIZ_LIVE_TESTS", "").strip().lower() in {"1", "true", "yes"}


@pytest.mark.skipif(
    not _previz_live_tests_enabled(),
    reason="Costs real money (Imagen/Veo). Set RUN_PREVIZ_LIVE_TESTS=1 to opt in explicitly.",
)
def test_live_storyboard_generation():
    from pathlib import Path

    from backlot.tools.previz_generation import generate_storyboards

    settings = get_settings()
    settings.require_llm_credentials()
    paths = generate_storyboards(settings, "a test prompt", Path("output/previz/_test"), count=1)
    assert paths
