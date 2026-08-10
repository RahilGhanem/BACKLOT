"""Confirms the re-plan demo screenplay's structural claim (Gap 4) with
the deterministic scheduler alone, no LLM/credentials needed: six
consecutive EXT/NIGHT scenes at six distinct locations must produce six
consecutive night shoot days, past the Risk agent's ">3 consecutive
night shoot days" bar for requesting a re-plan (see backlot/agents/risk.py
and backlot/orchestrator/line_producer.py's _longest_consecutive_night_run).

This doesn't run the real Script Supervisor against
data/screenplays/replan_demo_screenplay.txt (that needs live Gemini
credentials, covered separately by the live-gated pipeline tests) — it
hand-builds a breakdown with the same location/int-ext/time-of-day shape a
correct breakdown of that screenplay would have, so the scheduling
mechanics this demo depends on are verified on every `pytest -v`, not just
when credentials happen to be configured.
"""

from __future__ import annotations

from backlot.orchestrator.line_producer import _longest_consecutive_night_run
from backlot.schemas import IntExt, ScriptBreakdown, TimeOfDay
from backlot.schemas.breakdown import SceneBreakdown
from backlot.tools.scheduler_solver import DEFAULT_MAX_PAGES_PER_DAY, solve_schedule

_NIGHT_LOCATIONS = [
    "ROOFTOP HELIPAD",
    "FIRE ESCAPE ALLEY",
    "SUBWAY RAIL YARD",
    "RIVERFRONT PIER",
    "PARKING STRUCTURE ROOF",
    "ABANDONED RAIL BRIDGE",
]


def _replan_demo_breakdown() -> ScriptBreakdown:
    scenes = [
        SceneBreakdown(
            scene_number=str(i + 1),
            sequence_index=i,
            slugline=f"EXT. {loc} - NIGHT",
            int_ext=IntExt.EXT,
            time_of_day=TimeOfDay.NIGHT,
            location=loc,
            synopsis="Dax flees across the city.",
            cast=["DAX", "RUIZ"],
            estimated_page_count=1.0,
        )
        for i, loc in enumerate(_NIGHT_LOCATIONS)
    ]
    scenes.append(
        SceneBreakdown(
            scene_number="7",
            sequence_index=6,
            slugline="INT. SAFEHOUSE KITCHEN - DAY",
            int_ext=IntExt.INT,
            time_of_day=TimeOfDay.DAY,
            location="SAFEHOUSE KITCHEN",
            synopsis="Aftermath.",
            cast=["DAX", "RUIZ"],
            estimated_page_count=1.0,
        )
    )
    return ScriptBreakdown(
        title="THE LONG NIGHT",
        total_estimated_pages=sum(s.estimated_page_count for s in scenes),
        scenes=scenes,
        unique_cast=["DAX", "RUIZ"],
        unique_locations=_NIGHT_LOCATIONS + ["SAFEHOUSE KITCHEN"],
    )


def test_replan_demo_screenplay_shape_produces_six_consecutive_night_days():
    schedule = solve_schedule(_replan_demo_breakdown(), max_pages_per_day=DEFAULT_MAX_PAGES_PER_DAY)

    # Six distinct EXT/NIGHT locations never share a day (scheduler_solver.py
    # never packs two locations together), so each gets exactly one day, in
    # script order, ahead of the single closing DAY scene.
    assert schedule.total_shoot_days == 7
    night_days = schedule.days[:6]
    assert all(day.time_of_day is TimeOfDay.NIGHT for day in night_days)
    assert [day.location for day in night_days] == _NIGHT_LOCATIONS
    assert schedule.days[6].time_of_day is TimeOfDay.DAY

    night_run = _longest_consecutive_night_run(schedule)
    assert night_run == 6
    # This is exactly the condition backlot/orchestrator/line_producer.py
    # checks to pick the "grow the pages/day cap" re-plan lever, and the
    # threshold backlot/agents/risk.py's instruction tells the model to
    # request a re-plan for.
    assert night_run > 3
