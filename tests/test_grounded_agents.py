"""Budget/Resource agent tests."""

import uuid

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from backlot.agents._state_instructions import CLICKHOUSE_TOOL_FILTER
from backlot.agents.budget import build_budget_agent
from backlot.agents.resource import build_resource_agent
from backlot.config import get_settings
from backlot.schemas import IntExt, ScriptBreakdown, TimeOfDay
from backlot.schemas.breakdown import SceneBreakdown
from backlot.tools.scheduler_solver import solve_schedule


def _seed_breakdown_and_schedule() -> dict:
    scenes = [
        SceneBreakdown(
            scene_number="1",
            sequence_index=0,
            slugline="EXT. INDUSTRIAL LOT - NIGHT",
            int_ext=IntExt.EXT,
            time_of_day=TimeOfDay.NIGHT,
            location="INDUSTRIAL LOT",
            synopsis="A getaway driver waits in a van.",
            cast=["MARA"],
            vehicles=["CARGO VAN"],
            estimated_page_count=1.5,
        ),
        SceneBreakdown(
            scene_number="2",
            sequence_index=1,
            slugline="INT. GARAGE - DAY",
            int_ext=IntExt.INT,
            time_of_day=TimeOfDay.DAY,
            location="GARAGE",
            synopsis="A buyer inspects the goods.",
            cast=["MARA", "LOU"],
            estimated_page_count=1.0,
        ),
    ]
    breakdown = ScriptBreakdown(
        title="TEST",
        total_estimated_pages=2.5,
        scenes=scenes,
        unique_cast=["MARA", "LOU"],
        unique_locations=["INDUSTRIAL LOT", "GARAGE"],
    )
    schedule = solve_schedule(breakdown)
    return {"breakdown": breakdown.model_dump(), "schedule": schedule.model_dump()}


def test_build_budget_agent_scopes_tools_to_cost_lookups():
    """Tool scoping must hold in whichever MCP_MODE .env selects."""
    settings = get_settings()
    agent = build_budget_agent(settings)
    assert agent.name == "budget_agent"
    assert agent.output_key == "budget"
    toolset = agent.tools[0]
    expected = (
        set(CLICKHOUSE_TOOL_FILTER)
        if settings.mcp_mode == "clickhouse"
        else {"get_comparable_costs", "get_vendor_rates"}
    )
    assert set(toolset.tool_filter) == expected


def test_build_resource_agent_scopes_tools_to_crew_and_locations():
    settings = get_settings()
    agent = build_resource_agent(settings)
    assert agent.name == "resource_agent"
    assert agent.output_key == "resources"
    toolset = agent.tools[0]
    expected = (
        set(CLICKHOUSE_TOOL_FILTER)
        if settings.mcp_mode == "clickhouse"
        else {"find_available_crew", "find_locations"}
    )
    assert set(toolset.tool_filter) == expected


def test_clickhouse_tool_filter_matches_official_mcp_clickhouse_tools():
    """Pinned against github.com/ClickHouse/mcp-clickhouse's registered tool
    names (verified in its mcp_server.py: `name="run_query"`)."""
    assert set(CLICKHOUSE_TOOL_FILTER) == {"run_query", "list_tables"}


def _has_llm_credentials() -> bool:
    settings = get_settings()
    try:
        settings.require_llm_credentials()
        return True
    except RuntimeError:
        return False


async def _run_seeded(agent, seed_state: dict, prompt: str, output_key: str):
    settings = get_settings()
    runner = InMemoryRunner(agent=agent, app_name=settings.app_name)
    user_id, session_id = "test-user", str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id, state=seed_state
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass
    session = await runner.session_service.get_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id
    )
    return session.state.get(output_key)


@pytest.mark.skipif(
    not _has_llm_credentials(),
    reason="No Gemini credentials in .env — skipping live MCP-grounded call.",
)
@pytest.mark.asyncio
async def test_budget_agent_grounds_estimate_via_mcp(mcp_shim_process):
    settings = get_settings()
    agent = build_budget_agent(settings)
    result = await _run_seeded(
        agent, _seed_breakdown_and_schedule(), "Estimate the budget.", "budget"
    )
    assert result is not None
    assert result["line_items"], "expected at least one budget line item"
    assert any(item["grounded"] for item in result["line_items"]), (
        "expected at least one line item grounded via an MCP tool call"
    )
    for item in result["line_items"]:
        if item["grounded"]:
            assert item["source_records"], "grounded line item must cite a source record"


@pytest.mark.skipif(
    not _has_llm_credentials(),
    reason="No Gemini credentials in .env — skipping live MCP-grounded call.",
)
@pytest.mark.asyncio
async def test_resource_agent_grounds_picks_via_mcp(mcp_shim_process):
    settings = get_settings()
    agent = build_resource_agent(settings)
    result = await _run_seeded(
        agent, _seed_breakdown_and_schedule(), "Propose crew and locations.", "resources"
    )
    assert result is not None
    all_picks = result["crew_picks"] + result["location_picks"]
    assert all_picks, "expected at least one resource pick"
    assert any(p["grounded"] for p in all_picks), (
        "expected at least one pick grounded via an MCP tool call"
    )
