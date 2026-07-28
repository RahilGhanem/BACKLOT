"""The Budget Agent's output contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .provenance import GroundedRecord


class BudgetLineItem(BaseModel):
    label: str = Field(description="e.g. 'Shoot day 1 (LOT, night exterior)' or 'Vendor: rain effects unit'.")
    amount: float
    currency: str = "USD"
    grounded: bool = Field(description="True only if source_records cites at least one real MCP record.")
    source_records: list[GroundedRecord] = Field(default_factory=list)
    notes: str = ""


class BudgetEstimate(BaseModel):
    title: str
    currency: str = "USD"
    total_estimated_cost: float
    line_items: list[BudgetLineItem]
