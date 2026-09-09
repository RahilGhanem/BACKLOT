"""Real ClickHouse-via-MCP integration tests."""

from __future__ import annotations

import json
import os
import socket
import uuid
from urllib.parse import urlparse

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from backlot.agents._mcp import build_mcp_toolset, check_mcp_reachable
from backlot.agents._state_instructions import CLICKHOUSE_TOOL_FILTER
from backlot.agents.budget import build_budget_agent
from backlot.agents.resource import build_resource_agent
from backlot.config import get_settings

CH_MCP_URL = (
    os.getenv("BACKLOT_TEST_CLICKHOUSE_MCP_URL")
    or os.getenv("CLICKHOUSE_MCP_URL")
    or ""
)
CH_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "backlot_studio")

EXPECTED_ROW_COUNTS = {
    "historical_costs": 6,
    "vendor_rates": 12,
    "crew_library": 10,
    "location_library": 6,
    "past_schedules": 5,
}


def _reachable(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


requires_clickhouse_mcp = pytest.mark.skipif(
    not _reachable(CH_MCP_URL),
    reason=(
        "No ClickHouse MCP server reachable — set "
        "BACKLOT_TEST_CLICKHOUSE_MCP_URL to a running mcp-clickhouse endpoint "
        "(see this module's docstring)."
    ),
)


def _clickhouse_settings():
    """Settings pinned to clickhouse mode regardless of what .env selects, so
    these tests don't depend on the developer's current MCP_MODE."""
    prev = {k: os.environ.get(k) for k in ("MCP_MODE", "CLICKHOUSE_MCP_URL", "CLICKHOUSE_DATABASE")}
    os.environ["MCP_MODE"] = "clickhouse"
    os.environ["CLICKHOUSE_MCP_URL"] = CH_MCP_URL
    os.environ["CLICKHOUSE_DATABASE"] = CH_DATABASE
    try:
        return get_settings()
    finally:
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _rows(tool_result) -> dict:
    """mcp-clickhouse returns its payload as a JSON string in a text part."""
    content = tool_result.get("content") or []
    for part in content:
        if part.get("type") == "text":
            return json.loads(part["text"])
    raise AssertionError(f"no text content in tool result: {tool_result!r}")


def _has_llm_credentials() -> bool:
    try:
        get_settings().require_llm_credentials()
        return True
    except RuntimeError:
        return False


requires_llm = pytest.mark.skipif(
    not _has_llm_credentials(), reason="No Gemini credentials in .env."
)


@requires_clickhouse_mcp
@pytest.mark.asyncio
async def test_official_mcp_server_exposes_exactly_the_filtered_tools():
    """run_query + list_tables must both exist on the real server, and the
    tool_filter must resolve to exactly those two — no more, no less."""
    settings = _clickhouse_settings()
    toolset = build_mcp_toolset(settings, tool_filter=CLICKHOUSE_TOOL_FILTER)
    try:
        names = {t.name for t in await toolset.get_tools()}
    finally:
        await toolset.close()

    assert names == set(CLICKHOUSE_TOOL_FILTER)
    assert "run_query" in names
    assert "list_tables" in names
    assert "run_chdb_select_query" not in names


@requires_clickhouse_mcp
@pytest.mark.asyncio
async def test_run_query_returns_real_rows_from_clickhouse():
    """Executes real SQL against the cluster and checks the loaded dataset."""
    settings = _clickhouse_settings()
    toolset = build_mcp_toolset(settings, tool_filter=CLICKHOUSE_TOOL_FILTER)
    try:
        tools = {t.name: t for t in await toolset.get_tools()}
        for table, expected in EXPECTED_ROW_COUNTS.items():
            result = await tools["run_query"].run_async(
                args={"query": f"SELECT count() AS c FROM {CH_DATABASE}.{table}"},
                tool_context=None,
            )
            payload = _rows(result)
            assert payload["rows"][0][0] == expected, (
                f"{table}: expected {expected} rows, got {payload['rows'][0][0]} "
                "— did scripts/clickhouse_load.sql load correctly?"
            )
    finally:
        await toolset.close()


@requires_clickhouse_mcp
@pytest.mark.asyncio
async def test_backquoted_keyword_columns_are_queryable():
    """`type` and `union` are ClickHouse keywords; the Resource Agent is
    instructed to back-quote them."""
    settings = _clickhouse_settings()
    toolset = build_mcp_toolset(settings, tool_filter=CLICKHOUSE_TOOL_FILTER)
    try:
        tools = {t.name: t for t in await toolset.get_tools()}
        result = await tools["run_query"].run_async(
            args={
                "query": (
                    f"SELECT location_id, `type` FROM {CH_DATABASE}.location_library "
                    "WHERE `type` ILIKE '%industrial%' ORDER BY location_id"
                )
            },
            tool_context=None,
        )
        payload = _rows(result)
        assert [r[0] for r in payload["rows"]] == ["LOC-01", "LOC-05"]

        crew = await tools["run_query"].run_async(
            args={"query": f"SELECT `union` FROM {CH_DATABASE}.crew_library WHERE crew_id='CR-101'"},
            tool_context=None,
        )
        assert _rows(crew)["rows"][0][0] == "IATSE Local 728"
    finally:
        await toolset.close()


def test_unreachable_clickhouse_fails_fast_with_actionable_error():
    """ClickHouse down must raise a clear error, not hang or silently fall
    back to invented numbers."""
    prev_mode = os.environ.get("MCP_MODE")
    prev_url = os.environ.get("CLICKHOUSE_MCP_URL")
    os.environ["MCP_MODE"] = "clickhouse"
    os.environ["CLICKHOUSE_MCP_URL"] = "http://127.0.0.1:1/mcp"
    try:
        settings = get_settings()
        with pytest.raises(RuntimeError, match="unreachable"):
            check_mcp_reachable(settings, timeout=1.0)
    finally:
        for key, value in (("MCP_MODE", prev_mode), ("CLICKHOUSE_MCP_URL", prev_url)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_clickhouse_mode_requires_its_configuration():
    """Missing CLICKHOUSE_MCP_URL must be a clear config error up front."""
    prev_mode = os.environ.get("MCP_MODE")
    prev_url = os.environ.get("CLICKHOUSE_MCP_URL")
    os.environ["MCP_MODE"] = "clickhouse"
    os.environ["CLICKHOUSE_MCP_URL"] = ""
    try:
        with pytest.raises(RuntimeError, match="CLICKHOUSE_MCP_URL"):
            get_settings().require_mcp_credentials()
    finally:
        for key, value in (("MCP_MODE", prev_mode), ("CLICKHOUSE_MCP_URL", prev_url)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _run_seeded(agent, seed_state: dict, prompt: str, output_key: str):
    settings = get_settings()
    runner = InMemoryRunner(agent=agent, app_name=settings.app_name)
    user_id, session_id = "ch-test", str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id, state=seed_state
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for _event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        pass
    session = await runner.session_service.get_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id
    )
    return session.state.get(output_key)


def _seed_breakdown_and_schedule() -> dict:
    """A deterministic breakdown + solver-produced schedule."""
    from backlot.schemas import IntExt, ScriptBreakdown, TimeOfDay
    from backlot.schemas.breakdown import SceneBreakdown
    from backlot.tools.scheduler_solver import solve_schedule

    scenes = [
        SceneBreakdown(
            scene_number="1",
            sequence_index=0,
            slugline="EXT. INDUSTRIAL LOT - NIGHT",
            int_ext=IntExt.EXT,
            time_of_day=TimeOfDay.NIGHT,
            location="INDUSTRIAL LOT",
            synopsis="A driver waits in a cargo van.",
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
        title="CLICKHOUSE INTEGRATION TEST",
        total_estimated_pages=2.5,
        scenes=scenes,
        unique_cast=["MARA", "LOU"],
        unique_locations=["INDUSTRIAL LOT", "GARAGE"],
    )
    schedule = solve_schedule(breakdown)
    return {"breakdown": breakdown.model_dump(), "schedule": schedule.model_dump()}


@requires_clickhouse_mcp
@requires_llm
@pytest.mark.asyncio
async def test_budget_agent_is_grounded_in_real_clickhouse_rows():
    """Every grounded amount must exist in ClickHouse, and the total must be
    the sum of the line items — proving nothing was invented."""
    settings = _clickhouse_settings()
    agent = build_budget_agent(settings)
    budget = await _run_seeded(
        agent, _seed_breakdown_and_schedule(), "Estimate the budget.", "budget"
    )
    assert budget is not None and budget["line_items"]

    grounded = [li for li in budget["line_items"] if li["grounded"]]
    assert grounded, "expected at least one ClickHouse-grounded line item"

    for item in grounded:
        assert item["source_records"], "a grounded item must cite its source"
        for record in item["source_records"]:
            assert record["source"].startswith(f"clickhouse:{CH_DATABASE}."), (
                f"expected ClickHouse provenance, got {record['source']!r}"
            )

    assert budget["total_estimated_cost"] == pytest.approx(
        sum(li["amount"] for li in budget["line_items"])
    )

    toolset = build_mcp_toolset(settings, tool_filter=CLICKHOUSE_TOOL_FILTER)
    try:
        tools = {t.name: t for t in await toolset.get_tools()}
        known = await tools["run_query"].run_async(
            args={
                "query": (
                    f"SELECT avg_cost_per_day FROM {CH_DATABASE}.historical_costs "
                    f"UNION ALL SELECT rate FROM {CH_DATABASE}.vendor_rates"
                )
            },
            tool_context=None,
        )
        real_amounts = {row[0] for row in _rows(known)["rows"]}
    finally:
        await toolset.close()

    for item in grounded:
        assert item["amount"] in real_amounts, (
            f"{item['label']}: {item['amount']} is not any value in ClickHouse — "
            "the model invented it"
        )


@requires_clickhouse_mcp
@requires_llm
@pytest.mark.asyncio
async def test_resource_agent_is_grounded_in_real_clickhouse_rows():
    settings = _clickhouse_settings()
    agent = build_resource_agent(settings)
    resources = await _run_seeded(
        agent, _seed_breakdown_and_schedule(), "Propose crew and locations.", "resources"
    )
    assert resources is not None
    picks = resources["crew_picks"] + resources["location_picks"]
    assert picks, "expected at least one resource pick"

    grounded = [p for p in picks if p["grounded"]]
    assert grounded, "expected at least one ClickHouse-grounded pick"
    for pick in grounded:
        assert pick["source_records"]
        for record in pick["source_records"]:
            assert record["source"].startswith(f"clickhouse:{CH_DATABASE}.")
