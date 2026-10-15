"""Contract tests for the official USDM Puerto Rico footprint producer."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest_drought_usdm_footprint.py"
SPEC = importlib.util.spec_from_file_location("ingest_drought_usdm_footprint", MODULE_PATH)
assert SPEC and SPEC.loader
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)


def _polygon(minx: float, miny: float, maxx: float, maxy: float):
    return [[
        [minx, miny],
        [maxx, miny],
        [maxx, maxy],
        [minx, maxy],
        [minx, miny],
    ]]


def test_stats_preserve_cumulative_semantics():
    raw = (
        "MapDate,State,None,D0,D1,D2,D3,D4,ValidStart,ValidEnd\n"
        "20261006,Puerto Rico,39,61,43,24,5,0,2026-10-06,2026-10-13\n"
        "20261013,Puerto Rico,36,64,48,28,9,0,2026-10-13,2026-10-20\n"
    ).encode()
    rows = ingest.parse_stats(raw)
    assert [row["map_date"] for row in rows] == ["2026-10-06", "2026-10-13"]
    assert rows[-1]["D0"] == 64
    assert rows[-1]["D3"] == 9
    assert rows[-1]["semantics"] == "cumulative_percent_area_at_or_above_category"
    assert rows[-1]["D0"] + rows[-1]["D1"] + rows[-1]["D2"] + rows[-1]["D3"] == 149


def test_pr_component_selection_retains_source_coordinates_without_interpolation():
    source = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"DM": 3},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    _polygon(-100, 30, -99, 31),
                    _polygon(-67.2, 17.9, -66.0, 18.5),
                ],
            },
        }],
    }
    footprint, counts = ingest.extract_pr_footprint(json.dumps(source).encode())
    assert counts["D3"] == 1
    feature = footprint["features"][0]
    assert feature["properties"]["category"] == "D3"
    assert feature["properties"]["derived"] is False
    assert feature["geometry"]["coordinates"] == [_polygon(-67.2, 17.9, -66.0, 18.5)]


def test_crossing_component_fails_closed_instead_of_clipping():
    source = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"DM": "D2"},
            "geometry": {
                "type": "Polygon",
                "coordinates": _polygon(-70, 17.9, -66.0, 18.5),
            },
        }],
    }
    with pytest.raises(ValueError, match="crosses"):
        ingest.extract_pr_footprint(json.dumps(source).encode())


def test_document_binds_statistics_and_geometry_to_same_map_date():
    stats = (
        "MapDate,State,None,D0,D1,D2,D3,D4,ValidStart,ValidEnd\n"
        "20261013,Puerto Rico,36,64,48,28,9,0,2026-10-13,2026-10-20\n"
    ).encode()
    geo = json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"DM": 3},
            "geometry": {"type": "Polygon", "coordinates": _polygon(-67.2, 17.9, -66.0, 18.5)},
        }],
    }).encode()
    document = ingest.build_document(
        stats_raw=stats,
        stats_url="https://example.test/stats",
        geo_raw=geo,
        geo_url="https://droughtmonitor.unl.edu/Data/json/USDM_20261013.json",
        retrieved_at="2026-10-15T20:00:00Z",
    )
    assert document["map_date"] == "2026-10-13"
    assert document["statistics"]["D2"] == 28
    assert len(document["source_manifestations"]["geometry"]["sha256"]) == 64
    assert document["footprint"]["features"][0]["properties"]["category"] == "D3"


def test_refresh_plan_schedules_footprint_weekly_and_all_only():
    refresh_path = Path(__file__).resolve().parents[1] / "scripts" / "refresh.py"
    refresh_spec = importlib.util.spec_from_file_location("refresh_for_drought_test", refresh_path)
    assert refresh_spec and refresh_spec.loader
    refresh = importlib.util.module_from_spec(refresh_spec)
    refresh_spec.loader.exec_module(refresh)

    def scripts(plan):
        return {argv[0] for _label, argv, _optional in refresh.PLANS[plan]}

    target = "scripts/ingest_drought_usdm_footprint.py"
    assert target in scripts("weekly")
    assert target in scripts("all")
    assert target not in scripts("daily")
    assert target not in scripts("fast")
