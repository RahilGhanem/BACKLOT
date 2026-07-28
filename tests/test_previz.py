"""Previz tests.

Schema, prompt-building, and agent/pipeline wiring tests always run (no
network). The actual Imagen/Veo/Lyria calls cost real money and are never
exercised just because Gemini credentials are present — they require an
explicit second opt-in (RUN_PREVIZ_LIVE_TESTS=1) that nothing in this repo
sets automatically, so a routine `pytest -v` can never trigger billed
generative-media calls.
"""

from __future__ import annotations

import os

import pytest

from backlot.agents.previz import _build_prompt, build_previz_agent
from backlot.config import get_settings
from backlot.orchestrator import build_line_producer
from backlot.schemas import IntExt, PrevizAsset, TimeOfDay
from backlot.schemas.breakdown import SceneBreakdown


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
