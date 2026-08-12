"""End-to-end tests for calibrated thresholds, deduplication, and federation export."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.app as backend  # noqa: E402
from server.backend.monitoring_alert_operations import (  # noqa: E402
    lifecycle_alerts,
    resolve_threshold,
)
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    surface = tmp_path / "reservoir_levels.jsonl"
    rows = [
        {"site_no": "S1", "metric": "streamflow", "parameter_code": "00060", "unit": "ft3/s", "value": 6100.0, "observed_date": "2026-07-29T18:00:00Z"},
        {"site_no": "S1", "metric": "streamflow", "parameter_code": "00060", "unit": "ft3/s", "value": 6200.0, "observed_date": "2026-07-29T19:00:00Z"},
        {"site_no": "S2", "metric": "streamflow", "parameter_code": "00060", "unit": "ft3/s", "value": 6000.0, "observed_date": "2026-07-29T18:00:00Z"},
        {"site_no": "S2", "metric": "streamflow", "parameter_code": "00060", "unit": "ft3/s", "value": 1000.0, "observed_date": "2026-07-29T19:00:00Z"},
        {"site_no": "S3", "metric": "streamflow", "parameter_code": "00060", "unit": "ft3/s", "value": 9000.0, "observed_date": "2026-07-29T19:00:00Z", "provisional": True},
    ]
    surface.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    groundwater = tmp_path / "groundwater_levels.jsonl"
    groundwater.write_text("", encoding="utf-8")
    coastal = tmp_path / "coastal_levels.jsonl"
    coastal.write_text("", encoding="utf-8")
    peaks = tmp_path / "usgs_peaks_readings.jsonl"
    peaks.write_text("".join(json.dumps(row) + "\n" for row in [
        {"site_no": "P1", "metric": "streamflow", "parameter_code": "00060", "unit": "ft^3/s", "value": 284000.0, "observed_date": "2017-09-20"},
        {"site_no": "P1", "metric": "gage_height", "parameter_code": "00065", "unit": "ft", "value": 43.36, "observed_date": "2017-09-20"},
    ]), encoding="utf-8")
    field = tmp_path / "usgs_field_measurements_readings.jsonl"
    field.write_text(json.dumps({
        "site_no": "F1", "metric": "groundwater_level", "parameter_code": "72019",
        "unit": "ft", "value": 11.2, "observed_date": "2026-07-28",
    }) + "\n", encoding="utf-8")
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["reservoir"], "path", surface)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["groundwater"], "path", groundwater)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["coastal"], "path", coastal)
    # Isolate the new vectors too, or these tests read the developer's real data/ files
    # (they are gitignored, so CI would pass while local runs drifted).
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["usgs_peaks"], "path", peaks)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["usgs_field_measurements"], "path", field)
    with TestClient(backend.app) as test_client:
        yield test_client


def test_alerts_are_deduplicated_to_one_incident_per_site(client):
    body = client.get("/monitoring/alerts?metric=streamflow&state=all").json()
    assert body["total"] == 2
    by_site = {item["site_no"]: item for item in body["items"]}
    assert by_site["S1"]["state"] == "active"
    assert by_site["S1"]["evidence_count"] == 2
    assert by_site["S2"]["state"] == "resolved"


def test_active_and_resolved_filters_are_explicit(client):
    active = client.get("/monitoring/alerts?metric=streamflow&state=active").json()
    resolved = client.get("/monitoring/alerts?metric=streamflow&state=resolved").json()
    assert [item["site_no"] for item in active["items"]] == ["S1"]
    assert [item["site_no"] for item in resolved["items"]] == ["S2"]


def test_provisional_only_site_never_creates_incident(client):
    body = client.get("/monitoring/alerts?metric=streamflow&state=all").json()
    assert "S3" not in {item["site_no"] for item in body["items"]}


def test_site_threshold_override_requires_provenance_and_effective_date():
    registry = {
        "site_thresholds": {
            "streamflow": {
                "S1": {"direction": "above", "value": 7000.0, "severity": 5}
            }
        }
    }
    with pytest.raises(ValueError, match="site_threshold_without_provenance"):
        resolve_threshold("reservoir", "streamflow", "S1", registry)
    registry["site_thresholds"]["streamflow"]["S1"]["provenance"] = "approved_stage_table"
    with pytest.raises(ValueError, match="site_threshold_without_effective_date"):
        resolve_threshold("reservoir", "streamflow", "S1", registry)


def test_site_threshold_override_changes_lifecycle_deterministically():
    rows = [
        {"site_no": "S1", "metric": "streamflow", "unit": "ft3/s", "value": 6200.0, "observed_date": "2026-07-29T19:00:00Z"}
    ]
    registry = {
        "site_thresholds": {
            "streamflow": {
                "S1": {
                    "direction": "above",
                    "value": 7000.0,
                    "severity": 5,
                    "provenance": "approved_stage_table",
                    "effective_date": "2026-07-01",
                }
            }
        }
    }
    assert lifecycle_alerts("reservoir", "streamflow", rows, backend.legacy._parse_dt, registry) == []


def test_federation_export_contains_certified_lifecycle_counts(client):
    body = client.get("/export/federation/monitoring-alerts.json").json()
    assert body["contract"] == "aguayluz.monitoring.alert-incidents"
    assert body["certification"] == "certified-only"
    assert body["incident_count"] == 2
    assert body["active_count"] == 1
    assert body["resolved_count"] == 1
    assert all(item["dedup_key"] for item in body["items"])


def test_unknown_alert_state_fails_closed(client):
    response = client.get("/monitoring/alerts?state=pending")
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "unknown_alert_state"
