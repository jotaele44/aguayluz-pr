"""End-to-end contract tests for the canonical metric-safe readings API."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.app as backend  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

ROWS = [
    {"site_no": "R1", "metric": "reservoir_elevation", "parameter_code": "62615", "unit": "ft", "value": 40.0, "observed_date": "2026-01-01"},
    {"site_no": "R1", "metric": "reservoir_elevation", "parameter_code": "62615", "unit": "ft", "value": 41.0, "observed_date": "2026-02-01"},
    {"site_no": "R1", "metric": "reservoir_storage_pct", "parameter_code": "00054", "unit": "%", "value": 73.0, "observed_date": "2026-02-01"},
    {"site_no": "S1", "metric": "streamflow", "parameter_code": "00060", "unit": "ft3/s", "value": 120.0, "observed_date": "2026-02-01"},
    {"site_no": "S1", "metric": "gage_height", "parameter_code": "00065", "unit": "ft", "value": 3.5, "observed_date": "2026-02-01"},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    surface = tmp_path / "reservoir_levels.jsonl"
    surface.write_text("".join(json.dumps(row) + "\n" for row in ROWS), encoding="utf-8")
    groundwater = tmp_path / "groundwater_levels.jsonl"
    groundwater.write_text(json.dumps({
        "site_no": "G1", "metric": "groundwater_level", "parameter_code": "72019",
        "unit": "ft", "value": 12.5, "observed_date": "2026-02-01",
    }) + "\n", encoding="utf-8")
    coastal = tmp_path / "coastal_levels.jsonl"
    coastal.write_text(json.dumps({
        "site_no": "C1", "metric": "coastal_water_level", "parameter_code": "8665530",
        "unit": "ft", "value": 1.8, "observed_date": "2026-02-01",
    }) + "\n", encoding="utf-8")

    peaks = tmp_path / "usgs_peaks_readings.jsonl"
    peaks.write_text("".join(json.dumps(row) + "\n" for row in [
        # `ft^3/s` verbatim, exactly as the USGS OGC API publishes it — see below.
        {"site_no": "P1", "metric": "streamflow", "parameter_code": "00060",
         "unit": "ft^3/s", "value": 284000.0, "observed_date": "2017-09-20"},
        {"site_no": "P1", "metric": "gage_height", "parameter_code": "00065",
         "unit": "ft", "value": 43.36, "observed_date": "2017-09-20"},
    ]), encoding="utf-8")
    field = tmp_path / "usgs_field_measurements_readings.jsonl"
    field.write_text(json.dumps({
        "site_no": "F1", "metric": "groundwater_level", "parameter_code": "72019",
        "unit": "ft", "value": 11.2, "observed_date": "2026-07-28",
    }) + "\n", encoding="utf-8")

    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["reservoir"], "path", surface)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["groundwater"], "path", groundwater)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["coastal"], "path", coastal)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["usgs_peaks"], "path", peaks)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["usgs_field_measurements"], "path", field)
    with TestClient(backend.app) as test_client:
        yield test_client


def test_unknown_kind_and_metric_fail_closed(client):
    assert client.get("/readings?kind=unknown&metric=streamflow").status_code == 400
    assert client.get("/readings?kind=reservoir&metric=unknown").status_code == 400
    assert client.get("/readings?kind=reservoir").status_code == 400


@pytest.mark.parametrize(
    ("kind", "metric", "unit"),
    [
        ("reservoir", "reservoir_elevation", "ft"),
        ("reservoir", "reservoir_storage_pct", "%"),
        ("reservoir", "streamflow", "ft3/s"),
        ("reservoir", "gage_height", "ft"),
        ("groundwater", "groundwater_level", "ft"),
        ("coastal", "coastal_water_level", "ft"),
        ("usgs_field_measurements", "groundwater_level", "ft"),
        ("usgs_peaks", "streamflow", "ft^3/s"),
        ("usgs_peaks", "gage_height", "ft"),
    ],
)
def test_every_vector_is_independently_observable(client, kind, metric, unit):
    response = client.get(f"/readings?kind={kind}&metric={metric}")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == kind
    assert body["metric"] == metric
    assert body["record_count"] >= 1
    assert body["units"] == [unit]
    assert body["mixed_units"] is False
    assert {row["metric"] for row in body["items"]} == {metric}


def test_site_parameter_and_time_filters(client):
    response = client.get(
        "/readings?kind=reservoir&metric=reservoir_elevation"
        "&site_no=R1&parameter_code=62615"
        "&since=2026-01-15T00:00:00Z&until=2026-02-15T00:00:00Z"
    )
    body = response.json()
    assert body["record_count"] == 1
    assert body["site_count"] == 1
    assert body["parameter_codes"] == ["62615"]
    assert body["items"][0]["observed_date"] == "2026-02-01"


def test_invalid_time_bounds_fail_closed(client):
    assert client.get("/readings?kind=coastal&metric=coastal_water_level&since=nope").status_code == 400
    assert client.get(
        "/readings?kind=coastal&metric=coastal_water_level"
        "&since=2026-03-01&until=2026-02-01"
    ).status_code == 400


def test_response_never_mixes_surface_units(client):
    for metric in ("reservoir_elevation", "reservoir_storage_pct", "streamflow", "gage_height"):
        body = client.get(f"/readings?kind=reservoir&metric={metric}").json()
        assert len(body["units"]) <= 1
        assert body["mixed_units"] is False


# ── the (kind, metric) re-key ─────────────────────────────────────────────────
def test_caret_streamflow_unit_is_not_silently_dropped(client):
    """Regression. The USGS OGC peaks API publishes ``unit_of_measure: "ft^3/s"`` and
    scripts/ingest_usgs_peaks.py stores it verbatim, but the reservoir whitelist is
    ``{"ft3/s", "ft³/s"}`` and ``_series_rows`` filters on exact unit membership. Measured
    against the real 8,317-row corpus before this was fixed: **0 of 4,104** streamflow
    peaks survived, so a fully populated file rendered an empty chart.
    """
    body = client.get("/readings?kind=usgs_peaks&metric=streamflow").json()
    assert body["record_count"] == 1
    assert body["units"] == ["ft^3/s"]
    assert body["items"][0]["value"] == 284000.0


def test_each_vector_reports_its_own_provenance_not_a_borrowed_one(client):
    """The whole point of keying on (kind, metric).

    `streamflow` and `gage_height` belong to both `reservoir` and `usgs_peaks`;
    `groundwater_level` to both `groundwater` and `usgs_field_measurements`. Keyed on
    metric alone, the peaks series reported the reservoir policy — a >5,000 ft3/s
    threshold that 46% of the 1899-2025 record exceeds, graded against a 24-hour
    freshness limit.
    """
    peaks = client.get("/readings?kind=usgs_peaks&metric=streamflow").json()
    reservoir = client.get("/readings?kind=reservoir&metric=streamflow").json()
    assert peaks["provenance"]["kind"] == "usgs_peaks"
    assert reservoir["provenance"]["kind"] == "reservoir"
    assert peaks["provenance"]["threshold"] is None
    assert reservoir["provenance"]["threshold"]["value"] == 5000.0

    field = client.get("/readings?kind=usgs_field_measurements&metric=groundwater_level").json()
    gw = client.get("/readings?kind=groundwater&metric=groundwater_level").json()
    assert field["provenance"]["kind"] == "usgs_field_measurements"
    assert gw["provenance"]["kind"] == "groundwater"
    assert field["items"][0]["site_no"] == "F1"      # distinct corpora, not one file
    assert gw["items"][0]["site_no"] == "G1"


def test_a_historical_series_is_not_reported_as_stale(client):
    """A 2017 annual peak is the correct latest value, not a degraded feed."""
    body = client.get("/readings?kind=usgs_peaks&metric=streamflow").json()
    assert body["quality"]["freshness"] == "not_applicable"
    assert body["quality"]["freshness_limit_hours"] is None
    assert body["quality"]["ingest_health"] == "healthy"


def test_peaks_require_an_explicit_metric(client):
    """Two metrics share the corpus, so defaulting would silently pick one."""
    assert client.get("/readings?kind=usgs_peaks").status_code == 400


def test_reference_series_raise_no_incidents(client):
    body = client.get("/monitoring/alerts?kind=usgs_peaks&state=all").json()
    assert body["items"] == []
