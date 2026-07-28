"""Deterministic stripboard scheduling solver.

This is the "custom Cloud Run tool" from the architecture doc, running
locally as a plain function during development (Phase 7 wraps it as a
Cloud Run service). Grouping and packing scenes into shoot days is a
constraint/greedy problem, not a language problem, so it stays out of the
LLM's hands entirely -- cheaper, and fully deterministic.
"""

from __future__ import annotations

from ..schemas.breakdown import IntExt, SceneBreakdown, ScriptBreakdown, TimeOfDay
from ..schemas.schedule import Schedule, ShootDay

DEFAULT_MAX_PAGES_PER_DAY = 5.0

_NIGHT_BUCKET = {TimeOfDay.NIGHT, TimeOfDay.DUSK}


def _continuity_bucket(scene: SceneBreakdown) -> str:
    """NIGHT or DAY grouping key.

    A real 1st AD never mixes night and day scenes in one shoot day because
    the lighting rig and crew call times differ; DAWN/CONTINUOUS/UNSPECIFIED
    default to DAY, the more common case.
    """
    return "NIGHT" if scene.time_of_day in _NIGHT_BUCKET else "DAY"


def solve_schedule(
    breakdown: ScriptBreakdown,
    max_pages_per_day: float = DEFAULT_MAX_PAGES_PER_DAY,
) -> Schedule:
    """Groups scenes by (location, day/night) and packs each group into
    consecutive shoot days under a page-count budget.

    Group order follows first-appearance order in the script, which
    consolidates repeat visits to the same location without otherwise
    reordering the shoot.
    """
    if max_pages_per_day <= 0:
        raise ValueError("max_pages_per_day must be positive.")

    groups: dict[tuple[str, str], list[SceneBreakdown]] = {}
    group_order: list[tuple[str, str]] = []
    for scene in sorted(breakdown.scenes, key=lambda s: s.sequence_index):
        key = (scene.location, _continuity_bucket(scene))
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(scene)

    days: list[ShootDay] = []
    day_number = 0

    for location, bucket in group_order:
        remaining = list(groups[(location, bucket)])
        while remaining:
            day_scenes: list[SceneBreakdown] = []
            day_pages = 0.0
            while remaining and (
                not day_scenes
                or day_pages + remaining[0].estimated_page_count <= max_pages_per_day
            ):
                scene = remaining.pop(0)
                day_scenes.append(scene)
                day_pages += scene.estimated_page_count

            day_number += 1
            int_ext_values = {s.int_ext for s in day_scenes}
            time_of_day_values = {s.time_of_day for s in day_scenes}
            cast_called = sorted({name for s in day_scenes for name in s.cast})

            notes = ""
            if day_pages > max_pages_per_day:
                notes = (
                    "A single scene exceeds the max-pages-per-day target; "
                    "flagged for Risk/Continuity review."
                )

            days.append(
                ShootDay(
                    day_number=day_number,
                    location=location,
                    int_ext=(
                        int_ext_values.pop()
                        if len(int_ext_values) == 1
                        else IntExt.INT_EXT
                    ),
                    time_of_day=(
                        time_of_day_values.pop()
                        if len(time_of_day_values) == 1
                        else (TimeOfDay.NIGHT if bucket == "NIGHT" else TimeOfDay.DAY)
                    ),
                    scene_numbers=[s.scene_number for s in day_scenes],
                    total_pages=round(day_pages, 3),
                    cast_called=cast_called,
                    notes=notes,
                )
            )

    return Schedule(
        title=breakdown.title,
        max_pages_per_day=max_pages_per_day,
        total_shoot_days=len(days),
        days=days,
        unscheduled_scenes=[],
        solver_notes=(
            f"Greedy location/continuity packer, {max_pages_per_day} "
            "pages/day target. Phase 3 grounds this target in the studio's "
            "own past-schedule data via MCP instead of a fixed constant."
        ),
    )
