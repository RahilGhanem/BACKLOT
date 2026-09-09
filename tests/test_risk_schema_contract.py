"""Regression guards for the Risk Agent's structured-output contract."""

from __future__ import annotations

import pytest
from google.genai import _transformers as genai_transformers
from pydantic import ValidationError

from backlot.orchestrator.line_producer import MAX_RISK_VALIDATION_RETRIES
from backlot.schemas import RiskFlag, RiskReport


def _wire_schema(model) -> dict:
    """The schema google-genai actually transmits as response_schema."""
    return genai_transformers.t_schema(None, model).model_dump(exclude_none=True)


def test_wire_schema_requires_every_riskreport_field():
    """Constrained decoding may omit any field absent from `required`."""
    required = _wire_schema(RiskReport)["required"]
    assert set(required) == {
        "title",
        "schedule_feasible",
        "flags",
        "replan_requested",
        "replan_reason",
    }
    assert "flags" in required, "flags must be required or the model may omit it"


def test_wire_schema_requires_every_riskflag_field():
    flag_schema = _wire_schema(RiskReport)["properties"]["flags"]["items"]
    assert "description" in flag_schema["required"]
    assert "severity" in flag_schema["required"]
    assert "recommendation" in flag_schema["required"], (
        "the validator needs a recommendation to justify a replan"
    )


def test_wire_schema_bounds_every_free_text_field():
    """A bounded field turns a degenerate repetition loop into a fast,
    catchable validation error rather than a multi-thousand-token reply."""
    schema = _wire_schema(RiskReport)
    assert schema["properties"]["replan_reason"]["max_length"] > 0
    assert schema["properties"]["title"]["max_length"] > 0

    flag_props = schema["properties"]["flags"]["items"]["properties"]
    for field in ("category", "severity", "description", "recommendation"):
        assert flag_props[field]["max_length"] > 0, f"{field} must be bounded"


def test_flags_ordered_before_free_text_fields():
    """property_ordering asks the model for `flags` before the free-text
    fields, so the substantive content is emitted first."""
    ordering = _wire_schema(RiskReport)["property_ordering"]
    assert ordering.index("flags") < ordering.index("replan_reason")


def test_python_defaults_are_preserved():
    """Requiring fields on the wire must not make them required in Python --
    internal callers and tests construct RiskReport without them."""
    report = RiskReport(title="TEST", schedule_feasible=True, flags=[])
    assert report.replan_requested is False
    assert report.replan_reason == ""


def test_degenerate_replan_reason_is_rejected():
    """A runaway repetition in replan_reason must fail validation."""
    degenerate = "risk. " * 5000
    with pytest.raises(ValidationError):
        RiskReport(
            title="TEST",
            schedule_feasible=False,
            flags=[
                RiskFlag(
                    category="overtime",
                    severity="high",
                    description="Four consecutive night shoot days.",
                    recommendation="Re-plan with a larger pages/day cap.",
                )
            ],
            replan_requested=True,
            replan_reason=degenerate,
        )


def test_oversized_flag_description_is_rejected():
    with pytest.raises(ValidationError):
        RiskFlag(
            category="overtime",
            severity="high",
            description="x" * 5000,
            recommendation="ok",
        )


def test_risk_validation_retries_are_hard_bounded():
    """No infinite retry loop: the orchestrator caps corrective retries and
    then raises rather than spinning."""
    assert isinstance(MAX_RISK_VALIDATION_RETRIES, int)
    assert 0 < MAX_RISK_VALIDATION_RETRIES <= 5
