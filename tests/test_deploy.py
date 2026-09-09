"""Deployment artifact tests — construction/presence only, no network, no
gcloud/adk CLI invocation, no Docker."""

from backlot.agents.approval_gate import auto_approve_decider
from backlot.config import REPO_ROOT


def test_agent_engine_entrypoint_builds_an_auto_approving_root_agent():
    import deploy.agent_engine.agent as deployed

    assert deployed.root_agent.name == "line_producer"
    by_name = {a.name: a for a in deployed.root_agent.sub_agents}
    assert by_name["approval_gate"].decider is auto_approve_decider


def test_dockerfiles_exist_and_reference_the_right_entrypoints():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "backlot.api.app:app" in dockerfile

    shim_dockerfile = (REPO_ROOT / "Dockerfile.mcp_shim").read_text(encoding="utf-8")
    assert "backlot.mcp_shim.server" in shim_dockerfile


def test_deploy_scripts_exist():
    assert (REPO_ROOT / "deploy" / "cloud_run" / "deploy.sh").exists()
    assert (REPO_ROOT / "deploy" / "cloud_run" / "deploy_mcp_shim.sh").exists()
    assert (REPO_ROOT / "deploy" / "agent_engine" / "deploy.sh").exists()
