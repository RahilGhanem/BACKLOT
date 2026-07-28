"""Schema-only tests — no network, no model calls, always run."""

import pytest
from pydantic import ValidationError

from backlot.schemas import IntExt, SceneBreakdown, ScriptBreakdown, TimeOfDay


def _scene(**overrides) -> dict:
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
        vfx=[],
        stunts=[],
        estimated_page_count=0.5,
        notes="",
    )
    base.update(overrides)
    return base


def test_scene_breakdown_round_trips():
    scene = SceneBreakdown.model_validate(_scene())
    dumped = scene.model_dump()
    reloaded = SceneBreakdown.model_validate(dumped)
    assert reloaded == scene


def test_script_breakdown_holds_multiple_scenes():
    scenes = [
        _scene(),
        _scene(
            scene_number="2",
            sequence_index=1,
            slugline="INT. CARGO VAN - CONTINUOUS",
            int_ext=IntExt.INT,
            time_of_day=TimeOfDay.CONTINUOUS,
            location="CARGO VAN",
            cast=["MARA", "DESH"],
        ),
    ]
    breakdown = ScriptBreakdown.model_validate(
        {
            "title": "THE HANDOFF",
            "total_estimated_pages": 1.0,
            "scenes": scenes,
            "unique_cast": ["MARA", "DESH"],
            "unique_locations": ["INDUSTRIAL LOT", "CARGO VAN"],
        }
    )
    assert len(breakdown.scenes) == 2
    assert breakdown.scenes[1].int_ext is IntExt.INT


def test_invalid_int_ext_is_rejected():
    with pytest.raises(ValidationError):
        SceneBreakdown.model_validate(_scene(int_ext="INTERIOR"))


def test_minimum_page_count_is_not_enforced_by_type_but_zero_is_valid_float():
    # estimated_page_count is a float field; the *content* rule (never 0) is
    # instruction-level guidance to the model, not a schema constraint, since
    # the schema's job is shape validation, not creative judgment.
    scene = SceneBreakdown.model_validate(_scene(estimated_page_count=0.125))
    assert scene.estimated_page_count == 0.125
