from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "research/environmental_exposure/environmental_public_service_denominator_20260821.v1.json"


def test_service_manifestations_do_not_close_record_denominators():
    data = json.loads(MANIFEST.read_text("utf-8"))
    assert data["completeness_claimed"] is False
    assert data["global_terminal_state"] == "OPEN"
    assert data["open_record_denominators"]
    assert data["causal_state"] == "NOT_TESTED"
    assert data["source_attribution_implication"] == "NONE"
    for service in data["services"]:
        assert service["service_manifestation_state"].startswith("EXHAUSTED_FOR_")
        assert any(key.endswith("query_state") and value == "OPEN" for key, value in service.items()) or service["family"] == "ECHO_ALL_MEDIA"


def test_echo_family_source_system_bindings_are_explicit():
    data = json.loads(MANIFEST.read_text("utf-8"))
    by_family = {row["family"]: row for row in data["services"]}
    assert by_family["SDWIS"]["source_system"] == "SDWIS/Fed"
    assert by_family["RCRA"]["source_system"] == "RCRAInfo"
    assert by_family["ECHO_NPDES"]["source_system"] == "ICIS-NPDES"
    assert by_family["ECHO_NPDES"]["receiving_water_source_system"] == "ATTAINS_WHEN_AVAILABLE"


def test_attains_and_tri_freshness_are_not_extrapolated():
    data = json.loads(MANIFEST.read_text("utf-8"))
    by_family = {row["family"]: row for row in data["services"]}
    attains = by_family["ATTAINS_303D"]
    assert attains["documentation_update_date"] == "2026-05-27"
    assert attains["api_key_transition_documented"] is True
    tri = by_family["TRI"]
    assert tri["latest_reporting_year_explicitly_observed_on_status_page"] == 2024
    assert "Do not infer" in tri["freshness_note"]


def test_uic_state_inventory_is_not_dorado_well_inventory():
    data = json.loads(MANIFEST.read_text("utf-8"))
    uic = next(row for row in data["services"] if row["family"] == "UIC")
    assert uic["inventory_reporting_period"] == "FY2024"
    assert uic["puerto_rico_regulatory_authority"]["classes_I_to_V"].startswith("Puerto Rico")
    assert uic["puerto_rico_regulatory_authority"]["class_VI"] == "US EPA Region 2"
    assert uic["dorado_well_level_query_state"] == "OPEN"
