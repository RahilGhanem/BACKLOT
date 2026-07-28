"""Risk agent, approval gate, and their schemas — construction/logic tests
that always run (no network)."""

from backlot.agents.approval_gate import auto_approve_decider, build_approval_gate, cli_approval_decider
from backlot.agents.risk import build_risk_agent
from backlot.config import get_settings
from backlot.schemas import ApprovalDecision, RiskFlag, RiskReport


def test_build_risk_agent_is_configured_correctly():
    settings = get_settings()
    agent = build_risk_agent(settings)
    assert agent.name == "risk_agent"
    assert agent.output_key == "risk_report"
    assert agent.output_schema is RiskReport
    assert agent.model == settings.gemini_model_pro
    assert agent.tools == []  # pure reasoning over state, no MCP tools


def test_auto_approve_decider_always_approves():
    approved, reason = auto_approve_decider({"total_estimated_cost": 999999})
    assert approved is True
    assert reason


def test_build_approval_gate_defaults_to_cli_decider():
    gate = build_approval_gate()
    assert gate.decider is cli_approval_decider


def test_risk_report_schema_round_trips():
    report = RiskReport(
        title="TEST",
        schedule_feasible=False,
        flags=[
            RiskFlag(
                category="overtime",
                severity="high",
                description="Three shoot days flagged over budget.",
                affected_shoot_days=[1, 2, 3],
                recommendation="Re-plan with a lower pages/day target.",
            )
        ],
        replan_requested=True,
        replan_reason="repeated overtime risk",
    )
    reloaded = RiskReport.model_validate(report.model_dump())
    assert reloaded == report


def test_approval_decision_schema_defaults_reason_empty():
    decision = ApprovalDecision(approved=True)
    assert decision.reason == ""
