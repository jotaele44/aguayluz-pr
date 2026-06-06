"""Tests for `aguayluz.waters.mapping`.

Drives the layer with the M2 fixture so PR/VPU-21 partial-coverage flagging
is exercised end-to-end through Pydantic validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aguayluz.confidence import score as confidence_score
from aguayluz.models import ServiceEvent, UtilityAsset
from aguayluz.waters.mapping import (
    ReviewQueueItem,
    point_to_utility_asset,
    service_event_from_owld,
)

FIXTURES = Path(__file__).parent / "fixtures" / "waters"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------- point_to_utility_asset ----------------


def test_pr_pointindexing_maps_with_partial_coverage():
    resp = _load("pointindexing_lago_la_plata.json")
    asset = point_to_utility_asset(
        resp,
        asset_id="AYL_AST_LAGO_LA_PLATA_INTAKE",
        asset_name="Lago La Plata raw-water intake",
        asset_type="water",
        asset_subtype="intake",
        municipality="Toa Alta",
        operator="PRASA",
        snap_lat=18.388,
        snap_lon=-66.232,
    )
    assert isinstance(asset, UtilityAsset)
    assert asset.comid == 21000100
    assert asset.reachcode == "21010002000001"
    assert asset.measure == 0.0
    assert asset.vpuid == "21"
    assert asset.attribute_coverage == "partial"
    assert asset.evidence_tier == "T1"
    expected_conf = confidence_score(
        tier="T1", source_count=1, has_coords=True, attribute_coverage="partial"
    )
    assert asset.confidence == expected_conf
    assert asset.source_ref.startswith("https://api.epa.gov/waters/v1/pointindexing")
    assert asset.source_hash is not None and len(asset.source_hash) == 64  # sha256 hex


def test_non_pr_vpu_marks_full_coverage():
    """If the snap returns a non-VPU-21 region (e.g. mainland), coverage is full."""
    resp = _load("pointindexing_lago_la_plata.json")
    # Mutate the fixture in-memory: pretend the snap returned a mainland region.
    resp["output"]["ary_flowlines"][0]["nhdplus_region"] = "02"
    asset = point_to_utility_asset(
        resp,
        asset_id="AYL_AST_TEST_MAINLAND",
        asset_name="Test mainland asset",
        asset_type="water",
        asset_subtype="intake",
        municipality="Toa Alta",
        snap_lat=18.388,
        snap_lon=-66.232,
    )
    assert isinstance(asset, UtilityAsset)
    assert asset.attribute_coverage == "full"
    assert asset.vpuid == "02"


def test_out_of_pr_bbox_returns_review_queue_item():
    resp = _load("pointindexing_lago_la_plata.json")
    result = point_to_utility_asset(
        resp,
        asset_id="AYL_AST_NYC",
        asset_name="NYC test",
        asset_type="water",
        asset_subtype="intake",
        municipality="N/A",
        snap_lat=40.7128,
        snap_lon=-74.0060,
    )
    assert isinstance(result, ReviewQueueItem)
    assert result["record_ref"] == "AYL_AST_NYC"
    assert "outside PR bbox" in result["reason"]
    assert result["severity"] == "warn"


def test_no_flowlines_returns_review_queue_item():
    empty = {"output": {"ary_flowlines": []}}
    result = point_to_utility_asset(
        empty,
        asset_id="AYL_AST_NOSNAP",
        asset_name="No-snap test",
        asset_type="water",
        asset_subtype="intake",
        municipality="Toa Alta",
        snap_lat=18.388,
        snap_lon=-66.232,
    )
    assert isinstance(result, ReviewQueueItem)
    assert "no flowlines" in result["reason"].lower()


def test_missing_coords_lowers_confidence():
    resp = _load("pointindexing_lago_la_plata.json")
    with_coords = point_to_utility_asset(
        resp,
        asset_id="AYL_AST_A",
        asset_name="A",
        asset_type="water",
        asset_subtype="intake",
        municipality="Toa Alta",
        snap_lat=18.388,
        snap_lon=-66.232,
    )
    without_coords = point_to_utility_asset(
        resp,
        asset_id="AYL_AST_B",
        asset_name="B",
        asset_type="water",
        asset_subtype="intake",
        municipality="Toa Alta",
    )
    assert isinstance(with_coords, UtilityAsset) and isinstance(without_coords, UtilityAsset)
    assert without_coords.confidence < with_coords.confidence


def test_resulting_asset_passes_jsonschema(utility_asset_valid):
    # Sanity: a mapped asset round-trips through model_dump → schema validation
    # (re-validated by the model_validator on construction; this is a guard
    # against silent drift between mapping and schema).
    resp = _load("pointindexing_lago_la_plata.json")
    asset = point_to_utility_asset(
        resp,
        asset_id="AYL_AST_X",
        asset_name="X",
        asset_type="water",
        asset_subtype="intake",
        municipality="Toa Alta",
        snap_lat=18.388,
        snap_lon=-66.232,
    )
    assert isinstance(asset, UtilityAsset)
    dumped = asset.model_dump()
    # All required fields from the schema must be present.
    for required in (
        "asset_id", "asset_name", "asset_type", "asset_subtype", "municipality",
        "geometry_type", "status", "source_ref", "evidence_tier", "confidence",
        "review_status",
    ):
        assert required in dumped


# ---------------- service_event_from_owld ----------------


def test_owld_to_service_event():
    owld_resp = {
        "output": {
            "waterbodies": [
                {"gnis_name": "Río de La Plata", "comid": 21000101},
                {"gnis_name": "Bahía de San Juan", "comid": 21000102},
            ]
        }
    }
    event = service_event_from_owld(
        owld_resp,
        event_id="AYL_EVT_20260606_release",
        affected_area="Toa Alta downstream cascade",
        snap_lat=18.388,
        snap_lon=-66.232,
        linked_asset_ids=["AYL_AST_LAGO_LA_PLATA_INTAKE"],
    )
    assert isinstance(event, ServiceEvent)
    assert event.evidence_tier == "T2"
    assert event.reported_customers_or_users == 2
    assert event.linked_asset_ids == ["AYL_AST_LAGO_LA_PLATA_INTAKE"]
    assert event.source_ref.startswith("https://api.epa.gov/waters/v1/owldlocator")


def test_owld_out_of_pr_bbox_routes_to_review_queue():
    result = service_event_from_owld(
        {"output": {"waterbodies": []}},
        event_id="AYL_EVT_20260606_offshore",
        affected_area="Atlantic Ocean",
        snap_lat=35.0,
        snap_lon=-50.0,
    )
    assert isinstance(result, ReviewQueueItem)
    assert "outside PR bbox" in result["reason"]


def test_owld_rejects_bad_event_type():
    """Pydantic Literal must reject typos in `event_type`."""
    with pytest.raises(ValidationError):
        service_event_from_owld(
            {"output": {"waterbodies": []}},
            event_id="AYL_EVT_20260606_bad",
            affected_area="Toa Alta",
            event_type="fireworks",  # not in the Literal
            snap_lat=18.388,
            snap_lon=-66.232,
        )
