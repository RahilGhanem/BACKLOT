"""BACKLOT's local, synthetic stand-in for the IBM watsonx.data remote MCP
server. Exposes the exact tool interface the real IBM server would: agents
never need to change when MCP_SERVER_URL is repointed at IBM's endpoint in
production (see .env.example and README's "Data note").

Run standalone:
    python -m backlot.mcp_shim.server

Note MCP_SHIM_HOST/MCP_SHIM_PORT (what this process binds to) are separate
settings from MCP_SERVER_URL (what clients connect to) — see config.py.
Locally they describe the same address by default; in a cloud deployment
this process binds 0.0.0.0:$PORT while MCP_SERVER_URL, set on whatever
connects to it, is this service's public HTTPS URL instead.
"""

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
        "libraries, and past-schedule patterns behind the same tool "
        "interface the real IBM watsonx.data remote MCP server exposes."
    ),
    host=_settings.mcp_shim_host,
    port=_settings.mcp_shim_port,
    streamable_http_path=_mcp_path,
)


@mcp.tool()
def get_comparable_costs(scene_profile: str) -> dict:
    """Look up historical per-day production costs for scenes resembling
    `scene_profile` (e.g. 'EXT_NIGHT_INDUSTRIAL', 'INT_DAY_STANDARD').
    Uses fuzzy token matching against the studio's cost history, not an
    exact key lookup — pass your best description of the scene's setting.
    """
    dataset = load_dataset()["historical_costs"]
    matches = best_matches(scene_profile, dataset["records"], key="scene_profile")
    return {
        "source": "mcp_shim:historical_costs.json",
        "query": {"scene_profile": scene_profile},
        "matches": [record for record, _score in matches],
    }


@mcp.tool()
def get_vendor_rates(category: str, region: str | None = None) -> dict:
    """Look up current per-day vendor rate cards by category (e.g.
    'grip_and_electric', 'picture_vehicle', 'rain_effects'), fuzzy-matched,
    optionally filtered to a region (e.g. 'US-West').
    """
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
    """Find crew members whose role fuzzy-matches `role` (e.g. 'Gaffer',
    'Key Grip', '1st AD') and who are available across
    [start_date, end_date] (ISO 'YYYY-MM-DD'; omit both to skip date
    filtering).
    """
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
    """Find studio locations whose type fuzzy-matches `location_type` (e.g.
    'industrial lot', 'warehouse dock', 'highway'), optionally filtered to
    a region (e.g. 'US-East').
    """
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
    for a genre (e.g. 'heist thriller', 'drama'), fuzzy-matched, optionally
    filtered to a production scale ('short_film' or 'feature').
    """
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
