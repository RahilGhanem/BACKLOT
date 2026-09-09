"""BACKLOT's local, synthetic stand-in for the real ClickHouse MCP server
(github.com/ClickHouse/mcp-clickhouse)."""

from __future__ import annotations

from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from ..config import get_settings
from .data_loader import load_dataset
from .matching import best_matches, date_ranges_overlap

_settings = get_settings()
_mcp_path = urlparse(_settings.mcp_server_url).path or "/mcp"

mcp = FastMCP(
    name="backlot-mcp-shim",
    instructions=(
        "Synthetic studio-data MCP server for BACKLOT local development. "
        "Serves fabricated historical costs, vendor rates, crew/location "
        "libraries, and past-schedule patterns — the offline dev fallback "
        "for MCP_MODE=clickhouse's real ClickHouse cluster + "
        "mcp-clickhouse server."
    ),
    host=_settings.mcp_shim_host,
    port=_settings.mcp_shim_port,
    streamable_http_path=_mcp_path,
)


@mcp.tool()
def get_comparable_costs(scene_profile: str) -> dict:
    """Look up historical per-day production costs for scenes resembling
    `scene_profile` (e.g."""
    dataset = load_dataset()["historical_costs"]
    matches = best_matches(scene_profile, dataset["records"], key="scene_profile")
    return {
        "source": "mcp_shim:historical_costs.json",
        "query": {"scene_profile": scene_profile},
        "matches": [record for record, _score in matches],
    }


@mcp.tool()
def get_vendor_rates(category: str, region: str | None = None) -> dict:
    """Look up current per-day vendor rate cards by category (e.g."""
    dataset = load_dataset()["vendor_rates"]
    matches = [record for record, _score in best_matches(category, dataset["records"], key="category")]
    if region:
        region_norm = region.strip().lower()
        narrowed = [r for r in matches if r["region"].strip().lower() == region_norm]
        if narrowed:
            matches = narrowed
    return {
        "source": "mcp_shim:vendor_rates.json",
        "query": {"category": category, "region": region},
        "matches": matches,
    }


@mcp.tool()
def find_available_crew(
    role: str, start_date: str | None = None, end_date: str | None = None
) -> dict:
    """Find crew members whose role fuzzy-matches `role` (e.g."""
    dataset = load_dataset()["crew_library"]
    matches = [
        record
        for record, _score in best_matches(role, dataset["records"], key="role", min_score=0.3)
    ]
    matches = [
        r
        for r in matches
        if date_ranges_overlap(start_date, end_date, r["available_from"], r["available_to"])
    ]
    return {
        "source": "mcp_shim:crew_library.json",
        "query": {"role": role, "start_date": start_date, "end_date": end_date},
        "matches": matches,
    }


@mcp.tool()
def find_locations(location_type: str, region: str | None = None) -> dict:
    """Find studio locations whose type fuzzy-matches `location_type` (e.g."""
    dataset = load_dataset()["location_library"]
    matches = [record for record, _score in best_matches(location_type, dataset["records"], key="type")]
    if region:
        region_norm = region.strip().lower()
        narrowed = [r for r in matches if r["region"].strip().lower() == region_norm]
        if narrowed:
            matches = narrowed
    return {
        "source": "mcp_shim:location_library.json",
        "query": {"location_type": location_type, "region": region},
        "matches": matches,
    }


@mcp.tool()
def get_past_schedule_patterns(genre: str, scale: str | None = None) -> dict:
    """Look up historical scheduling priors (avg pages/day, avg shoot days)
    for a genre (e.g."""
    dataset = load_dataset()["past_schedules"]
    matches = [record for record, _score in best_matches(genre, dataset["records"], key="genre")]
    if scale:
        scale_norm = scale.strip().lower()
        narrowed = [r for r in matches if r["scale"].strip().lower() == scale_norm]
        if narrowed:
            matches = narrowed
    return {
        "source": "mcp_shim:past_schedules.json",
        "query": {"genre": genre, "scale": scale},
        "matches": matches,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
