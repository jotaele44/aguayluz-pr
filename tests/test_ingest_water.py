import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_water import _centroid, build_water_assets, merge  # noqa: E402


def test_centroid_polygon_is_inside_ring():
    geom = {"type": "Polygon", "coordinates": [
        [[-66.0, 18.0], [-66.0, 18.2], [-65.8, 18.2], [-65.8, 18.0], [-66.0, 18.0]]
    ]}
    lat, lon = _centroid(geom)
    assert 18.0 <= lat <= 18.2
    assert -66.0 <= lon <= -65.8


def test_centroid_point():
    assert _centroid({"type": "Point", "coordinates": [-66.1, 18.4]}) == (18.4, -66.1)


def test_centroid_none_for_empty_or_garbage():
    assert _centroid({"type": "Polygon", "coordinates": []}) is None
    assert _centroid({"type": "GeometryCollection"}) is None


def test_merge_preserves_nonwater_and_replaces_water():
    existing = [
        {"asset_id": "PWR_1", "asset_type": "power"},
        {"asset_id": "WTR_old", "asset_type": "water"},
    ]
    water = [{"asset_id": "WTR_1", "asset_type": "water"}]
    out = merge(existing, water)
    ids = {r["asset_id"] for r in out}
    assert ids == {"PWR_1", "WTR_1"}  # power kept, stale water dropped, new water added


def test_build_water_assets_maps_layer(tmp_path):
    (tmp_path / "wastewater_plant.geojson").write_text(json.dumps({
        "features": [{
            "type": "Feature",
            "properties": {"id": 42, "name": "PRASA WWTP", "operator": "PRASA"},
            "geometry": {"type": "Polygon", "coordinates": [
                [[-66.0, 18.0], [-66.0, 18.1], [-65.9, 18.1], [-65.9, 18.0], [-66.0, 18.0]]
            ]},
        }]
    }))
    rows = build_water_assets(tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["asset_id"] == "WWT_42"
    assert r["asset_type"] == "wastewater" and r["asset_subtype"] == "wastewater_treatment"
    assert r["asset_name"] == "PRASA WWTP" and r["operator"] == "PRASA"
    assert r["review_status"] == "needs_review" and r["evidence_tier"] == "T3"
    assert "lat" in r and "lon" in r  # centroid carried for the Z2 entity location


def test_build_water_assets_unnamed_gets_label(tmp_path):
    (tmp_path / "water_reservoir.geojson").write_text(json.dumps({
        "features": [{
            "type": "Feature", "properties": {"id": 7},
            "geometry": {"type": "Polygon", "coordinates": [
                [[-66.0, 18.0], [-66.0, 18.1], [-65.9, 18.0], [-66.0, 18.0]]
            ]},
        }]
    }))
    rows = build_water_assets(tmp_path)
    assert rows[0]["asset_name"] == "Reservoir 7"
    assert rows[0]["asset_type"] == "water" and rows[0]["asset_subtype"] == "reservoir"
