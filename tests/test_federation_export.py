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
