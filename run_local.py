"""Local dev entrypoint for the BACKLOT crew.

Usage:
    python run_local.py
        Runs the full Line Producer spine (script -> breakdown -> schedule
        -> package) and writes output/package.json.

    python run_local.py --stage breakdown
        Runs only the Script Supervisor and writes output/breakdown.json.

    python run_local.py --screenplay path/to/script.txt --out path/to/out.json

This bypasses Agent Engine entirely and uses ADK's InMemoryRunner + an
in-memory session, so it works with nothing more than a Gemini credential
in .env. Progress prints live as each crew member runs; if a run stops
early (e.g. a quota limit), whatever state was produced up to that point
is still written out rather than lost.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from google.adk.agents import RunConfig
from google.adk.agents.base_agent import BaseAgent
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from backlot.agents._mcp import check_mcp_reachable
from backlot.agents.approval_gate import auto_approve_decider, cli_approval_decider
from backlot.config import DATA_DIR, OUTPUT_DIR, get_settings
from backlot.orchestrator import build_line_producer
from backlot.agents.script_supervisor import build_script_supervisor
from backlot.schemas import ScriptBreakdown

# Every key an agent might write into shared session state, in pipeline
# order — used to salvage a partial package if a run stops early.
_ARTIFACT_KEYS = [
    "breakdown",
    "previz",
    "schedule",
    "budget",
    "risk_report",
    "approval",
    "resources",
]


def _print_event(event: Event) -> None:
    text = None
    if event.content and event.content.parts:
        for part in event.content.parts:
            if part.text:
                text = part.text
                break
    tool_calls = [fc.name for fc in event.get_function_calls()]
    line = f"  [{event.author}]"
    if tool_calls:
        line += f" calling {', '.join(tool_calls)}"
    if text:
        line += f" {text}"
    print(line)


async def _run_agent(
    agent: BaseAgent, screenplay_text: str
) -> tuple[dict, Exception | None]:
    """Runs `agent`, printing live progress, and returns whatever known
    artifact keys exist in session state afterward, plus the exception if
    the run stopped early (a quota limit, a model error, etc.) — partial
    results are still useful and are never silently discarded.
    """
    settings = get_settings()
    runner = InMemoryRunner(agent=agent, app_name=settings.app_name)

    user_id = "local-dev"
    session_id = str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id
    )

    message = types.Content(role="user", parts=[types.Part(text=screenplay_text)])

    # Hard safety cap: a runaway tool-calling loop shouldn't be able to
    # burn through a whole day's free-tier quota in a single run (default
    # RunConfig.max_llm_calls is 500 — far too loose for e.g. a
    # 20-requests/day account).
    run_config = RunConfig(max_llm_calls=settings.max_llm_calls_per_run)

    error: Exception | None = None
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message, run_config=run_config
        ):
            _print_event(event)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not swallowed
        error = exc
        print(f"\n  !! Run stopped early: {exc}\n")

    session = await runner.session_service.get_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id
    )
    state = session.state if session else {}
    artifacts = {key: state[key] for key in _ARTIFACT_KEYS if key in state}
    return artifacts, error


async def run_script_supervisor(screenplay_text: str) -> ScriptBreakdown:
    settings = get_settings()
    settings.require_llm_credentials()
    agent = build_script_supervisor(settings)
    artifacts, error = await _run_agent(agent, screenplay_text)
    if "breakdown" not in artifacts:
        raise RuntimeError(
            "Script Supervisor produced no 'breakdown' state."
            + (f" Underlying error: {error}" if error else "")
        )
    return ScriptBreakdown.model_validate(artifacts["breakdown"])


async def run_line_producer(
    screenplay_text: str, auto_approve: bool = False, with_previz: bool = False
) -> tuple[dict, Exception | None]:
    """Returns the raw artifact dict (not a validated ProductionPackage) so
    a partial run — some steps done, one still missing — can still be
    written out. main() assembles/prints from whatever's present.
    """
    settings = get_settings()
    settings.require_llm_credentials()
    check_mcp_reachable(settings)
    decider = auto_approve_decider if auto_approve else cli_approval_decider
    agent = build_line_producer(settings, approval_decider=decider, include_previz=with_previz)
    return await _run_agent(agent, screenplay_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BACKLOT crew locally.")
    parser.add_argument(
        "--stage",
        choices=["breakdown", "pipeline"],
        default="pipeline",
        help="'breakdown' runs only the Script Supervisor; 'pipeline' (default) "
        "runs the full Line Producer spine.",
    )
    parser.add_argument(
        "--screenplay",
        type=Path,
        default=DATA_DIR / "screenplays" / "sample_screenplay.txt",
        help="Path to a plain-text screenplay.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the result JSON (defaults depend on --stage).",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip the interactive approval prompt and auto-approve the "
        "budget band (non-interactive runs, CI, demos).",
    )
    parser.add_argument(
        "--with-previz",
        action="store_true",
        help="Also generate a storyboard/animatic/music cue for the opening "
        "scene (Phase 6, opt-in — real Vertex AI Imagen/Veo cost and time, "
        "a Veo clip can take minutes; Lyria is best-effort).",
    )
    args = parser.parse_args()

    screenplay_text = args.screenplay.read_text(encoding="utf-8")

    if args.stage == "breakdown":
        out = args.out or (OUTPUT_DIR / "breakdown.json")
        breakdown = asyncio.run(run_script_supervisor(screenplay_text))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(breakdown.model_dump(), indent=2), encoding="utf-8")
        print(f"'{breakdown.title}' -> {len(breakdown.scenes)} scenes, "
              f"{breakdown.total_estimated_pages} estimated pages")
        print(f"Breakdown written to {out}")
        return

    out = args.out or (OUTPUT_DIR / "package.json")
    artifacts, error = asyncio.run(
        run_line_producer(
            screenplay_text, auto_approve=args.auto_approve, with_previz=args.with_previz
        )
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifacts, indent=2), encoding="utf-8")

    if "breakdown" in artifacts:
        breakdown = artifacts["breakdown"]
        print(f"'{breakdown['title']}' -> {len(breakdown['scenes'])} scenes")
    if "schedule" in artifacts:
        print(f"Scheduled across {artifacts['schedule']['total_shoot_days']} shoot day(s)")
    if "budget" in artifacts:
        print(f"Budget: {artifacts['budget']['currency']} "
              f"{artifacts['budget']['total_estimated_cost']:,.0f}")
    if "approval" in artifacts:
        approval = artifacts["approval"]
        print(f"Approval: {'approved' if approval['approved'] else 'rejected'} "
              f"({approval['reason']})")
    if "resources" in artifacts:
        print("Resources: proposed")
    if "previz" in artifacts:
        previz = artifacts["previz"]
        print(f"Previz: {len(previz['storyboard_paths'])} storyboard(s), "
              f"animatic={'yes' if previz['animatic_path'] else 'no'}, "
              f"music={'yes' if previz['music_cue_path'] else 'no'}")
        for warning in previz["warnings"]:
            print(f"  warning: {warning}")

    if error is not None:
        print(f"\nRun stopped early ({type(error).__name__}); "
              f"partial results above were still written to {out}.")
    else:
        print(f"\nPackage written to {out}")


if __name__ == "__main__":
    main()
