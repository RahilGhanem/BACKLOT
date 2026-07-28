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
in .env.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from google.adk.agents.base_agent import BaseAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from backlot.agents.approval_gate import auto_approve_decider, cli_approval_decider
from backlot.agents.script_supervisor import build_script_supervisor
from backlot.config import DATA_DIR, OUTPUT_DIR, get_settings
from backlot.orchestrator import build_line_producer
from backlot.schemas import ProductionPackage, ScriptBreakdown


async def _run_agent_and_get_state(agent: BaseAgent, screenplay_text: str, state_key: str) -> dict:
    settings = get_settings()
    runner = InMemoryRunner(agent=agent, app_name=settings.app_name)

    user_id = "local-dev"
    session_id = str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id
    )

    message = types.Content(role="user", parts=[types.Part(text=screenplay_text)])

    async for _event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        pass  # agents write their results into session state via output_key / state_delta

    session = await runner.session_service.get_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id
    )
    data = session.state.get(state_key) if session else None
    if data is None:
        raise RuntimeError(
            f"Pipeline produced no '{state_key}' state. Check the agent "
            "output above for errors."
        )
    return data


async def run_script_supervisor(screenplay_text: str) -> ScriptBreakdown:
    settings = get_settings()
    settings.require_llm_credentials()
    agent = build_script_supervisor(settings)
    data = await _run_agent_and_get_state(agent, screenplay_text, "breakdown")
    return ScriptBreakdown.model_validate(data)


async def run_line_producer(
    screenplay_text: str, auto_approve: bool = False, with_previz: bool = False
) -> ProductionPackage:
    settings = get_settings()
    settings.require_llm_credentials()
    decider = auto_approve_decider if auto_approve else cli_approval_decider
    agent = build_line_producer(settings, approval_decider=decider, include_previz=with_previz)
    data = await _run_agent_and_get_state(agent, screenplay_text, "package")
    return ProductionPackage.model_validate(data)


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
    else:
        out = args.out or (OUTPUT_DIR / "package.json")
        package = asyncio.run(
            run_line_producer(
                screenplay_text, auto_approve=args.auto_approve, with_previz=args.with_previz
            )
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(package.model_dump(), indent=2), encoding="utf-8")
        print(f"'{package.title}' -> {len(package.breakdown.scenes)} scenes, "
              f"{package.schedule.total_shoot_days} shoot day(s)")
        if package.approval:
            print(f"Approval: {'approved' if package.approval.approved else 'rejected'} "
                  f"({package.approval.reason})")
        if package.previz:
            print(f"Previz: {len(package.previz.storyboard_paths)} storyboard(s), "
                  f"animatic={'yes' if package.previz.animatic_path else 'no'}, "
                  f"music={'yes' if package.previz.music_cue_path else 'no'}")
            for warning in package.previz.warnings:
                print(f"  warning: {warning}")
        print(f"Package written to {out}")


if __name__ == "__main__":
    main()
