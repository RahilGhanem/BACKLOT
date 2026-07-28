"""Computes the evaluation scorecard from the report's Evaluation Plan (§11),
directly from the ADK event log a run produces — no separate instrumentation
pass needed. Metrics that need data this project doesn't have (a
hand-labeled retrieval precision@k set, a naive-baseline schedule
comparison) are intentionally left out rather than faked; "report the
number honestly" applies to what's missing too.
"""

from __future__ import annotations

from google.adk.events import Event


def compute_run_metrics(events: list[Event], package: dict | None) -> dict:
    tool_calls = 0
    tool_errors = 0
    prompt_tokens = 0
    candidates_tokens = 0
    total_tokens = 0
    per_agent_timestamps: dict[str, list[float]] = {}

    for event in events:
        per_agent_timestamps.setdefault(event.author, []).append(event.timestamp)

        tool_calls += len(event.get_function_calls())
        for response in event.get_function_responses():
            payload = response.response
            if isinstance(payload, dict) and payload.get("error"):
                tool_errors += 1

        usage = event.usage_metadata
        if usage is not None:
            prompt_tokens += usage.prompt_token_count or 0
            candidates_tokens += usage.candidates_token_count or 0
            total_tokens += usage.total_token_count or 0

    all_timestamps = [ts for spans in per_agent_timestamps.values() for ts in spans]
    total_latency_s = (max(all_timestamps) - min(all_timestamps)) if all_timestamps else 0.0
    per_agent_latency_s = {
        agent: round(max(spans) - min(spans), 2)
        for agent, spans in per_agent_timestamps.items()
    }

    grounded_count = 0
    ungrounded_count = 0
    if package:
        for item in (package.get("budget") or {}).get("line_items", []):
            grounded_count += 1 if item.get("grounded") else 0
            ungrounded_count += 0 if item.get("grounded") else 1
        resources = package.get("resources") or {}
        for pick in resources.get("crew_picks", []) + resources.get("location_picks", []):
            grounded_count += 1 if pick.get("grounded") else 0
            ungrounded_count += 0 if pick.get("grounded") else 1

    grounded_total = grounded_count + ungrounded_count

    return {
        "task_completed": package is not None,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "tool_success_rate": (
            round((tool_calls - tool_errors) / tool_calls, 3) if tool_calls else None
        ),
        "prompt_tokens": prompt_tokens or None,
        "candidates_tokens": candidates_tokens or None,
        "total_tokens": total_tokens or None,
        "total_latency_seconds": round(total_latency_s, 2),
        "per_agent_latency_seconds": per_agent_latency_s,
        "grounded_claims": grounded_count,
        "ungrounded_claims": ungrounded_count,
        "grounded_rate": (
            round(grounded_count / grounded_total, 3) if grounded_total else None
        ),
    }
