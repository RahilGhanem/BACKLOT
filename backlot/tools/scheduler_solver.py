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
    """NIGHT or DAY grouping key for a scene with an explicit time_of_day.

    A real 1st AD never mixes night and day scenes in one shoot day because
    the lighting rig and crew call times differ; DAWN/UNSPECIFIED default to
    DAY, the more common case. CONTINUOUS is handled separately by the
    caller, since it doesn't carry its own time-of-day -- it means "same
    continuous timeframe as whatever scene came before."
    """
    return "NIGHT" if scene.time_of_day in _NIGHT_BUCKET else "DAY"


def solve_schedule(
    breakdown: ScriptBreakdown,
    max_pages_per_day: float = DEFAULT_MAX_PAGES_PER_DAY,
) -> Schedule:
    """Groups scenes by (location, day/night) and packs each group into
    the fewest shoot days a page-count budget allows.

    Group order follows first-appearance order in the script, which
    consolidates repeat visits to the same location without otherwise
    reordering the shoot. Different locations are never packed into the
    same shoot day (company moves), even when both are NIGHT scenes.
    """
    if max_pages_per_day <= 0:
        raise ValueError("max_pages_per_day must be positive.")

    groups: dict[tuple[str, str], list[SceneBreakdown]] = {}
    group_order: list[tuple[str, str]] = []
    prev_bucket = "DAY"
    for scene in sorted(breakdown.scenes, key=lambda s: s.sequence_index):
        # CONTINUOUS doesn't carry its own time-of-day -- it's the same
        # continuous timeframe as whatever scene came right before it (e.g.
        # cutting into a moving car mid-chase), so it inherits that scene's
        # bucket instead of defaulting to DAY. Getting this wrong silently
        # pulls a scene out of its actual night shoot and miscounts both
        # the day/night split and the resulting shoot-day total.
        bucket = prev_bucket if scene.time_of_day is TimeOfDay.CONTINUOUS else _continuity_bucket(scene)
        prev_bucket = bucket
        key = (scene.location, bucket)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(scene)

    days: list[ShootDay] = []
    day_number = 0

    for location, bucket in group_order:
        # First-fit-decreasing: pack the largest scenes first. Packing in
        # plain arrival order can strand a handful of small scenes on their
        # own extra day purely because of arrival order -- e.g. pages
        # [4, 4, 1, 1] under a 5-page cap take 3 days in arrival order but
        # only need 2 -- which shows up as spurious extra shoot days (and,
        # for a NIGHT group, spurious extra night days) with no scheduling
        # reason behind them.
        remaining = sorted(
            groups[(location, bucket)],
            key=lambda s: s.estimated_page_count,
            reverse=True,
        )
        while remaining:
            day_scenes: list[SceneBreakdown] = []
            day_pages = 0.0
            i = 0
            while i < len(remaining):
                scene = remaining[i]
                if not day_scenes or day_pages + scene.estimated_page_count <= max_pages_per_day:
                    day_scenes.append(scene)
                    day_pages += scene.estimated_page_count
                    remaining.pop(i)
                else:
                    i += 1
            # Packing order was by size, not story order; restore script
            # order within the day purely for readability (which day a
            # scene lands on is unaffected).
            day_scenes.sort(key=lambda s: s.sequence_index)

            day_number += 1
            int_ext_values = {s.int_ext for s in day_scenes}
            # CONTINUOUS doesn't carry real time-of-day info of its own (see
            # the grouping loop above, which already resolved it to this
            # day's actual NIGHT/DAY bucket) -- excluding it here means a
            # day made up entirely of CONTINUOUS scenes (or CONTINUOUS mixed
            # with one other exact match) still reports the bucket it was
            # actually scheduled under, via the fallback below, instead of
            # leaking the literal CONTINUOUS enum value into the output.
            time_of_day_values = {
                s.time_of_day for s in day_scenes if s.time_of_day is not TimeOfDay.CONTINUOUS
            }
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
