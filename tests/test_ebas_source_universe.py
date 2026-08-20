from __future__ import annotations

import json
from pathlib import Path

from ontology.tools.audit_ebas_manifestations import audit, load, normalize


def test_ebas_normalization_is_candidate_grouping_only() -> None:
    assert normalize("Unibón #4") == "unibon_4"
    assert normalize("Unibón 4") == "unibon_4"


def test_source_registry_keeps_current_open_and_freezes_recovered_source_universes() -> None:
    registry = json.loads(Path("ontology/ebas_source_registry.v0.1.json").read_text(encoding="utf-8"))
    enum = registry["enumerator_certification"]
    assert enum["aaa_bounded_current_denominator"] == "OPEN"
    assert enum["aaa_bounded_historical_denominator"] == 835
    assert enum["aaa_bounded_historical_snapshot"] == "2024-06"
    assert enum["aaa_bounded_historical_state"] == "CERTIFIED_REPORTED_SNAPSHOT"
    assert enum["aaa_bounded_historical_computed_from_enumerator"] is False
    assert enum["aaa_2015_ww_pump_station_layer_denominator"] == 1066
    assert enum["aaa_2015_owner_prasa_rows"] == 969
    assert enum["sige_complete_layer_denominator"] == 155
    assert enum["pr_wide_denominator"] == "OPEN"


def test_sige_layer_is_complete_but_not_current_aaa_denominator() -> None:
    registry = json.loads(Path("ontology/ebas_source_registry.v0.1.json").read_text(encoding="utf-8"))
    source = next(source for source in registry["sources"] if source["source_id"] == "EBAS_SRC_SIGE_CALIDAD_AMBIENTE_L5")
    assert source["query_completeness"] == "RETRIEVED_COMPLETE"
    assert source["retrieved_count"] == source["retrieved_object_id_count"] == source["retrieved_feature_count"] == 155
    assert source["denominator_effect"] == "INELIGIBLE_AS_AAA_CURRENT_DENOMINATOR"


def test_2015_gdb_is_row_level_wastewater_pump_enumerator_with_mixed_owners() -> None:
    registry = json.loads(Path("ontology/ebas_source_registry.v0.1.json").read_text(encoding="utf-8"))
    source = next(source for source in registry["sources"] if source["source_id"] == "EBAS_SRC_GISPR_AAA_2015_GDB")
    assert source["query_completeness"] == "ARCHIVE_RETRIEVED_LAYERS_ENUMERATED"
    assert source["archive_sha256"] == "6afe70c8cc96f2b7d3f73a0976f4bd5d422dff74ba7071281f9c1262be851d8e"
    assert source["layer_count"] == 29
    assert source["ww_pump_station_layer_count"] == 1066
    assert source["ww_pump_station_owner_counts"] == {"PRASA": 969, "PRV": 91, "GOV": 5, "UNK": 1}
    assert sum(source["ww_pump_station_owner_counts"].values()) == 1066
    assert source["denominator_effect"] == "CERTIFIED_2015_WASTEWATER_PUMP_LAYER_1066"


def test_prasa_cer_system_inventory_is_reported_denominator_not_enumerator() -> None:
    registry = json.loads(Path("ontology/ebas_source_registry.v0.1.json").read_text(encoding="utf-8"))
    source = next(source for source in registry["sources"] if source["source_id"] == "EBAS_SRC_PRASA_FY2024_CER_SYSTEM_INVENTORY")
    assert source["eligibility"] == "AUTHORITATIVE_BOUNDED_DENOMINATOR_SOURCE"
    assert source["denominator_effect"] == "CERTIFIED_REPORTED_HISTORICAL"
    assert source["reported_wwps_count"] == 835
    assert source["computed_from_retrieved_enumerator"] is False
    assert source["physical_identity_rows_retrieved"] is False


def test_current_sige_aaa_service_is_partial_not_ebas_enumerator() -> None:
    registry = json.loads(Path("ontology/ebas_source_registry.v0.1.json").read_text(encoding="utf-8"))
    source = next(source for source in registry["sources"] if source["source_id"] == "EBAS_SRC_SIGE_AAA_V10_N")
    assert source["eligibility"] == "AUTHORITATIVE_PARTIAL"
    assert source["denominator_effect"] == "INELIGIBLE_AS_EBAS_ENUMERATOR"


def test_project_manifestations_do_not_become_physical_identity() -> None:
    report, manifestations = audit(load(Path("ontology/ebas_manifestation_seed.v0.1.json")), load(Path("ontology/ebas_source_registry.v0.1.json")))
    assert report["manifestation_count"] == 44
    assert report["identity_candidate_key_count"] == 42
    assert report["repeated_candidate_keys"] == ["morovis|cruz_rosario", "morovis|unibon_4"]
    assert report["candidate_not_identity_count"] == 44
    assert report["certified_enumerators"] == 0
    assert report["certified_historical_row_level_enumerators"] == 1
    assert report["certified_reported_denominator_sources"] == 1
    assert report["aaa_bounded_historical_denominator"] == 835
    assert report["aaa_2015_ww_pump_station_layer_denominator"] == 1066
    assert report["aaa_2015_owner_prasa_rows"] == 969
    assert report["sige_complete_layer_denominator"] == 155
    assert report["physical_asset_count_claimed"] is False
    assert all(row["identity_state"] == "CANDIDATE_NOT_IDENTITY" for row in manifestations)
    assert all(row["identity_effect"] == "none" for row in manifestations)


def test_maunabo_conversion_is_not_current_station_identity() -> None:
    _, manifestations = audit(load(Path("ontology/ebas_manifestation_seed.v0.1.json")), load(Path("ontology/ebas_source_registry.v0.1.json")))
    row = next(row for row in manifestations if row["name_raw"] == "PTAR y EBAS de Maunabo")
    assert row["manifestation_kind"] == "PLANNED_WWTP_TO_EBAS_CONVERSION"
    assert row["identity_state"] == "CANDIDATE_NOT_IDENTITY"


def test_non_aaa_owner_operator_universe_is_fail_closed() -> None:
    universe = json.loads(Path("ontology/ebas_non_aaa_operator_universe.v0.1.json").read_text(encoding="utf-8"))
    snap = universe["source_snapshot_2015"]
    assert snap["owner_domain"] == {"PRASA": "AAA", "PRV": "Privado", "GOV": "Gobierno", "UNK": "Desconocido"}
    assert snap["lifecycle_domain"]["2"] == "En Uso"
    assert snap["en_uso_counts"] == {"PRASA": 792, "PRV": 87, "GOV": 4, "UNK": 0}
    assert snap["non_aaa_owned_en_uso"] == 91
    assert len(snap["government_en_uso_manifestations"]) == 4
    terminal = universe["terminal_state"]
    assert terminal["non_aaa_sanitary_systems_current_exist"] is True
    assert terminal["current_non_aaa_ebas_denominator"] == "OPEN"
    assert terminal["pr_wide_ebas_denominator"] == "OPEN"
    assert set(terminal["non_aaa_current_system_operators_confirmed"]) == {
        "Local Redevelopment Authority for Roosevelt Roads",
        "PDM Utility Corporation",
        "Coco Beach Utility Company, Inc.",
    }
    assert universe["private_franchise_universe"]["bounded_count"] == 3
    assert universe["private_franchise_universe"]["not_equivalent_to_ebas_denominator"] is True
    federal = next(x for x in universe["current_operator_classes"] if x["class"] == "FEDERAL_INSTALLATION_NEGATIVE_CONTROL")
    assert federal["entity"] == "Fort Buchanan"
    assert federal["operator_state"] == "AAA_OPERATED_SANITARY_SERVICE"
    assert universe["municipal_operator_test"]["state"] == "NO_INDEPENDENT_MUNICIPAL_POTW_OPERATOR_CERTIFIED_IN_BOUNDED_SEARCH"


def test_current_non_aaa_asset_enumeration_is_bounded_and_fail_closed() -> None:
    data = json.loads(Path("ontology/ebas_non_aaa_current_asset_enumeration.v0.1.json").read_text(encoding="utf-8"))
    assert data["current_non_aaa_ebas_denominator"] == "OPEN"
    assert data["current_non_aaa_operational_ebas_denominator"] == "OPEN"
    assert data["certified_current_non_aaa_operational_lower_bound"] == 5
    assert data["cross_source_named_station_manifestations"] == 12
    operators = {row["operator"]: row for row in data["operators"]}
    pdmu = operators["PDM Utility Corporation"]
    assert pdmu["current_station_count"] == 5
    assert pdmu["current_station_count_state"] == "CERTIFIED_CURRENT_OPERATOR_BOUND_DENOMINATOR"
    assert [x["station_id"] for x in pdmu["named_station_assets"]] == ["PS-1", "PS-2", "PS-3", "PS-10", "PS-12"]
    lra = operators["Local Redevelopment Authority for Roosevelt Roads"]
    assert lra["named_asset_count"] == 5
    assert lra["current_operational_count"] == "OPEN"
    coco = operators["Coco Beach Utility Company, Inc."]
    assert coco["recent_operational_station_count"] == 2
    assert coco["current_station_count"] == "OPEN"
    assert coco["same_name_exclusion"]["facility_id"] == "WWPS0000166AAA0329"
    assert coco["same_name_exclusion"]["owner"] == "PRASA"
    caguas = operators["Caguas Real Utility Corp."]
    assert caguas["current_water_system_state"] == "CONFIRMED"
    assert caguas["sewer_operator_state"] == "CURRENT_2026_UNRESOLVED"
    assert caguas["current_station_count"] == "OPEN"
    assert data["aaa_combination_gate"]["aaa_current_2026_denominator"] == "OPEN"
    assert data["aaa_combination_gate"]["combination_state"] == "NOT_EXECUTED"
    assert data["pr_wide_closure"]["state"] == "OPEN"
