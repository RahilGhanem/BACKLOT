"""Line Producer orchestrator tests.

Construction test always runs (no network). The end-to-end test runs the
full crew (script -> breakdown -> schedule -> grounded budget/resources ->
package) against a real Gemini call and the auto-started MCP shim; skipped
automatically without credentials, same as test_script_supervisor.py.
"""

import pytest

from backlot.config import DATA_DIR, get_settings
from backlot.orchestrator import build_line_producer
from backlot.schemas import ProductionPackage


def test_build_line_producer_wires_the_full_crew():
    settings = get_settings()
    line_producer = build_line_producer(settings)

    assert line_producer.name == "line_producer"
    sub_names = [a.name for a in line_producer.sub_agents]
    assert sub_names == [
        "script_supervisor",
        "first_ad_scheduler",
        "budget_agent",
        "resource_agent",
        "package_assembler",
    ]


def _has_llm_credentials() -> bool:
    settings = get_settings()
    try:
        settings.require_llm_credentials()
        return True
    except RuntimeError:
        return False


@pytest.mark.skipif(
    not _has_llm_credentials(),
    reason="No Gemini credentials in .env — skipping live pipeline run.",
)
@pytest.mark.asyncio
async def test_pipeline_produces_a_grounded_scheduled_package(mcp_shim_process):
    from run_local import run_line_producer

    screenplay_path = DATA_DIR / "screenplays" / "sample_screenplay.txt"
    screenplay_text = screenplay_path.read_text(encoding="utf-8")

    package = await run_line_producer(screenplay_text)

    assert isinstance(package, ProductionPackage)
    assert package.schedule.total_shoot_days > 0
    assert package.schedule.unscheduled_scenes == []
    scheduled = {n for day in package.schedule.days for n in day.scene_numbers}
    expected = {s.scene_number for s in package.breakdown.scenes}
    assert scheduled == expected

    assert package.budget is not None
    assert package.resources is not None
