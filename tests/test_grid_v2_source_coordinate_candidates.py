"""Grid V2 source-coordinate candidate export gates for AguaYLuz USGS locations."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/export_pr_grid_v2_source_coordinate_candidates.py"


def _module():
    spec = importlib.util.spec_from_file_location("grid_v2_candidate_export", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_native_t1_location_is_eligible_and_unbound():
    m = _module()
    rows = [
        {
            "location_id": "USGS-50000000",
            "lon": -66.0,
            "lat": 18.35,
            "source_ref": "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items",
            "evidence_tier": "T1",
        }
    ]
    candidates, skipped = m.build_candidates(rows)
    assert skipped == {
        "missing_identity": 0,
        "missing_coordinates": 0,
        "out_of_pr_bounds": 0,
        "non_t1_source": 0,
        "missing_source_ref": 0,
    }
    assert candidates == [
        {
            "Contract": "pr-grid-v2-source-coordinate-candidate/1.0",
            "Repository": "aguayluz-pr",
            "Record_ID": "USGS-50000000",
            "Source_X": -66.0,
            "Source_Y": 18.35,
            "Source_CRS": "EPSG:4326",
            "Coordinate_Evidence_State": "VERIFIED_SOURCE_COORDINATE",
            "Uncertainty_Class": "EXACT",
            "Spatial_Role": "MONITORING_LOCATION",
            "Source_Ref": "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items",
            "Evidence_Tier": "T1",
            "Candidate_State": "SOURCE_COORDINATE_ELIGIBLE_NOT_BOUND",
            "Geometry_Authority": "spiderweb-pr",
            "Cell_ID": None,
        }
    ]


def test_non_source_native_rows_are_not_promoted():
    m = _module()
    rows = [
        {"location_id": "missing", "evidence_tier": "T1", "source_ref": "x"},
        {
            "location_id": "weak",
            "lon": -66.1,
            "lat": 18.2,
            "evidence_tier": "T2",
            "source_ref": "x",
        },
        {
            "location_id": "no-ref",
            "lon": -66.1,
            "lat": 18.2,
            "evidence_tier": "T1",
        },
        {
            "location_id": "outside",
            "lon": -70.0,
            "lat": 18.2,
            "evidence_tier": "T1",
            "source_ref": "x",
        },
    ]
    candidates, skipped = m.build_candidates(rows)
    assert candidates == []
    assert skipped["missing_coordinates"] == 1
    assert skipped["non_t1_source"] == 1
    assert skipped["missing_source_ref"] == 1
    assert skipped["out_of_pr_bounds"] == 1


def test_duplicate_identity_fails_closed_even_when_coordinates_match():
    m = _module()
    row = {
        "location_id": "USGS-50000000",
        "lon": -66.0,
        "lat": 18.35,
        "source_ref": "source",
        "evidence_tier": "T1",
    }
    with pytest.raises(m.CandidateExportError, match="duplicate"):
        m.build_candidates([row, dict(row)])


def test_export_receipt_hash_binds_source_and_candidate_bytes(tmp_path):
    m = _module()
    source = tmp_path / "locations.jsonl"
    source.write_text(
        json.dumps(
            {
                "location_id": "USGS-50000000",
                "lon": -66.0,
                "lat": 18.35,
                "source_ref": "source",
                "evidence_tier": "T1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "candidates.jsonl"
    receipt_path = tmp_path / "receipt.json"
    receipt = m.export_candidates(source, output, receipt_path)

    assert receipt["Source_Row_Count"] == 1
    assert receipt["Eligible_Candidate_Count"] == 1
    assert receipt["Cell_ID_Materialized"] is False
    assert receipt["Geometry_Authority"] == "spiderweb-pr"
    assert receipt["State"] == "PASS"
    assert receipt_path.is_file()
    candidate = json.loads(output.read_text())
    assert candidate["Cell_ID"] is None


def test_missing_source_fails_without_overwriting_last_good_output(tmp_path):
    m = _module()
    output = tmp_path / "candidates.jsonl"
    output.write_text("last-good\n", encoding="utf-8")
    receipt = tmp_path / "receipt.json"

    with pytest.raises(m.CandidateExportError, match="unavailable"):
        m.export_candidates(tmp_path / "missing.jsonl", output, receipt)

    assert output.read_text(encoding="utf-8") == "last-good\n"
    assert not receipt.exists()
