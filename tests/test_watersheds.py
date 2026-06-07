"""Tests for `aguayluz.analysis.watersheds.delineate_assets`."""

from __future__ import annotations

import json
from pathlib import Path

from aguayluz.analysis import delineate_assets
from aguayluz.confidence import score as confidence_score
from aguayluz.models import validate_against_schema

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "waters" / "drainagearea_v3.json"


def _drainagearea_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _asset(asset_id: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    return {
        "asset_id": asset_id,
        "asset_name": kw.get("name", asset_id),
        "asset_type": kw.get("asset_type", "water"),
        "asset_subtype": "intake",
        "municipality": kw.get("municipality", "Toa Alta"),
        "lat": kw.get("lat", 18.388),
        "lon": kw.get("lon", -66.232),
        "geometry_type": "point",
        "status": "active",
        "source_ref": "https://example.gov",
        "evidence_tier": "T1",
        "confidence": 70,
        "review_status": "accepted",
        "vpuid": kw.get("vpuid", "21"),
    }


# ---------- happy path ----------


def test_delineates_water_assets():
    records, review = delineate_assets(
        [_asset("AYL_AST_X")],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
    )
    assert len(records) == 1
    r = records[0]
    assert r["asset_id"] == "AYL_AST_X"
    assert r["nhdplus_id"] == 21000100
    assert r["area_sqkm"] == 142.6
    assert r["bounds_bbox"] == [-66.31, 18.30, -66.20, 18.40]
    assert r["attribute_coverage"] == "partial"  # VPU 21
    expected_conf = confidence_score(
        tier="T1", source_count=1, has_coords=True, attribute_coverage="partial"
    )
    assert r["confidence"] == expected_conf
    assert r["source_ref"].startswith("https://api.epa.gov/waters/v3/drainageareadelineation")
    assert review == []


def test_skips_non_water_assets():
    records, review = delineate_assets(
        [_asset("AYL_AST_POW", asset_type="power")],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
    )
    assert records == []
    assert review == []


def test_delineates_wastewater_assets():
    records, _ = delineate_assets(
        [_asset("AYL_AST_W", asset_type="wastewater")],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
    )
    assert len(records) == 1
    assert records[0]["asset_id"] == "AYL_AST_W"


# ---------- non-PR VPU ----------


def test_non_vpu21_records_full_coverage():
    records, _ = delineate_assets(
        [_asset("AYL_AST_MAIN", vpuid="02")],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
    )
    assert records[0]["attribute_coverage"] == "full"


# ---------- failure routing ----------


def test_missing_coords_routes_to_review():
    asset = _asset("AYL_AST_NULL")
    asset["lat"] = None
    asset["lon"] = None
    records, review = delineate_assets(
        [asset],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
    )
    assert records == []
    assert len(review) == 1
    assert "missing snap" in review[0]["reason"]


def test_snap_exception_routes_to_review():
    def boom(_lo: float, _la: float) -> dict:
        raise RuntimeError("network down")

    records, review = delineate_assets([_asset("AYL_AST_NET")], snap_fn=boom)
    assert records == []
    assert "RuntimeError" in review[0]["reason"]


def test_empty_drainage_response_routes_to_review():
    records, review = delineate_assets(
        [_asset("AYL_AST_NONE")],
        snap_fn=lambda _lo, _la: {"Result_Delineated_Area": {"features": []}},
    )
    assert records == []
    assert "no Result_Delineated_Area" in review[0]["reason"]


# ---------- sidecar geometry ----------


def test_geometry_dir_populates_sidecar_path():
    records, _ = delineate_assets(
        [_asset("AYL_AST_X")],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
        geometry_dir="geometry",
    )
    assert records[0]["geometry_sidecar"] == "geometry/watershed_AYL_AST_X.geojson"


def test_no_geometry_dir_yields_null_sidecar():
    records, _ = delineate_assets(
        [_asset("AYL_AST_X")],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
    )
    assert records[0]["geometry_sidecar"] is None


# ---------- schema round-trip ----------


def test_records_validate_against_schema():
    records, _ = delineate_assets(
        [_asset("AYL_AST_X"), _asset("AYL_AST_W", asset_type="wastewater")],
        snap_fn=lambda _lo, _la: _drainagearea_fixture(),
        geometry_dir="geometry",
    )
    validate_against_schema("watershed_delineation", records)


def test_empty_records_array_validates():
    # The schema is an array — an empty array is a legitimate "no watersheds" state.
    validate_against_schema("watershed_delineation", [])


# ---------- headwater extraction ----------


def test_headwater_comids_parse_from_string_list():
    response = {
        "Result_Delineated_Area": {
            "features": [
                {
                    "geometry": {"type": "Polygon", "coordinates": [[[-66.0, 18.0], [-65.9, 18.1]]]},
                    "properties": {
                        "NHDPlusID": 21000100,
                        "AreaSqKm": 50.0,
                        "Headwater_COMIDs": "21000150, 21000151, not_a_number",
                    },
                }
            ]
        }
    }
    records, _ = delineate_assets(
        [_asset("AYL_AST_X")],
        snap_fn=lambda _lo, _la: response,
    )
    assert records[0]["headwater_comids"] == [21000150, 21000151]


# ---------- bbox computation when absent ----------


def test_bbox_falls_back_to_polygon_coords():
    response = {
        "Result_Delineated_Area": {
            "features": [
                {
                    # No bbox key — must be derived from coordinates.
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-66.5, 18.1], [-66.0, 18.6], [-66.3, 18.3]]],
                    },
                    "properties": {"NHDPlusID": 1, "AreaSqKm": 10.0},
                }
            ]
        }
    }
    records, _ = delineate_assets(
        [_asset("AYL_AST_X")],
        snap_fn=lambda _lo, _la: response,
    )
    bbox = records[0]["bounds_bbox"]
    assert bbox == [-66.5, 18.1, -66.0, 18.6]
