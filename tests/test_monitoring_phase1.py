"""End-to-end tests for freshness, provenance, alerts, and certified exports."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.app as backend  # noqa: E402
from server.backend.monitoring_quality import native_alerts, series_quality  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    surface = tmp_path / "reservoir_levels.jsonl"
    rows = [
        {"site_no": "R1", "metric": "reservoir_elevation", "parameter_code": "62615", "unit": "ft", "datum": "NAVD88", "value": 18.0, "observed_date": "2026-07-29T20:00:00Z"},
        {"site_no": "R1", "metric": "reservoir_storage_pct", "parameter_code": "00054", "unit": "%", "value": 25.0, "observed_date": "2026-07-29T20:00:00Z"},
        {"site_no": "S1", "metric": "streamflow", "parameter_code": "00060", "unit": "ft3/s", "value": 6000.0, "observed_date": "2026-07-29T20:00:00Z"},
        {"site_no": "S1", "metric": "gage_height", "parameter_code": "00065", "unit": "ft", "datum": "NAVD88", "value": 16.0, "observed_date": "2026-07-29T20:00:00Z", "provisional": True},
        {"site_no": "S1", "metric": "streamflow", "parameter_code": "00060", "unit": "ft", "value": 9999.0, "observed_date": "2026-07-29T20:00:00Z"},
    ]
    surface.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    groundwater = tmp_path / "groundwater_levels.jsonl"
    groundwater.write_text(json.dumps({
        "site_no": "G1", "metric": "groundwater_level", "parameter_code": "72019",
        "unit": "ft", "datum": "land_surface", "value": 55.0,
        "observed_date": "2026-07-29T20:00:00Z",
    }) + "\n", encoding="utf-8")
    coastal = tmp_path / "coastal_levels.jsonl"
    coastal.write_text(json.dumps({
        "site_no": "C1", "metric": "coastal_water_level", "parameter_code": "8665530",
        "unit": "ft", "datum": "MLLW", "value": 4.5,
        "observed_date": "2026-07-29T20:00:00Z",
    }) + "\n", encoding="utf-8")
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["reservoir"], "path", surface)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["groundwater"], "path", groundwater)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["coastal"], "path", coastal)
    with TestClient(backend.app) as test_client:
        yield test_client


def test_readings_expose_quality_and_provenance(client):
    body = client.get("/readings?kind=reservoir&metric=reservoir_elevation").json()
    assert body["provenance"]["threshold"]["provenance"] == "operator_policy_v1"
    assert body["quality"]["datum_status"] == "declared"
    assert body["quality"]["certified_count"] == 1


def test_wrong_unit_is_excluded_before_alerts_or_statistics(client):
    body = client.get("/readings?kind=reservoir&metric=streamflow").json()
    assert body["record_count"] == 1
    assert body["units"] == ["ft3/s"]
    assert body["mixed_units"] is False


def test_provisional_readings_are_not_certified_or_alerted(client):
    reading = client.get("/readings?kind=reservoir&metric=gage_height").json()
    assert reading["quality"]["provisional_count"] == 1
    assert reading["quality"]["certified_count"] == 0
    alerts = client.get("/monitoring/alerts?metric=gage_height").json()
    assert alerts["total"] == 0


def test_each_native_threshold_vector_can_alert(client):
    expected = {
        "reservoir_elevation", "reservoir_storage_pct", "streamflow",
        "groundwater_level", "coastal_water_level",
    }
    body = client.get("/monitoring/alerts").json()
    assert {alert["metric"] for alert in body["items"]} == expected
    assert all(alert["threshold"]["provenance"] for alert in body["items"])
    assert all(alert["certification"] == "certified" for alert in body["items"])


def test_health_accounts_for_all_six_vectors(client):
    body = client.get("/monitoring/health").json()
    assert body["series_count"] == 6
    assert set(body["vectors"]) == {
        "reservoir_elevation", "reservoir_storage_pct", "streamflow",
        "gage_height", "groundwater_level", "coastal_water_level",
    }
    assert all(vector["threshold_provenance"] for vector in body["vectors"].values())


def test_export_excludes_provisional_records(client):
    body = client.get("/export/monitoring.json").json()
    by_metric = {series["metric"]: series for series in body["series"]}
    assert by_metric["gage_height"]["certified_record_count"] == 0
    assert by_metric["gage_height"]["items"] == []
    assert len(by_metric) == 6


def test_stale_and_missing_datum_are_explicit():
    rows = [{"value": 1.0, "observed_date": "2026-01-01T00:00:00Z", "unit": "ft"}]
    quality = series_quality(
        "reservoir_elevation",
        rows,
        backend.legacy._parse_dt,
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert quality["freshness"] == "stale"
    assert quality["datum_status"] == "missing"


def test_threshold_without_provenance_fails_closed(monkeypatch):
    threshold = backend.SERIES_METADATA_REGISTRY["streamflow"]["threshold"]
    monkeypatch.setitem(threshold, "provenance", "")
    with pytest.raises(ValueError, match="threshold_without_provenance"):
        native_alerts("streamflow", [], backend.legacy._parse_dt)
