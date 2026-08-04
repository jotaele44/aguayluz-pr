from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import server.backend.app as target  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "water-asset-graph" / "v0.1"


def _fixture_assets():
    return [
        {
            "asset_id": "PWR_TEST_1",
            "asset_name": "Test Substation",
            "asset_type": "power",
            "asset_subtype": "substation",
            "operator": "PREPA",
            "municipality": "Arecibo",
            "lat": 18.47,
            "lon": -66.72,
            "geometry_type": "point",
            "status": "active",
            "source_ref": "PREPA:TEST",
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": 90,
            "review_status": "accepted",
        },
        {
            "asset_id": "WATER_TEST_1",
            "asset_name": "Test Pump Station",
            "asset_type": "water",
            "asset_subtype": "pump_station",
            "operator": "AAA",
            "municipality": "Arecibo",
            "lat": 18.46,
            "lon": -66.71,
            "geometry_type": "point",
            "status": "active",
            "source_ref": "AAA:TEST",
            "source_hash": None,
            "evidence_tier": "T2",
            "confidence": 65,
            "review_status": "accepted",
        },
        {
            "asset_id": "VALVE_TEST_1",
            "asset_name": "Exact Control Valve",
            "asset_type": "water",
            "asset_subtype": "control_valve",
            "operator": "AAA",
            "municipality": "Barceloneta",
            "lat": 18.45,
            "lon": -66.54,
            "geometry_type": "point",
            "status": "active",
            "source_ref": "AAA:RESTRICTED",
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": 95,
            "review_status": "accepted",
        },
    ]


def _validate_switchboard_schema(payload):
    graph_schema = json.loads((SCHEMA_DIR / "water_asset_graph.schema.json").read_text())
    relationship_schema = json.loads(
        (SCHEMA_DIR / "water_asset_relationship.schema.json").read_text()
    )
    registry = Registry().with_resource(
        relationship_schema["$id"], Resource.from_contents(relationship_schema)
    )
    Draft202012Validator(graph_schema, registry=registry).validate(payload)


def test_switchboard_is_deterministic_and_propagates_only_declared_edges(monkeypatch):
    monkeypatch.setattr(target.legacy, "_assets", _fixture_assets())
    monkeypatch.setattr(
        target.legacy,
        "_alerts",
        [
            {
                "alert_id": "ALERT_TEST_1",
                "asset_id": "PWR_TEST_1",
                "linked_asset_ids": ["PWR_TEST_1"],
                "status": "active",
                "review_status": "accepted",
                "evidence_tier": "T1",
                "confidence": 90,
                "module_id": "HYDRO_OPS",
                "source_title": "Confirmed power loss",
                "source_ref": "TEST:ALERT",
                "start_at": "2026-08-01T12:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        target.legacy,
        "_alert_edges",
        [
            {
                "edge_id": "EDGE-TEST-1",
                "from_node_id": "PWR_TEST_1",
                "to_node_id": "WATER_TEST_1",
                "dependency_type": "energizes",
                "confidence": 55,
                "evidence_required": True,
                "notes": "Test proximity proxy",
            }
        ],
    )
    monkeypatch.setattr(
        target.legacy,
        "_municipios_geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"NAME": "Arecibo"}, "geometry": None},
                {"type": "Feature", "properties": {"NAME": "Barceloneta"}, "geometry": None},
            ],
        },
    )
    monkeypatch.setattr(target, "read_events", lambda: [])
    monkeypatch.setattr(target, "_crosswalk_aliases", lambda: ({}, {}))

    first = target._asset_switchboard("public")
    second = target._asset_switchboard("public")
    _validate_switchboard_schema(first)
    assert first["baseline_id"] == second["baseline_id"]
    assert first["inventory"]["duplicate_canonical_id_count"] == 0

    by_id = {item["asset_id"]: item for item in first["assets"]}
    assert by_id["PWR_TEST_1"]["impact_status"] == "confirmed"
    assert by_id["WATER_TEST_1"]["impact_status"] == "derived"
    assert by_id["WATER_TEST_1"]["hop_count"] == 1
    assert by_id["VALVE_TEST_1"]["lat"] is None
    assert by_id["VALVE_TEST_1"]["source_ref"] == "restricted"
    assert first["relationships"][0]["relationship_id"]


def test_linked_asset_confidence_does_not_confirm(monkeypatch):
    monkeypatch.setattr(target.legacy, "_assets", _fixture_assets()[:1])
    monkeypatch.setattr(
        target.legacy,
        "_alerts",
        [
            {
                "alert_id": "ALERT_TEST_2",
                "asset_id": None,
                "linked_asset_ids": ["PWR_TEST_1"],
                "status": "active",
                "review_status": "accepted",
                "evidence_tier": "T1",
                "confidence": 100,
                "module_id": "SEISMIC_GEO",
                "source_title": "Nearby hazard",
                "source_ref": "TEST:ALERT",
                "start_at": "2026-08-01T12:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(target.legacy, "_alert_edges", [])
    monkeypatch.setattr(
        target.legacy,
        "_municipios_geojson",
        {"type": "FeatureCollection", "features": []},
    )
    monkeypatch.setattr(target, "read_events", lambda: [])
    monkeypatch.setattr(target, "_crosswalk_aliases", lambda: ({}, {}))

    payload = target._asset_switchboard("public")
    assert payload["assets"][0]["impact_status"] == "derived"
    assert payload["safety"]["confidence_only_confirmation_forbidden"] is True


def test_assets_api_preserves_array_contract_and_gates_operator_view(monkeypatch):
    monkeypatch.setattr(target.legacy, "_assets", _fixture_assets()[:1])
    monkeypatch.setattr(target.legacy, "_alerts", [])
    monkeypatch.setattr(target.legacy, "_alert_edges", [])
    monkeypatch.setattr(
        target.legacy,
        "_municipios_geojson",
        {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"NAME": "Arecibo"}}],
        },
    )
    monkeypatch.setattr(target, "read_events", lambda: [])
    monkeypatch.setattr(target, "_crosswalk_aliases", lambda: ({}, {}))
    monkeypatch.delenv("AGUAYLUZ_OPERATOR_ASSET_VIEW_ENABLED", raising=False)

    client = TestClient(target.app)
    legacy_response = client.get("/assets")
    assert legacy_response.status_code == 200
    assert isinstance(legacy_response.json(), list)

    impact_response = client.get("/assets?impact=true&view=public")
    assert impact_response.status_code == 200
    assert impact_response.json()["schema_version"] == "aguayluz.water-asset-impact/v0.1"

    operator_response = client.get("/assets?impact=true&view=operator")
    assert operator_response.status_code == 403
    assert operator_response.json()["detail"]["error"] == "operator_asset_view_disabled"
