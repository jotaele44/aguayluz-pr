"""Tests for the water<->power dependency crosswalk builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

# The builder lives under scripts/ (not an installed package); load it by path.
_SPEC = importlib.util.spec_from_file_location(
    "build_water_power_crosswalk",
    Path(__file__).resolve().parent.parent / "scripts" / "build_water_power_crosswalk.py",
)
xwalk = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(xwalk)


def _asset(aid, atype, sub, lat, lon):
    return {"asset_id": aid, "asset_name": aid, "asset_type": atype,
            "asset_subtype": sub, "lat": lat, "lon": lon}


def test_haversine_known_distance():
    # ~1 degree of latitude ≈ 111 km.
    d = xwalk.haversine_km(18.0, -66.0, 19.0, -66.0)
    assert 110 < d < 112


def test_pump_links_to_nearest_power_within_range():
    assets = [
        _asset("PMP1", "water", "pumping_station", 18.20, -66.20),
        _asset("PWR_NEAR", "power", "substation", 18.205, -66.205),   # ~0.7 km
        _asset("PWR_FAR", "power", "substation", 18.90, -67.10),      # far
    ]
    edges = xwalk.build_edges(assets)
    assert len(edges) == 1
    e = edges[0]
    assert e["from_node_id"] == "PWR_NEAR"
    assert e["to_node_id"] == "PMP1"
    assert e["dependency_type"] == "energizes"
    assert e["evidence_required"] is True
    assert e["confidence"] == xwalk._CONF_NEAR  # within NEAR_KM


def test_no_edge_when_beyond_far_threshold():
    assets = [
        _asset("WWT1", "wastewater", "wastewater_treatment", 18.0, -66.0),
        _asset("PWR", "power", "substation", 18.9, -67.5),  # > FAR_KM away
    ]
    assert xwalk.build_edges(assets) == []


def test_non_power_drawing_water_ignored():
    assets = [
        _asset("CANAL", "water", "irrigation_canal", 18.2, -66.2),
        _asset("PWR", "power", "substation", 18.2, -66.2),
    ]
    assert xwalk.build_edges(assets) == []


def test_confidence_fades_with_distance():
    near = xwalk._confidence_for(xwalk._NEAR_KM)
    mid = xwalk._confidence_for((xwalk._NEAR_KM + xwalk._FAR_KM) / 2)
    far = xwalk._confidence_for(xwalk._FAR_KM)
    assert near == xwalk._CONF_NEAR
    assert far == xwalk._CONF_FAR
    assert far < mid < near


def test_merge_drops_null_placeholder_and_prior_generated():
    existing = [
        {"edge_id": "EDGE-POWER-PUMP-SEED", "from_node_id": None, "to_node_id": None},
        {"edge_id": "EDGE-CARRAIZO-SERVICE-SEED", "from_node_id": "X", "to_node_id": "Y"},
        {"edge_id": "EDGE-WP-OLD", "from_node_id": "a", "to_node_id": "b"},
    ]
    generated = [{"edge_id": "EDGE-WP-PMP1", "from_node_id": "p", "to_node_id": "w"}]
    merged = xwalk.merge_edges(existing, generated)
    ids = {e["edge_id"] for e in merged}
    assert "EDGE-POWER-PUMP-SEED" not in ids   # null placeholder removed
    assert "EDGE-WP-OLD" not in ids            # stale generated replaced
    assert "EDGE-CARRAIZO-SERVICE-SEED" in ids  # unrelated seed kept
    assert "EDGE-WP-PMP1" in ids


def test_close_gap_marks_gap_003_closed():
    gaps = [{"gap_id": "GAP-003", "status": "open", "next_action": "x"},
            {"gap_id": "GAP-004", "status": "open", "next_action": "y"}]
    out = xwalk._close_gap(gaps, 42)
    g3 = next(g for g in out if g["gap_id"] == "GAP-003")
    assert g3["status"] == "closed"
    assert "42" in g3["next_action"]
    assert next(g for g in out if g["gap_id"] == "GAP-004")["status"] == "open"
