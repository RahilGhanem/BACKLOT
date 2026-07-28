"""mcp_shim tool tests — pure Python function calls, no server, no network."""

from backlot.mcp_shim.server import (
    find_available_crew,
    find_locations,
    get_comparable_costs,
    get_past_schedule_patterns,
    get_vendor_rates,
)


def test_get_comparable_costs_fuzzy_matches_scene_profile():
    result = get_comparable_costs("exterior night industrial lot")
    assert result["source"] == "mcp_shim:historical_costs.json"
    assert any(m["scene_profile"] == "EXT_NIGHT_INDUSTRIAL" for m in result["matches"])


def test_get_comparable_costs_no_match_returns_empty_not_invented():
    result = get_comparable_costs("zzz_totally_unrelated_profile_xyz")
    assert result["matches"] == []


def test_get_vendor_rates_filters_by_region_when_available():
    result = get_vendor_rates("rain effects", region="US-West")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["region"] == "US-West"


def test_get_vendor_rates_falls_back_when_region_has_no_exact_match():
    result = get_vendor_rates("rain effects", region="EU-Central")
    # no EU-Central vendor exists; falls back to fuzzy category matches
    assert len(result["matches"]) >= 1


def test_find_available_crew_filters_by_role_and_date_window():
    result = find_available_crew("gaffer", start_date="2026-08-05", end_date="2026-08-10")
    assert all(m["role"] == "Gaffer" for m in result["matches"])
    assert len(result["matches"]) == 2  # both gaffers in the fixture cover this window


def test_find_available_crew_excludes_out_of_window_availability():
    # Stunt Coordinator is only available 2026-08-15 to 2026-09-15
    result = find_available_crew("stunt coordinator", start_date="2026-07-01", end_date="2026-07-10")
    assert result["matches"] == []


def test_find_locations_filters_by_type():
    result = find_locations("warehouse dock")
    assert all("dock" in m["type"] for m in result["matches"])


def test_get_past_schedule_patterns_filters_by_scale():
    result = get_past_schedule_patterns("heist thriller", scale="feature")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["scale"] == "feature"
