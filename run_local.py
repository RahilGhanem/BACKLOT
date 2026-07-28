"""Local dev entrypoint: run the Script Supervisor on a screenplay file.

Usage:
    python run_local.py
    python run_local.py --screenplay data/screenplays/sample_screenplay.txt --out output/breakdown.json

This bypasses Agent Engine entirely and uses ADK's InMemoryRunner + an
in-memory session, so it works with nothing more than a Gemini credential
in .env. Later phases add the Line Producer orchestrator on top of this
same pattern.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from google.adk.runners import InMemoryRunner
from google.genai import types

from backlot.agents.script_supervisor import build_script_supervisor
from backlot.config import DATA_DIR, OUTPUT_DIR, get_settings
from backlot.schemas import ScriptBreakdown


async def run_script_supervisor(screenplay_text: str) -> ScriptBreakdown:
    settings = get_settings()
    settings.require_llm_credentials()

    agent = build_script_supervisor(settings)
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
        pass  # the agent writes its result into session state via output_key

    session = await runner.session_service.get_session(
        app_name=settings.app_name, user_id=user_id, session_id=session_id
    )
    breakdown_data = session.state.get("breakdown") if session else None
    if breakdown_data is None:
        raise RuntimeError(
            "Script Supervisor produced no 'breakdown' state. Check the "
            "model response above for errors."
        )
    return ScriptBreakdown.model_validate(breakdown_data)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the BACKLOT Script Supervisor on a screenplay."
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
        default=OUTPUT_DIR / "breakdown.json",
        help="Where to write the resulting breakdown JSON.",
    )
    args = parser.parse_args()

    screenplay_text = args.screenplay.read_text(encoding="utf-8")
    breakdown = asyncio.run(run_script_supervisor(screenplay_text))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(breakdown.model_dump(), indent=2), encoding="utf-8"
    )

    print(f"'{breakdown.title}' -> {len(breakdown.scenes)} scenes, "
          f"{breakdown.total_estimated_pages} estimated pages")
    print(f"Breakdown written to {args.out}")


if __name__ == "__main__":
    main()
