from __future__ import annotations

import json
from pathlib import Path


def load() -> dict:
    return json.loads(Path("ontology/ebas_non_aaa_current_asset_enumeration.v0.1.json").read_text(encoding="utf-8"))


def test_current_non_aaa_denominator_stays_open_until_all_operator_branches_close() -> None:
    data = load()
    assert data["current_non_aaa_ebas_denominator"] == "OPEN"
    assert data["current_non_aaa_operational_ebas_denominator"] == "OPEN"
    assert data["certified_current_non_aaa_operational_lower_bound"] == 5
    assert data["aaa_current_2026_denominator"] == "OPEN"
    assert data["pr_wide_denominator"] == "OPEN"
    assert data["cross_source_named_station_manifestations"] == 12
    assert data["identity_effect"] == "none"
    assert data["physical_asset_count_claimed"] is False


def test_pdmu_is_only_closed_current_station_denominator() -> None:
    data = load()
    operators = {row["operator"]: row for row in data["operators"]}
    pdmu = operators["PDM Utility Corporation"]
    assert pdmu["operator_state"] == "CURRENT_NON_AAA_OPERATOR_CONFIRMED"
    assert pdmu["current_station_count"] == 5
    assert pdmu["current_station_count_state"] == "CERTIFIED_CURRENT_OPERATOR_BOUND_DENOMINATOR"
    assert [x["station_id"] for x in pdmu["named_station_assets"]] == ["PS-1", "PS-2", "PS-3", "PS-10", "PS-12"]


def test_lra_assets_are_not_promoted_to_current_operation() -> None:
    data = load()
    operators = {row["operator"]: row for row in data["operators"]}
    lra = operators["Local Redevelopment Authority for Roosevelt Roads"]
    assert lra["named_asset_count"] == 5
    assert lra["current_operational_count"] == "OPEN"
    assert [x["station_id"] for x in lra["named_station_assets"]] == ["39", "1971", "1471", "2262", "2382"]
    assert all("NOT_CERTIFIED_OPERATIONAL" in x["state"] for x in lra["named_station_assets"])


def test_coco_beach_recent_two_are_not_promoted_to_current_2026() -> None:
    data = load()
    operators = {row["operator"]: row for row in data["operators"]}
    coco = operators["Coco Beach Utility Company, Inc."]
    assert coco["recent_operational_station_count"] == 2
    assert coco["current_station_count"] == "OPEN"
    assert coco["same_name_exclusion"]["facility_id"] == "WWPS0000166AAA0329"
    assert coco["same_name_exclusion"]["sige_geo_id"] == "PREE0113"
    assert coco["same_name_exclusion"]["owner"] == "PRASA"


def test_caguas_real_current_sewer_status_remains_unresolved() -> None:
    data = load()
    operators = {row["operator"]: row for row in data["operators"]}
    caguas = operators["Caguas Real Utility Corp."]
    assert caguas["current_water_system_state"] == "CONFIRMED"
    assert caguas["sewer_operator_state"] == "CURRENT_2026_UNRESOLVED"
    assert caguas["current_sewer_franchise_renewal"] == "NOT_RECOVERED"
    assert caguas["current_station_count"] == "OPEN"


def test_aaa_combination_and_pr_wide_closure_fail_closed() -> None:
    data = load()
    assert data["aaa_combination_gate"]["aaa_current_2026_denominator"] == "OPEN"
    assert data["aaa_combination_gate"]["latest_authoritative_reported_snapshot"] == 835
    assert data["aaa_combination_gate"]["latest_authoritative_reported_snapshot_date"] == "2024-06"
    assert data["aaa_combination_gate"]["combination_state"] == "NOT_EXECUTED"
    assert data["pr_wide_closure"]["state"] == "OPEN"
    assert data["pr_wide_closure"]["rejected_claim"] == "PR_WIDE_EQUALS_AAA_ONLY"
