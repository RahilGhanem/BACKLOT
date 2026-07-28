"""Scheduler solver tests — pure logic, no network, no model calls."""

from backlot.schemas import IntExt, ScriptBreakdown, TimeOfDay
from backlot.schemas.breakdown import SceneBreakdown
from backlot.tools.scheduler_solver import solve_schedule


def _scene(scene_number, sequence_index, location, int_ext, time_of_day, pages, cast):
    return SceneBreakdown(
        scene_number=scene_number,
        sequence_index=sequence_index,
        slugline=f"{int_ext.value}. {location} - {time_of_day.value}",
        int_ext=int_ext,
        time_of_day=time_of_day,
        location=location,
        synopsis="test scene",
        cast=cast,
        estimated_page_count=pages,
    )


def _sample_breakdown() -> ScriptBreakdown:
    scenes = [
        _scene("1", 0, "LOT", IntExt.EXT, TimeOfDay.NIGHT, 2.0, ["MARA"]),
        _scene("2", 1, "LOT", IntExt.EXT, TimeOfDay.NIGHT, 2.0, ["DESH"]),
        _scene("3", 2, "LOT", IntExt.EXT, TimeOfDay.NIGHT, 2.0, ["MARA", "DESH"]),
        _scene("4", 3, "GARAGE", IntExt.INT, TimeOfDay.DAY, 6.5, ["LOU"]),
        _scene("5", 4, "HIGHWAY", IntExt.EXT, TimeOfDay.NIGHT, 1.0, ["MARA", "DESH"]),
    ]
    return ScriptBreakdown(
        title="TEST",
        total_estimated_pages=sum(s.estimated_page_count for s in scenes),
        scenes=scenes,
        unique_cast=["MARA", "DESH", "LOU"],
        unique_locations=["LOT", "GARAGE", "HIGHWAY"],
    )


def test_same_location_scenes_pack_into_one_day_under_budget():
    schedule = solve_schedule(_sample_breakdown(), max_pages_per_day=5.0)
    day1 = schedule.days[0]
    assert day1.location == "LOT"
    assert day1.scene_numbers == ["1", "2"]
    assert day1.total_pages == 4.0
    assert day1.int_ext is IntExt.EXT
    assert day1.time_of_day is TimeOfDay.NIGHT
    assert day1.cast_called == ["DESH", "MARA"]


def test_location_group_overflow_spills_to_a_new_day_same_location():
    schedule = solve_schedule(_sample_breakdown(), max_pages_per_day=5.0)
    day2 = schedule.days[1]
    assert day2.location == "LOT"
    assert day2.scene_numbers == ["3"]
    assert day2.total_pages == 2.0


def test_oversized_scene_gets_its_own_day_and_is_flagged():
    schedule = solve_schedule(_sample_breakdown(), max_pages_per_day=5.0)
    garage_day = next(d for d in schedule.days if d.location == "GARAGE")
    assert garage_day.scene_numbers == ["4"]
    assert garage_day.total_pages == 6.5
    assert "exceeds" in garage_day.notes


def test_never_mixes_two_locations_in_one_day():
    schedule = solve_schedule(_sample_breakdown(), max_pages_per_day=5.0)
    locations = [d.location for d in schedule.days]
    assert locations == ["LOT", "LOT", "GARAGE", "HIGHWAY"]


def test_all_scenes_are_scheduled_and_totals_match():
    breakdown = _sample_breakdown()
    schedule = solve_schedule(breakdown, max_pages_per_day=5.0)
    assert schedule.unscheduled_scenes == []
    assert schedule.total_shoot_days == len(schedule.days)
    scheduled_numbers = {n for day in schedule.days for n in day.scene_numbers}
    assert scheduled_numbers == {s.scene_number for s in breakdown.scenes}


def test_invalid_budget_raises():
    import pytest

    with pytest.raises(ValueError):
        solve_schedule(_sample_breakdown(), max_pages_per_day=0)
