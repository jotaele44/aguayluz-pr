"""Focused contracts for modern USGS Water Data API category coverage."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def load_script(name: str):
    path = REPO / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_api_key_is_header_only(monkeypatch):
    from aguayluz.usgs_water_api import api_headers, source_receipt

    monkeypatch.setenv("USGS_API_KEY", "secret-value")
    assert api_headers() == {"X-Api-Key": "secret-value"}
    receipt = source_receipt(
        category="continuous_values",
        source_url="https://example.test",
        rows_written=1,
        skipped={},
        live=True,
    )
    serialized = json.dumps(receipt)
    assert "secret-value" not in serialized
    assert receipt["api_key_present"] is True
    assert receipt["credential_material_persisted"] is False


def test_continuous_parser_isolates_timestamp_and_provisional_state():
    module = load_script("ingest_usgs_continuous.py")
    documents = [
        {
            "features": [
                {
                    "properties": {
                        "monitoring_location_id": "USGS-50059000",
                        "parameter_code": "00060",
                        "value": "12.5",
                        "unit_of_measure": "ft3/s",
                        "time": "2026-08-03T12:15:00-04:00",
                        "approvals_status": ["Working"],
                    }
                },
                {
                    "properties": {
                        "monitoring_location_id": "USGS-50059000",
                        "parameter_code": "00060",
                        "value": "13.0",
                        "unit_of_measure": "ft3/s",
                        "time": "2026-08-03T12:30:00-04:00",
                        "approvals_status": ["Approved"],
                    }
                },
            ]
        }
    ]
    rows, skipped = module.rows_from_documents(documents)
    assert len(rows) == 2
    assert rows[0]["reading_id"] != rows[1]["reading_id"]
    assert rows[0]["provisional"] is True
    assert rows[1]["provisional"] is False
    assert skipped == {
        "unsupported_parameter": 0,
        "missing_value": 0,
        "missing_identity": 0,
    }


def test_metadata_parser_preserves_thresholds_and_publication_gap(monkeypatch):
    module = load_script("ingest_usgs_time_series_metadata.py")
    documents = [
        {
            "features": [
                {
                    "id": "series-1",
                    "properties": {
                        "monitoring_location_id": "USGS-50059000",
                        "parameter_code": "00060",
                        "parameter_name": "Discharge",
                        "unit_of_measure": "ft3/s",
                        "begin": "2000-01-01T00:00:00",
                        "end": "2026-08-01T00:00:00",
                        "thresholds": [{"name": "action", "value": 50}],
                        "data_gap_interval": "P2D",
                    },
                }
            ]
        }
    ]
    rows = module.metadata_rows(documents, stale_days=7)
    assert rows[0]["operational_thresholds"][0]["name"] == "action"
    assert rows[0]["freshness_status"] == "publication_gap"


def test_field_measurements_flag_nonstatic_and_keep_negative_values():
    module = load_script("ingest_usgs_field_measurements.py")
    documents = [
        {
            "features": [
                {
                    "properties": {
                        "monitoring_location_id": "USGS-180046067053700",
                        "parameter_code": "72019",
                        "value": "-1.5",
                        "unit_of_measure": "ft",
                        "year": 2026,
                        "month": 1,
                        "day": 2,
                        "qualifier": ["Flowing"],
                    }
                }
            ]
        }
    ]
    rows, assets, skipped = module.rows_from_documents(documents)
    assert assets[0]["asset_id"] == "USGSFM_180046067053700"
    assert rows[0]["value"] == -1.5
    assert rows[0]["review_status"] == "needs_review"
    assert skipped["nonstatic_qualifier"] == 1


def test_peak_qualifiers_participate_in_identity():
    module = load_script("ingest_usgs_peaks.py")
    base = {
        "monitoring_location_id": "USGS-50029000",
        "peak_date": "2017-09-20",
        "peak_discharge": "284000",
        "peak_gage_height": "30.0",
    }
    documents = [
        {
            "features": [
                {"properties": {**base, "peak_discharge_qualifiers": ["A"]}},
                {"properties": {**base, "peak_discharge_qualifiers": ["B"]}},
            ]
        }
    ]
    rows, _ = module.rows_from_documents(documents)
    discharge_ids = [row["reading_id"] for row in rows if row["parameter_code"] == "00060"]
    assert len(discharge_ids) == 2
    assert len(set(discharge_ids)) == 2


def test_water_quality_assets_are_stable_and_owned():
    module = load_script("ingest_usgs_water_quality.py")
    rows = [{
        "MonitoringLocationIdentifier": "USGS-50059000",
        "MonitoringLocationName": "Rio Test",
        "LatitudeMeasure": "18.1",
        "LongitudeMeasure": "-66.5",
        "OrganizationIdentifier": "USGS-PR",
    }]
    assets = module.asset_rows(rows)
    assert assets[0]["asset_id"] == "USGSWQ_50059000"
    assert assets[0]["geometry_type"] == "point"


def test_water_quality_nondetect_is_preserved_not_zero():
    module = load_script("ingest_usgs_water_quality.py")
    source = [
        {
            "MonitoringLocationIdentifier": "USGS-50059000",
            "ActivityStartDate": "2026-01-02",
            "CharacteristicName": "Lead",
            "ResultMeasureValue": "",
            "ResultDetectionConditionText": "Not Detected",
            "ResultMeasure/MeasureUnitCode": "ug/L",
            "OrganizationIdentifier": "USGS-PR",
            "ActivityIdentifier": "A1",
            "ResultIdentifier": "R1",
        }
    ]
    readings, censored, skipped = module.result_rows(source)
    assert readings == []
    assert len(censored) == 1
    assert censored[0]["detection_condition"] == "Not Detected"
    assert censored[0]["reported_value"] is None
    assert skipped["nondetect"] == 1


def test_rtfi_only_creates_declared_nwis_edges():
    module = load_script("ingest_usgs_rtfi.py")
    document = [
        {"id": 1, "name": "Road", "nwis_id": "USGS-50059000", "active": True},
        {"id": 2, "name": "Building", "active": True},
    ]
    locations, edges = module.parse(document)
    assert len(locations) == 2
    assert len(edges) == 1
    assert edges[0]["authoritative_association"] is True
    assert edges[0]["from_id"] == "USGS_50059000"


def test_nims_image_listing_performs_no_visual_inference():
    module = load_script("ingest_usgs_nims.py")
    camera = {
        "camera_id": "PR_TEST",
        "site_no": "50059000",
        "overlay_dir": "https://example.test/images/",
    }
    rows = module.image_rows(
        camera,
        [{"filename": "image.jpg", "timestamp": "2026-08-03T10:00:00Z", "fs": 123}],
    )
    assert rows[0]["image_url"].endswith("image.jpg")
    assert rows[0]["visual_inference_performed"] is False


def test_statistics_never_replace_local_percentiles():
    module = load_script("ingest_usgs_statistics.py")
    document = {
        "items": [
            {
                "monitoring_location_id": "USGS-50059000",
                "parameter_code": "00060",
                "computation_type": "percentile",
                "normal_type": "DOY",
                "start_date": "08-03",
                "end_date": "08-03",
                "value": "12.5",
            }
        ]
    }
    rows = module.normalize(document, "observationNormals")
    assert rows[0]["local_percentile_replaced"] is False
    assert rows[0]["cross_validation_status"] == "pending"


def test_coverage_matrix_is_complete_and_non_strict_valid():
    module = load_script("validate_usgs_api_coverage.py")
    document = json.loads(
        (REPO / "config" / "usgs_water_api_coverage.json").read_text(encoding="utf-8")
    )
    assert {item["id"] for item in document["categories"]} == module.EXPECTED_IDS
    assert module.validate_document(document, REPO) == []


@pytest.mark.parametrize("cadence", ["fast", "daily", "weekly", "all"])
def test_coverage_gate_is_scheduled_before_derived_layers(cadence):
    refresh = load_script("refresh.py")
    scripts = [step[1][0] for step in refresh.PLANS[cadence]]
    assert "scripts/validate_usgs_api_coverage.py" in scripts
    assert scripts.index("scripts/validate_usgs_api_coverage.py") < scripts.index(
        "scripts/build_water_power_crosswalk.py"
    )
