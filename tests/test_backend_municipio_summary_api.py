"""Contract tests for the municipio summary endpoint's monitoring join.

`GET /municipios/{name}/summary` joins each municipio's utility_asset records to
their monitoring readings via the asset_id prefix convention documented next to
`ASSET_PREFIX_TO_SOURCE_KINDS` in `server/backend/app.py` (e.g. `USDM_<fips>` for
drought, `USGS_<site_no>` for reservoir/usgs_peaks). These tests exercise that
join end-to-end through the real HTTP surface, not just the helper functions.
"""
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

MUN_ASSETS = [
    {
        "asset_id": "USDM_72001", "asset_name": "Adjuntas drought station",
        "asset_type": "environmental", "municipality": "Adjuntas", "status": "active",
    },
    {
        "asset_id": "USGS_50038290", "asset_name": "Río Grande de Arecibo at Adjuntas",
        "asset_type": "water", "municipality": "Adjuntas", "status": "active",
    },
    # An asset with no recognized monitoring-station prefix — must be ignored by the
    # join (still counted toward asset_count/active_assets, just not `monitoring`).
    {
        "asset_id": "PWR00099", "asset_name": "Unrelated substation",
        "asset_type": "power", "municipality": "Adjuntas", "status": "active",
    },
]

DROUGHT_ROWS = [
    {"reading_id": "d1", "asset_id": "USDM_72001", "site_no": "72001",
     "metric": "drought_category", "parameter_code": None, "value": 1, "unit": "category",
     "observed_date": "2026-08-09", "provisional": False},
    {"reading_id": "d2", "asset_id": "USDM_72001", "site_no": "72001",
     "metric": "drought_category", "parameter_code": None, "value": 2, "unit": "category",
     "observed_date": "2026-08-16", "provisional": False},
]

RESERVOIR_ROWS = [
    {"reading_id": "r1", "asset_id": "USGS_50038290", "site_no": "50038290",
     "metric": "streamflow", "parameter_code": "00060", "value": 310.0, "unit": "ft3/s",
     "observed_date": "2026-08-20", "provisional": False},
]

PEAKS_ROWS = [
    # Same physical gage as RESERVOIR_ROWS (shared USGS_ prefix) — confirms one asset
    # can join into two source kinds at once, per ingest_usgs_peaks.py's own docstring.
    {"reading_id": "p1", "asset_id": "USGS_50038290", "site_no": "50038290",
     "metric": "streamflow", "parameter_code": "00060", "value": 9800.0, "unit": "ft^3/s",
     "observed_date": "1998-09-21", "provisional": False},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    drought = tmp_path / "drought_conditions.jsonl"
    drought.write_text("".join(json.dumps(r) + "\n" for r in DROUGHT_ROWS), encoding="utf-8")
    reservoir = tmp_path / "reservoir_levels.jsonl"
    reservoir.write_text("".join(json.dumps(r) + "\n" for r in RESERVOIR_ROWS), encoding="utf-8")
    peaks = tmp_path / "usgs_peaks_readings.jsonl"
    peaks.write_text("".join(json.dumps(r) + "\n" for r in PEAKS_ROWS), encoding="utf-8")

    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["drought"], "path", drought)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["reservoir"], "path", reservoir)
    monkeypatch.setitem(backend.READING_VECTOR_REGISTRY["usgs_peaks"], "path", peaks)
    monkeypatch.setattr(backend.legacy, "_assets", MUN_ASSETS)
    monkeypatch.setattr(backend.legacy, "_events", [])
    with TestClient(backend.app) as test_client:
        yield test_client


def test_monitoring_join_picks_latest_reading_per_site(client):
    response = client.get("/municipios/Adjuntas/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["asset_count"] == 3
    monitoring = body["monitoring"]

    drought_items = [m for m in monitoring if m["kind"] == "drought"]
    assert len(drought_items) == 1
    # Latest by observed_date (2026-08-16, value 2), not the first/last row as written.
    assert drought_items[0]["value"] == 2
    assert drought_items[0]["site_no"] == "72001"

    # The unrelated substation and the shared USGS_ gage's two source kinds.
    kinds = {(m["kind"], m["site_no"]) for m in monitoring}
    assert ("reservoir", "50038290") in kinds
    assert ("usgs_peaks", "50038290") in kinds
    assert len(monitoring) == 3  # drought + reservoir + usgs_peaks; no entry for PWR00099


def test_municipio_with_no_monitoring_stations_returns_empty_list_not_error(client):
    response = client.get("/municipios/San Juan/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["asset_count"] == 0
    assert body["monitoring"] == []
