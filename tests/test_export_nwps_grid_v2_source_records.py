from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.export_nwps_grid_v2_source_records import (
    COORDINATE_EVIDENCE_STATE,
    ExportError,
    export_rows,
    write_outputs,
)


def _row(record_id: str = "NWPS_GAUGE:TEST:REV:1") -> dict:
    return {
        "lid": "TEST",
        "name": "Test Gauge",
        "latitude": 18.25,
        "longitude": -66.10,
        "record_id": record_id,
        "bulk_manifestation_id": "HYDROMET:nwps_gauges:abc123",
        "retrieved_at": "2026-10-16T03:09:02Z",
        "usgs_id": "50000000",
        "asset_id": "USGS_50000000",
    }


def test_export_preserves_source_identity_without_assigning_cells():
    bindings, records, receipt = export_rows([_row()])
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding["Repository"] == "aguayluz-pr"
    assert binding["Source_CRS"] == "EPSG:4326"
    assert binding["Source_X"] == -66.10
    assert binding["Source_Y"] == 18.25
    assert binding["Coordinate_Evidence_State"] == COORDINATE_EVIDENCE_STATE
    assert "Cell_ID" not in binding
    assert records == [
        {
            "Repository": "aguayluz-pr",
            "Record_ID": "NWPS_GAUGE:TEST:REV:1",
            "Category": "NWPS_GAUGE",
            "Source_System": "NWPS API v1",
            "Source_LID": "TEST",
            "Source_Manifestation_ID": "HYDROMET:nwps_gauges:abc123",
            "Source_Retrieved_At": "2026-10-16T03:09:02Z",
            "Name": "Test Gauge",
            "USGS_ID": "50000000",
            "Asset_ID": "USGS_50000000",
        }
    ]
    assert receipt["Input_Record_Count"] == 1
    assert receipt["Unique_Record_ID_Count"] == 1
    assert receipt["State"] == "PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("record_id", None),
        ("latitude", None),
        ("longitude", None),
        ("bulk_manifestation_id", ""),
        ("retrieved_at", ""),
        ("lid", ""),
    ],
)
def test_missing_identity_coordinate_or_provenance_fails_closed(field, value):
    row = _row()
    row[field] = value
    with pytest.raises(ExportError):
        export_rows([row])


def test_duplicate_record_identity_fails_closed():
    with pytest.raises(ExportError, match="duplicate record_id"):
        export_rows([_row(), _row()])


def test_real_nwps_snapshot_is_exportable_and_receipt_hashes_match(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data/nwps_gauge_state.jsonl"
    if not source.exists():
        pytest.skip("repository snapshot not present")

    binding_out = tmp_path / "binding_input.jsonl"
    records_out = tmp_path / "records.jsonl"
    receipt_out = tmp_path / "receipt.json"
    receipt = write_outputs(
        source=source,
        binding_out=binding_out,
        records_out=records_out,
        receipt_out=receipt_out,
    )

    assert receipt["Input_Record_Count"] > 0
    assert receipt["Binding_Input_Record_Count"] == receipt["Input_Record_Count"]
    assert receipt["Profile_Record_Count"] == receipt["Input_Record_Count"]
    assert receipt["Unique_Record_ID_Count"] == receipt["Input_Record_Count"]
    assert receipt["Source_Manifestation_Count"] >= 1
    assert receipt["Binding_Input_SHA256"] == hashlib.sha256(binding_out.read_bytes()).hexdigest()
    assert receipt["Profile_Records_SHA256"] == hashlib.sha256(records_out.read_bytes()).hexdigest()

    rows = [json.loads(line) for line in binding_out.read_text().splitlines() if line]
    assert all(row["Repository"] == "aguayluz-pr" for row in rows)
    assert all(row["Coordinate_Evidence_State"] == COORDINATE_EVIDENCE_STATE for row in rows)
    assert all("Cell_ID" not in row for row in rows)
