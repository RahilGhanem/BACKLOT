"""The human approval gate's decision record."""

from __future__ import annotations

from pydantic import BaseModel


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""
