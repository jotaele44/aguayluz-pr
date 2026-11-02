"""/gis/* endpoints on the served app (server.backend.app) over the committed corpora."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
jsonschema = pytest.importorskip("jsonschema")

import server.backend.app as backend  # noqa: E402
import server.backend.gis_wiring as wiring  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client():
    with TestClient(backend.app) as c:
        yield c


@pytest.fixture(scope="module")
def proxy_edge():
    rows = [json.loads(line) for line in (ROOT / "data" / "alert_dependency_edges.jsonl").read_text().splitlines() if line]
    return next(r for r in rows if r.get("dependency_type") == "energizes")


def test_catalog_validates_and_marks_karst_unavailable(client):
    document = client.get("/gis/catalog").json()
    jsonschema.validate(document, _schema("gis_layer_catalog_v1.schema.json"))
    by_id = {layer["layer_id"]: layer for layer in document["layers"]}
    assert by_id["power_assets"]["data_available"] is True
    assert by_id["cave_karst"]["data_available"] is False


def test_asset_layers_split_by_type_and_lines_are_served(client):
    power = client.get("/gis/layers/power_assets.geojson").json()["features"]
    assert power and all(f["properties"]["asset_type"] == "power" for f in power)
    lines = client.get("/gis/layers/asset_dependencies.geojson").json()["features"]
    assert lines and all(f["geometry"]["type"] == "LineString" for f in lines)
    assert client.get("/gis/layers/not_a_layer.geojson").status_code == 404


def test_query_validates_and_counts_match_a_direct_bbox_count(client):
    west, south, east, north = -66.2, 18.3, -65.9, 18.5
    expected = sum(
        1
        for f in client.get("/gis/layers/water_assets.geojson").json()["features"]
        if west <= f["geometry"]["coordinates"][0] <= east and south <= f["geometry"]["coordinates"][1] <= north
    )
    body = {"geometry": {"type": "bbox", "west": west, "south": south, "east": east, "north": north},
            "layers": ["water_assets"], "limit_per_layer": 5000}
    payload = client.post("/gis/query", json=body).json()
    jsonschema.validate(payload, _schema("gis_query_v1.schema.json"))
    assert payload["total_matched"] == expected > 0


def test_identify_reports_municipio_and_barrio(client):
    payload = client.get("/gis/identify", params={"lon": -66.1057, "lat": 18.4655, "layers": "municipios"}).json()
    assert payload["location"]["municipio"]["name"] == "San Juan"
    assert payload["hits"][0]["layer_id"] == "municipios"


def test_trace_upstream_from_a_pump_returns_its_proxy_supplier(client, proxy_edge):
    payload = client.get(
        "/gis/trace", params={"feature_id": proxy_edge["to_node_id"], "direction": "upstream"}
    ).json()
    supplier = next(h for h in payload["hits"] if h["feature_id"] == proxy_edge["from_node_id"])
    assert supplier["evidence_required"] is True
    assert supplier["confidence"] == float(proxy_edge["confidence"])
    assert payload["unverified_links_used"] is True and payload["notes"]


def test_scenario_validates_is_hypothesis_and_names_municipios(client, proxy_edge):
    body = {"selected": [{"layer_id": "power_assets", "feature_id": proxy_edge["from_node_id"]}]}
    payload = client.post("/gis/scenario", json=body).json()
    jsonschema.validate(payload, _schema("gis_scenario_result_v1.schema.json"))
    assert payload["evidence_state"] == "HYPOTHESIS"
    assert payload["unverified_links_used"] is True
    assert proxy_edge["to_node_id"] in {i["feature_id"] for i in payload["impacted"]}
    assert payload["affected_areas"] and all(a["area_type"] == "municipio" for a in payload["affected_areas"])


def test_history_and_documents(client, proxy_edge, monkeypatch):
    history = client.get(f"/gis/features/power_assets/{proxy_edge['from_node_id']}/history").json()
    assert history["kind"] == "alert_timeline" and isinstance(history["items"], list)
    assert client.get("/gis/features/barrios/x/history").status_code == 404
    empty = client.get("/gis/features/municipios/72127/documents").json()
    assert empty["name"] == "San Juan"
    monkeypatch.setattr(backend, "_jp_flood_document_for_municipio", lambda name: {"municipality": name})
    bound = client.get("/gis/features/municipios/72127/documents").json()
    assert bound["documents"][0]["url"] == "/municipios/San Juan/flood-document/file"


def test_export_refuses_blocked_layers_and_exports_public_ones(client):
    aoi = {"type": "radius", "lon": -66.1, "lat": 18.4, "radius_m": 2000}
    assert client.post("/gis/export", json={"geometry": aoi, "layers": ["cave_karst"], "format": "csv"}).status_code == 403
    resp = client.post("/gis/export", json={"geometry": aoi, "layers": ["water_assets"], "format": "csv"})
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows and all(r["layer_id"] == "water_assets" for r in rows)


def test_karst_loader_never_serves_geometry():
    import asyncio

    features, manifest = asyncio.run(wiring.feature_loader("cave_karst"))
    assert features == [] and manifest["exists"] is False
