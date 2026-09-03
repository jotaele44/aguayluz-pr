import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from federation_export import _fid, build_streams  # noqa: E402

NOW = "2026-06-15T00:00:00Z"

ASSETS = [
    {"asset_id": "HIFLD_PP_61014", "asset_name": "Santa Isabel Wind", "asset_type": "power",
     "asset_subtype": "generation (WND)", "municipality": "Santa Isabel", "geometry_type": "point",
     "status": "active", "source_ref": "HIFLD power plants", "evidence_tier": "T1",
     "confidence": 80, "review_status": "accepted", "lat": 17.9876, "lon": -66.4303},
    {"asset_id": "EIA_PLANT_61014", "asset_name": "Pattern Santa Isabel LLC", "asset_type": "power",
     "asset_subtype": "generation (Wind)", "municipality": "unknown", "geometry_type": "unknown",
     "status": "active", "source_ref": "EIA Form-923", "evidence_tier": "T1",
     "confidence": 65, "review_status": "accepted"},
    {"asset_id": "OSMP_-17091033", "asset_name": "Santa Isabel Wind Farm", "asset_type": "power",
     "asset_subtype": "generation (wind)", "municipality": "Santa Isabel", "geometry_type": "point",
     "status": "active", "source_ref": "OSM power_plant", "evidence_tier": "T3",
     "confidence": 45, "review_status": "needs_review", "lat": 17.9878, "lon": -66.4301},
]
CROSSWALK = [{
    "cluster_id": "AYLX_abc123",
    "canonical_asset_id": "HIFLD_PP_61014",
    "asset_class": "generation",
    "match_method": "plant_code+proximity",
    "max_distance_m": 25.0,
    "member_asset_ids": ["EIA_PLANT_61014", "HIFLD_PP_61014", "OSMP_-17091033"],
    "members": [],
}]


def _dup_edges(rels):
    return [r for r in rels if r["relationship_type"] == "duplicate_of"]


def test_duplicate_of_edges_point_members_to_canonical():
    streams = build_streams(ASSETS, [], NOW, {}, CROSSWALK)
    dup = _dup_edges(streams["relationships"])
    canon_ent = _fid("ent", "asset", "HIFLD_PP_61014")
    assert len(dup) == 2  # two non-canonical members
    assert all(r["target_entity_id"] == canon_ent for r in dup)
    srcs = {r["source_entity_id"] for r in dup}
    assert srcs == {_fid("ent", "asset", "EIA_PLANT_61014"),
                    _fid("ent", "asset", "OSMP_-17091033")}


def test_canonical_has_no_outgoing_duplicate_of():
    streams = build_streams(ASSETS, [], NOW, {}, CROSSWALK)
    canon_ent = _fid("ent", "asset", "HIFLD_PP_61014")
    assert all(r["source_entity_id"] != canon_ent for r in _dup_edges(streams["relationships"]))
    # all three asset entities are still present (additive, non-destructive)
    asset_ents = [e for e in streams["entities"] if e["entity_type"] == "utility_asset"]
    assert len(asset_ents) == 3


def test_no_crosswalk_means_no_duplicate_edges():
    streams = build_streams(ASSETS, [], NOW, {}, [])
    assert _dup_edges(streams["relationships"]) == []


def test_canonical_set_is_recoverable_by_filtering():
    streams = build_streams(ASSETS, [], NOW, {}, CROSSWALK)
    dup_src = {r["source_entity_id"] for r in _dup_edges(streams["relationships"])}
    asset_ents = {e["entity_id"] for e in streams["entities"] if e["entity_type"] == "utility_asset"}
    canonical_set = asset_ents - dup_src  # drop nodes with an outgoing duplicate_of
    assert canonical_set == {_fid("ent", "asset", "HIFLD_PP_61014")}
