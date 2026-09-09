"""Script Supervisor agent tests."""

import pytest

from backlot.agents.script_supervisor import build_script_supervisor
from backlot.config import DATA_DIR, get_settings
from backlot.schemas import ScriptBreakdown


def test_build_script_supervisor_is_configured_correctly():
    settings = get_settings()
    agent = build_script_supervisor(settings)

    assert agent.name == "script_supervisor"
    assert agent.output_key == "breakdown"
    assert agent.output_schema is ScriptBreakdown
    assert agent.model.model == settings.gemini_model_pro


def _has_llm_credentials() -> bool:
    settings = get_settings()
    try:
        settings.require_llm_credentials()
        return True
    except RuntimeError:
        return False


@pytest.mark.skipif(
    not _has_llm_credentials(),
    reason="No Gemini credentials in .env (GOOGLE_API_KEY or Vertex AI project) — skipping live call.",
)
@pytest.mark.asyncio
async def test_script_supervisor_breaks_down_sample_screenplay():
    from run_local import run_script_supervisor

    screenplay_path = DATA_DIR / "screenplays" / "sample_screenplay.txt"
    screenplay_text = screenplay_path.read_text(encoding="utf-8")

    breakdown = await run_script_supervisor(screenplay_text)

    assert isinstance(breakdown, ScriptBreakdown)
    assert len(breakdown.scenes) >= 4
    assert breakdown.total_estimated_pages > 0
    assert "MARA" in breakdown.unique_cast
    assert "DESH" in breakdown.unique_cast
    scene_indices = [s.sequence_index for s in breakdown.scenes]
    assert scene_indices == sorted(scene_indices)
