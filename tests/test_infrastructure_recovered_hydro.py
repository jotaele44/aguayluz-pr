from __future__ import annotations

import csv
import io
from pathlib import Path

from ontology.tools.audit_infrastructure_recovered_replay import canal_id, replay, water_id
from ontology.tools.audit_recovered_hydro_sources import nonblank_csv_rows, stable_id


def test_nonblank_header_recovery_skips_leading_blank_row() -> None:
    text = "\nOBJECTID,canal,length_m,centroid_lon,centroid_lat\n1,Canal de Riego,1.0,-66.0,18.0\n"
    rows = nonblank_csv_rows(text)
    assert rows == [{
        "OBJECTID": "1",
        "canal": "Canal de Riego",
        "length_m": "1.0",
        "centroid_lon": "-66.0",
        "centroid_lat": "18.0",
    }]


def test_legacy_dictreader_witnesses_header_as_data_artifact() -> None:
    text = "\nOBJECTID,canal,length_m,centroid_lon,centroid_lat\n1,Canal de Riego,1.0,-66.0,18.0\n"
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[0] == {None: ["OBJECTID", "canal", "length_m", "centroid_lon", "centroid_lat"]}


def test_parser_artifact_legacy_id_is_deterministic() -> None:
    assert stable_id("LOCAL", "Canal_de_Riego_features_summary.csv", 1) == "LOCAL_0548e0c995b6c895"


def test_recovered_manifest_keeps_identity_neutral() -> None:
    import json

    manifest = json.loads(Path("ontology/recovered_hydro_sources.v0.1.json").read_text(encoding="utf-8"))
    assert manifest["identity_effect"] == "none"
    assert manifest["production_mutation"] is False
    assert manifest["cross_manifestation_binding"]["independent_corroboration"] is False
    assert manifest["cross_manifestation_binding"]["relationship"] == "SAME_SOURCE_FEATURE_DERIVED_MANIFESTATION"


def test_recovered_denominators_and_projection_close() -> None:
    import json

    manifest = json.loads(Path("ontology/recovered_hydro_sources.v0.1.json").read_text(encoding="utf-8"))
    water = manifest["members"]["Waterworks_Integrated_v2.csv"]
    canal = manifest["members"]["Canal_de_Riego_features_summary.csv"]
    assert water["source_data_rows"] == 3202
    assert sum(water["dispositions"].values()) == 3202
    assert canal["source_data_rows"] == 3187
    assert canal["legacy_import_rows"] == 3188
    assert canal["legacy_parser_artifacts"] == 1
    p = manifest["bounded_reclassification_projection"]
    assert p["primary_classified"] + p["duplicate_derived_manifestations"] + p["excluded"] + p["unresolved"] == p["starting_source_rows"] == 8475
    assert p["class_known_source_rows"] == p["primary_classified"] + p["duplicate_derived_manifestations"] == 8245
    assert p["physical_asset_count_claimed"] is False
    assert p["pr_wide_exhaustion_claimed"] is False


def test_ledger_replay_partition_and_recovered_ids() -> None:
    decisions = []
    for n in range(1, 3203):
        decisions.append({
            "source_record_id": water_id(n),
            "source_ref": "Waterworks_Integrated_v2.csv",
            "legacy_asset_type_raw": "water",
            "legacy_asset_subtype_raw": "waterworks",
            "classification_state": "unresolved",
            "canonical_term_id": None,
            "evidence_basis": [],
        })
    for n in range(1, 3189):
        decisions.append({
            "source_record_id": canal_id(n),
            "source_ref": "Canal_de_Riego_features_summary.csv",
            "legacy_asset_type_raw": "water",
            "legacy_asset_subtype_raw": "canal_feature",
            "classification_state": "unresolved",
            "canonical_term_id": None,
            "evidence_basis": [],
        })
    for n in range(1867):
        decisions.append({
            "source_record_id": f"EXISTING_CLASSIFIED_{n}",
            "source_ref": "other",
            "legacy_asset_type_raw": "water",
            "legacy_asset_subtype_raw": "other",
            "classification_state": "provisional",
            "canonical_term_id": "AYL_TERM_OTHER",
            "evidence_basis": [],
        })
    for n in range(218):
        decisions.append({
            "source_record_id": f"EXISTING_UNRESOLVED_{n}",
            "source_ref": "other",
            "legacy_asset_type_raw": "water",
            "legacy_asset_subtype_raw": "other",
            "classification_state": "unresolved",
            "canonical_term_id": None,
            "evidence_basis": [],
        })
    report, rows = replay(decisions)
    assert len(rows) == 8475
    assert report["primary_classified"] == 5058
    assert report["duplicate_derived_manifestations"] == 3187
    assert report["class_known_source_rows"] == 8245
    assert report["excluded"] == 11
    assert report["unresolved"] == 219
    assert report["arithmetic_pass"] is True
