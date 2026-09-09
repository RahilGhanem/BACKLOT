"""The production package the Line Producer assembles and returns."""

from __future__ import annotations

from pydantic import BaseModel

from .approval import ApprovalDecision
from .breakdown import ScriptBreakdown
from .budget import BudgetEstimate
from .previz import PrevizAsset
from .resources import ResourcePlan
from .risk import RiskReport
from .schedule import Schedule


class ProductionPackage(BaseModel):
    title: str
    breakdown: ScriptBreakdown
    schedule: Schedule
    budget: BudgetEstimate | None = None
    risk_report: RiskReport | None = None
    approval: ApprovalDecision | None = None
    resources: ResourcePlan | None = None
    previz: PrevizAsset | None = None
