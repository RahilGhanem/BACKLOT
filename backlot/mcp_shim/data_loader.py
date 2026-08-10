"""Loads the synthetic studio dataset once and caches it in memory.

Swapping this shim for the real, official ClickHouse MCP server
(github.com/ClickHouse/mcp-clickhouse) means setting MCP_MODE=clickhouse
and pointing CLICKHOUSE_MCP_URL / CLICKHOUSE_MCP_AUTH_TOKEN at it instead —
this module and mcp_shim/server.py simply go unused in that mode (see
backlot/agents/budget.py / resource.py's per-mode instructions, which do
change: the real server's tool names/SQL differ from this shim's).
"""

from __future__ import annotations

import json
from functools import lru_cache

from ..config import DATA_DIR

STUDIO_DATASET_DIR = DATA_DIR / "studio_dataset"

_FILES = {
    "historical_costs": "historical_costs.json",
    "vendor_rates": "vendor_rates.json",
    "crew_library": "crew_library.json",
    "location_library": "location_library.json",
    "past_schedules": "past_schedules.json",
}


@lru_cache(maxsize=1)
def load_dataset() -> dict[str, dict]:
    dataset = {}
    for key, filename in _FILES.items():
        path = STUDIO_DATASET_DIR / filename
        with path.open("r", encoding="utf-8") as f:
            dataset[key] = json.load(f)
    return dataset
