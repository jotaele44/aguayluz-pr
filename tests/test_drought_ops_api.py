"""API tests for the standalone drought operations surface."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.app as backend  # noqa: E402
import server.backend.drought_ops_api as drought  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    current = {
        "schema_version": "aguayluz.usdm-drought-operations/v0.1",
        "map_date": "2026-10-13",
        "retrieved_at": "2026-10-15T20:00:00Z",
        "authority": "NDMC/USDM (USDA/NOAA/NASA partnership)",
        "evidence_tier": "T1",
        "statistics": {
            "map_date": "2026-10-13", "None": 36, "D0": 64, "D1": 48,
            "D2": 28, "D3": 9, "D4": 0,
            "semantics": "cumulative_percent_area_at_or_above_category",
        },
        "history": [
            {"map_date": "2026-10-06", "D0": 61, "D1": 43, "D2": 24, "D3": 5, "D4": 0},
            {"map_date": "2026-10-13", "D0": 64, "D1": 48, "D2": 28, "D3": 9, "D4": 0},
        ],
        "footprint": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"category": "D3", "derived": False},
                "geometry": {"type": "Polygon", "coordinates": []},
            }],
        },
        "source_manifestations": {
            "statistics": {"sha256": "a" * 64},
            "geometry": {"sha256": "b" * 64},
        },
        "limitations": ["USDM is weekly."],
    }
    (tmp_path / drought.CURRENT_FILE).write_text(json.dumps(current), encoding="utf-8")
    (tmp_path / drought.MUNICIPIO_FILE).write_text(
        json.dumps({
            "site_no": "72079",
            "asset_name": "Lajas (USDM drought monitoring area)",
            "value": 3,
            "observed_date": "2026-10-13",
            "evidence_tier": "T1",
            "provisional": True,
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(drought, "DATA_DIR", tmp_path)
    return TestClient(backend.app)


def test_summary_preserves_cumulative_stats_and_municipio_date(client):
    response = client.get("/drought/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["map_date"] == "2026-10-13"
    assert body["statistics"]["D0"] == 64
    assert body["statistics"]["D3"] == 9
    assert body["municipio_date"] == "2026-10-13"
    assert body["municipios"][0]["municipio"] == "Lajas"
    assert body["municipios"][0]["category"] == "D3"
    assert body["change"]["direction"] == "worsened"


def test_footprint_returns_only_stored_official_geometry(client):
    body = client.get("/drought/footprint.geojson").json()
    assert body["type"] == "FeatureCollection"
    assert body["status"] == "available"
    assert body["features"][0]["properties"]["derived"] is False
    assert body["provenance"]["sha256"] == "b" * 64


def test_missing_artifact_is_explicit_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(drought, "DATA_DIR", tmp_path)
    client = TestClient(backend.app)
    summary = client.get("/drought/summary").json()
    footprint = client.get("/drought/footprint.geojson").json()
    assert summary["status"] == "unavailable"
    assert summary["statistics"] is None
    assert footprint["status"] == "unavailable"
    assert footprint["features"] == []
