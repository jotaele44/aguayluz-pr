from __future__ import annotations

import json
from pathlib import Path

from ontology.tools.audit_ebas_manifestations import audit, load, normalize


def test_ebas_normalization_is_candidate_grouping_only() -> None:
    assert normalize("Unibón #4") == "unibon_4"
    assert normalize("Unibón 4") == "unibon_4"


def test_source_registry_keeps_current_open_but_certifies_reported_historical_snapshot() -> None:
    registry = json.loads(Path("ontology/ebas_source_registry.v0.1.json").read_text(encoding="utf-8"))
    candidates = [
        source
        for source in registry["sources"]
        if source["eligibility"] in {"AUTHORITATIVE_BOUNDED_ENUMERATOR_CANDIDATE", "AUTHORITATIVE_ARCHIVE_CANDIDATE"}
    ]
    assert len(candidates) == 2
    assert all(source["denominator_effect"] == "NOT_CERTIFIED" for source in candidates)
    enum = registry["enumerator_certification"]
    assert enum["aaa_bounded_current_denominator"] == "OPEN"
    assert enum["aaa_bounded_historical_denominator"] == 835
    assert enum["aaa_bounded_historical_snapshot"] == "2024-06"
    assert enum["aaa_bounded_historical_state"] == "CERTIFIED_REPORTED_SNAPSHOT"
    assert enum["aaa_bounded_historical_computed_from_enumerator"] is False
    assert enum["pr_wide_denominator"] == "OPEN"


def test_prasa_cer_system_inventory_is_reported_denominator_not_enumerator() -> None:
    registry = json.loads(Path("ontology/ebas_source_registry.v0.1.json").read_text(encoding="utf-8"))
    source = next(
        source
        for source in registry["sources"]
        if source["source_id"] == "EBAS_SRC_PRASA_FY2024_CER_SYSTEM_INVENTORY"
    )
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
    report, manifestations = audit(
        load(Path("ontology/ebas_manifestation_seed.v0.1.json")),
        load(Path("ontology/ebas_source_registry.v0.1.json")),
    )
    assert report["manifestation_count"] == 44
    assert report["identity_candidate_key_count"] == 42
    assert report["repeated_candidate_keys"] == ["morovis|cruz_rosario", "morovis|unibon_4"]
    assert report["candidate_not_identity_count"] == 44
    assert report["certified_enumerators"] == 0
    assert report["certified_reported_denominator_sources"] == 1
    assert report["aaa_bounded_historical_denominator"] == 835
    assert report["aaa_bounded_historical_computed_from_enumerator"] is False
    assert report["physical_asset_count_claimed"] is False
    assert all(row["identity_state"] == "CANDIDATE_NOT_IDENTITY" for row in manifestations)
    assert all(row["identity_effect"] == "none" for row in manifestations)


def test_maunabo_conversion_is_not_current_station_identity() -> None:
    _, manifestations = audit(
        load(Path("ontology/ebas_manifestation_seed.v0.1.json")),
        load(Path("ontology/ebas_source_registry.v0.1.json")),
    )
    row = next(row for row in manifestations if row["name_raw"] == "PTAR y EBAS de Maunabo")
    assert row["manifestation_kind"] == "PLANNED_WWTP_TO_EBAS_CONVERSION"
    assert row["identity_state"] == "CANDIDATE_NOT_IDENTITY"
