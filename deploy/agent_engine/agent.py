"""Agent Engine deployment entrypoint.

`adk deploy agent_engine` expects exactly this folder convention — an
`__init__.py` that imports this module, and a module-level `root_agent`
(verified against the installed ADK CLI by running `adk create` on a
scratch folder and inspecting its output; see docs/DEPLOYMENT.md). Deploy
with:

    adk deploy agent_engine --project=$PROJECT_ID --region=$REGION \
        --display_name=backlot deploy/agent_engine

Run from an environment where this repo's `backlot` package is importable
(`pip install -e .` from the repo root — the same setup as local dev).

Agent Engine's native session/query API is stateless request/response; it
doesn't have the HTTP-approval-relay backlot/api/run_manager.py uses for
the web UI's Approve/Reject buttons. This variant auto-approves the budget
band so the crew still completes end to end when hosted here. The full
human-in-the-loop experience is the Cloud Run + web UI deployment — see
docs/DEPLOYMENT.md for both paths and why each exists.
"""

from backlot.agents.approval_gate import auto_approve_decider
from backlot.config import get_settings
from backlot.orchestrator import build_line_producer

root_agent = build_line_producer(get_settings(), approval_decider=auto_approve_decider)
