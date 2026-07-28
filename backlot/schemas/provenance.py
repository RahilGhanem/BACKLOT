"""Shared provenance contract for anything grounded via MCP.

Every budget/resource claim a professional would want to trust must cite the
MCP record it came from (or be explicitly marked ungrounded) — this is the
type that citation lives in.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GroundedRecord(BaseModel):
    record_id: str = Field(description="Identifier of the source record, e.g. 'CR-101' or 'EXT_NIGHT_INDUSTRIAL'.")
    summary: str = Field(description="One-line human-readable summary of what this record says.")
    source: str = Field(description="Where this record came from, e.g. 'mcp_shim:historical_costs.json'.")
