from __future__ import annotations

import server.backend.app as target


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
    monkeypatch.setattr(target.legacy, "_municipios_geojson", {"type": "FeatureCollection", "features": []})
    monkeypatch.setattr(target, "read_events", lambda: [])
    monkeypatch.setattr(target, "_crosswalk_aliases", lambda: ({}, {}))

    payload = target._asset_switchboard("public")
    assert payload["assets"][0]["impact_status"] == "derived"
    assert payload["safety"]["confidence_only_confirmation_forbidden"] is True
