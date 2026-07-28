"""Metrics computation tests — built from hand-constructed Event objects,
no network, no live model calls."""

from google.adk.events import Event
from google.genai import types

from backlot.metrics import compute_run_metrics


def _call_event(author: str, ts: float, tool_name: str) -> Event:
    return Event(
        author=author,
        timestamp=ts,
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=tool_name, args={}))],
        ),
    )


def _response_event(author: str, ts: float, tool_name: str, response: dict) -> Event:
    return Event(
        author=author,
        timestamp=ts,
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(name=tool_name, response=response)
                )
            ],
        ),
    )


def _usage_event(author: str, ts: float, prompt: int, candidates: int) -> Event:
    return Event(
        author=author,
        timestamp=ts,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt,
            candidates_token_count=candidates,
            total_token_count=prompt + candidates,
        ),
    )


def test_counts_tool_calls_and_errors():
    events = [
        _call_event("budget_agent", 1.0, "get_comparable_costs"),
        _response_event("budget_agent", 1.5, "get_comparable_costs", {"matches": []}),
        _call_event("budget_agent", 2.0, "get_vendor_rates"),
        _response_event("budget_agent", 2.5, "get_vendor_rates", {"error": "MCP tool execution failed"}),
    ]
    metrics = compute_run_metrics(events, package=None)
    assert metrics["tool_calls"] == 2
    assert metrics["tool_errors"] == 1
    assert metrics["tool_success_rate"] == 0.5


def test_no_tool_calls_gives_none_success_rate():
    metrics = compute_run_metrics([], package=None)
    assert metrics["tool_calls"] == 0
    assert metrics["tool_success_rate"] is None


def test_sums_token_usage_across_events():
    events = [
        _usage_event("script_supervisor", 1.0, prompt=500, candidates=200),
        _usage_event("budget_agent", 2.0, prompt=300, candidates=100),
    ]
    metrics = compute_run_metrics(events, package=None)
    assert metrics["prompt_tokens"] == 800
    assert metrics["candidates_tokens"] == 300
    assert metrics["total_tokens"] == 1100


def test_latency_spans_first_to_last_timestamp_per_agent_and_overall():
    events = [
        _call_event("script_supervisor", 10.0, "n/a"),
        _call_event("script_supervisor", 12.0, "n/a"),
        _call_event("budget_agent", 15.0, "n/a"),
        _call_event("budget_agent", 18.0, "n/a"),
    ]
    metrics = compute_run_metrics(events, package=None)
    assert metrics["total_latency_seconds"] == 8.0
    assert metrics["per_agent_latency_seconds"]["script_supervisor"] == 2.0
    assert metrics["per_agent_latency_seconds"]["budget_agent"] == 3.0


def test_grounded_rate_from_package_budget_and_resources():
    package = {
        "budget": {
            "line_items": [
                {"label": "day 1", "grounded": True},
                {"label": "day 2", "grounded": False},
            ]
        },
        "resources": {
            "crew_picks": [{"need": "gaffer", "grounded": True}],
            "location_picks": [{"need": "lot", "grounded": True}],
        },
    }
    metrics = compute_run_metrics([], package=package)
    assert metrics["task_completed"] is True
    assert metrics["grounded_claims"] == 3
    assert metrics["ungrounded_claims"] == 1
    assert metrics["grounded_rate"] == 0.75


def test_task_not_completed_when_no_package():
    metrics = compute_run_metrics([], package=None)
    assert metrics["task_completed"] is False
    assert metrics["grounded_rate"] is None
