import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from federation_export import build_streams  # noqa: E402

ASSETS = [{
    "asset_id": "A1", "asset_name": "PRASA Ponce Plant", "asset_type": "water",
    "asset_subtype": "treatment", "operator": "PRASA", "municipality": "Ponce",
    "source_ref": "prasa-registry", "source_hash": "h1", "confidence": 80,
    "evidence_tier": "T2", "review_status": "approved", "status": "active",
    "geometry_type": "point", "comid": 12345,
}]
EVENTS = [{
    "event_id": "E1", "event_type": "outage", "affected_area": "Ponce",
    "source_ref": "luma-report", "confidence": 70, "evidence_tier": "T3",
    "review_status": "approved", "linked_asset_ids": ["A1"],
}]


def test_stream_shapes():
    s = build_streams(ASSETS, EVENTS, "2026-01-01T00:00:00Z")
    types = {e["entity_type"] for e in s["entities"]}
    assert types == {"utility_asset", "utility_operator", "municipality", "service_event"}
    assert all(e["entity_id"].startswith("ent_") for e in s["entities"])
    assert all(srow["source_id"].startswith("src_") for srow in s["sources"])
    rels = {r["relationship_type"] for r in s["relationships"]}
    assert {"operated_by", "located_in", "affected_by"} <= rels
    assert all(r["relationship_id"].startswith("rel_") for r in s["relationships"])


def test_confidence_scaled_and_external_ids():
    s = build_streams(ASSETS, EVENTS, "t")
    asset = next(e for e in s["entities"] if e["entity_type"] == "utility_asset")
    assert asset["confidence"] == 0.8  # 80/100
    assert asset["external_ids"] == {"comid": "12345"}


def test_deterministic_ids():
    a = build_streams(ASSETS, EVENTS, "t")
    b = build_streams(ASSETS, EVENTS, "t")
    assert [e["entity_id"] for e in a["entities"]] == [e["entity_id"] for e in b["entities"]]


def test_asset_carries_location_when_coords_present():
    # Z2: a utility_asset with real coords gets a canonical `location`; entities
    # without point coords (operator/municipality/event) must not carry one.
    assets = [{**ASSETS[0], "lat": 18.0108, "lon": -66.6141}]
    s = build_streams(assets, EVENTS, "t")
    asset = next(e for e in s["entities"] if e["entity_type"] == "utility_asset")
    assert asset["location"] == {"lat": 18.0108, "lon": -66.6141, "municipality": "Ponce"}
    others = [e for e in s["entities"] if e["entity_type"] != "utility_asset"]
    assert all("location" not in e for e in others)


def test_asset_without_coords_has_no_location():
    s = build_streams(ASSETS, EVENTS, "t")  # fixture asset has no lat/lon
    asset = next(e for e in s["entities"] if e["entity_type"] == "utility_asset")
    assert "location" not in asset


def test_asset_carries_rich_attributes():
    # Rich operator-facing fields are carried through the canonical export so the
    # Hub water page renders municipality/status/operator instead of blank cells.
    s = build_streams(ASSETS, EVENTS, "t")
    asset = next(e for e in s["entities"] if e["entity_type"] == "utility_asset")
    attrs = asset["attributes"]
    assert attrs["municipality"] == "Ponce"
    assert attrs["operator"] == "PRASA"
    assert attrs["owner_agency"] == "PRASA"
    assert attrs["status"] == "active"
    assert attrs["review_status"] == "approved"
    # 'treatment' subtype is power-drawing -> flagged for the Continuity Risks surface.
    assert attrs["sensitivity"] == "power_dependent"


def test_energized_by_relationship_from_dep_edges():
    assets = [
        {**ASSETS[0], "asset_id": "PMP1", "asset_subtype": "pumping_station",
         "lat": 18.2, "lon": -66.2},
        {"asset_id": "PWR1", "asset_name": "Substation", "asset_type": "power",
         "asset_subtype": "substation", "source_ref": "eia", "confidence": 95,
         "lat": 18.21, "lon": -66.21},
    ]
    dep_edges = [{
        "edge_id": "EDGE-WP-PMP1", "from_node_type": "power_node", "from_node_id": "PWR1",
        "to_node_type": "hydro_asset", "to_node_id": "PMP1", "dependency_type": "energizes",
        "confidence": 55, "evidence_required": True,
    }]
    s = build_streams(assets, [], "t", dep_edges=dep_edges)
    energized = [r for r in s["relationships"] if r["relationship_type"] == "energized_by"]
    assert len(energized) == 1
    from federation_export import _fid  # noqa: PLC0415
    assert energized[0]["source_entity_id"] == _fid("ent", "asset", "PMP1")
    assert energized[0]["target_entity_id"] == _fid("ent", "asset", "PWR1")


def test_outdoor_conditions_become_entities_located_in_their_municipio():
    from test_federation_evidence_state import _outdoor_row

    streams = build_streams([], [], "2026-10-18T16:00:00Z",
                            outdoor=[_outdoor_row(), _outdoor_row("72113", "Ponce"), {"geoid": None}])
    outdoor = {e["attributes"]["municipality"]: e for e in streams["entities"]
               if e["entity_type"] == "outdoor_condition"}
    assert set(outdoor) == {"San Juan", "Ponce"}  # a row without a GEOID is skipped
    sj = outdoor["San Juan"]
    assert sj["external_ids"] == {"census_geoid": "72127", "aguayluz_condition_id": "AYL_OUTDOOR_72127"}
    assert sj["attributes"]["level"] == sj["attributes"]["status"] == "CAUTION"
    # components travel whole, so the hub sees why a value is missing, not a blank
    assert sj["attributes"]["components"]["air_quality"]["state"] == "NOT_CONFIGURED"
    assert sj["location"] == {"lat": 18.39, "lon": -66.06, "municipality": "San Juan"}
    located = [r for r in streams["relationships"]
               if r["source_entity_id"] == sj["entity_id"] and r["relationship_type"] == "located_in"]
    assert len(located) == 1
    target = next(e for e in streams["entities"] if e["entity_id"] == located[0]["target_entity_id"])
    assert target["entity_type"] == "municipality" and target["name"] == "San Juan"
