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
