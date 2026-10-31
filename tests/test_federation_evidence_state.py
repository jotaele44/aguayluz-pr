"""Additive evidence_state declarations (thehub-pr FEDERATION_EPISTEMIC_STATE_CONTRACT_V1).

Positive: every exported row declares a schema-valid evidence_state; curated
records are CURATED, promoter-generated alerts and derived edges are COMPUTED,
and published monitoring-location coordinates are OBSERVED_POINT.
Negative: a municipio centroid, an approximate alert point or a point standing
in for a polygon/line is never an OBSERVED_POINT; a proximity-linked power feed
is never a plain relationship; no row declares an observation state.
"""

import hashlib
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from federation_export import (  # noqa: E402
    _GENERATED_ALERT_MARKERS,
    EVIDENCE_STATE_CONTRACT,
    build_streams,
)

VENDORED = REPO / "schemas" / "federation_epistemic_state.v1.schema.json"
# sha256 of thehub-pr schemas/federation/epistemic_state.v1.schema.json (CANDIDATE).
HUB_CANDIDATE_SHA256 = "c31794807d47f00e9ffeb394cf9ddd5d093613dabcf22d4fd81d4a416bade088"
NOW = "2026-01-01T00:00:00Z"
GEO = {"PONCE": {"name": "Ponce", "lat": 18.0111, "lon": -66.6141}}


def _asset(asset_id, **extra):
    row = {
        "asset_id": asset_id, "asset_name": asset_id, "asset_type": "water",
        "asset_subtype": "monitoring_location", "municipality": "Ponce",
        "source_ref": f"ref-{asset_id}", "confidence": 80, "geometry_type": "point",
        "lat": 18.01, "lon": -66.61,
    }
    row.update(extra)
    return row


def _alert(alert_id, **extra):
    row = {
        "alert_id": alert_id, "module_id": "SEISMIC_GEO", "event_type": "hazard",
        "status": "active", "severity": 3, "gap_status": "none", "confidence": 70,
        "source_ref": "https://earthquake.usgs.gov/event/1", "start_at": "2026-01-01T10:00:00Z",
        "municipalities": ["Ponce"], "latitude": 17.9, "longitude": -66.6, "coord_confidence": "exact",
    }
    row.update(extra)
    return row


def _validator():
    schema = json.loads(VENDORED.read_text())
    wrapper = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/producer_declaration"}
    return jsonschema.Draft202012Validator(wrapper)


def _entity(streams, name):
    return next(r for r in streams["entities"] if r["name"] == name)


def _full_streams():
    assets = [
        _asset("USGS_50100450"),
        _asset("RSV_CARRAIZO", geometry_type="polygon"),
        _asset("LOCAL_CANAL", geometry_type="line"),
        _asset("PWR00039", asset_type="power"),
        _asset("LOCAL_TANK", geometry_type="unknown"),
        _asset("EIA_PLANT_1", geometry_type="unknown", lat=None, lon=None),
        _asset("PMP_1", asset_subtype="pumping_station"),
        _asset("HIFLD_PP_1", asset_type="power"),
    ]
    events = [{"event_id": "E1", "event_type": "outage", "affected_area": "Ponce", "municipality": "Ponce",
               "source_ref": "luma", "confidence": 60, "linked_asset_ids": ["PMP_1"]}]
    crosswalk = [{"canonical_asset_id": "HIFLD_PP_1", "member_asset_ids": ["HIFLD_PP_1", "EIA_PLANT_1"],
                  "match_method": "plant_code"}]
    dep_edges = [{"edge_id": "EDGE-WP-PMP_1", "from_node_id": "PWR00039", "to_node_id": "PMP_1",
                  "dependency_type": "energizes", "confidence": 44, "evidence_required": True}]
    alerts = [
        _alert("ALERT_seismic_1"),
        _alert("ALERT_weather_1", module_id="WEATHER_HAZARD", coord_confidence="approximate"),
        _alert("ALERT-HAND-1", module_id="HYDRO_OPS", coord_confidence="unknown", latitude=None, longitude=None),
    ]
    return build_streams(assets, events, NOW, geo=GEO, crosswalk=crosswalk, alerts=alerts, dep_edges=dep_edges)


def test_vendored_contract_is_byte_identical_to_the_hub_candidate():
    assert hashlib.sha256(VENDORED.read_bytes()).hexdigest() == HUB_CANDIDATE_SHA256
    assert json.loads(VENDORED.read_text())["$id"] == "urn:prii:federation:epistemic_state:v1"


def test_generated_alert_markers_match_the_promoter_registry():
    from aguayluz.alert_promotion import GENERATED_MARKERS  # noqa: PLC0415

    assert tuple(_GENERATED_ALERT_MARKERS) == tuple(GENERATED_MARKERS)


def test_every_row_declares_a_valid_evidence_state():
    validator = _validator()
    streams = _full_streams()
    assert {s for s, rows in streams.items() if rows} == {"sources", "entities", "relationships", "alerts"}
    for stream, rows in streams.items():
        for row in rows:
            declaration = row["evidence_state"]
            assert declaration["contract"] == EVIDENCE_STATE_CONTRACT
            assert declaration["epistemic_class"] in ("CURATED", "COMPUTED")
            expected_stage = "COMPUTATION" if declaration["epistemic_class"] == "COMPUTED" else "CANONICAL"
            assert declaration["data_stage"] == expected_stage
            assert list(validator.iter_errors(declaration)) == [], (stream, declaration)


def test_published_site_coordinates_are_observed_points():
    declaration = _entity(_full_streams(), "USGS_50100450")["evidence_state"]
    assert declaration["geometry_precision"] == "OBSERVED_POINT"
    assert declaration["coordinate_method"] == "AUTHORITATIVE"


@pytest.mark.parametrize("name, gtype", [("RSV_CARRAIZO", "polygon"), ("LOCAL_CANAL", "line")])
def test_point_for_a_polygon_or_line_is_representative(name, gtype):
    declaration = _entity(_full_streams(), name)["evidence_state"]
    assert declaration["geometry_precision"] == "REPRESENTATIVE_POINT"
    assert declaration["coordinate_method"] == f"POINT_FOR_{gtype.upper()}"


@pytest.mark.parametrize("name", ["PWR00039", "LOCAL_TANK", "EIA_PLANT_1", "PMP_1"])
def test_undocumented_or_absent_coordinates_declare_no_geometry(name):
    declaration = _entity(_full_streams(), name)["evidence_state"]
    assert "geometry_precision" not in declaration
    assert "coordinate_method" not in declaration


def test_service_event_centroid_is_never_an_observed_point():
    event = _entity(_full_streams(), "outage @ Ponce")
    assert event["location"]["lat"] == GEO["PONCE"]["lat"]
    assert event["evidence_state"]["geometry_precision"] == "REPRESENTATIVE_POINT"
    assert event["evidence_state"]["coordinate_method"] == "DERIVED_CENTROID"


def test_service_event_without_a_centroid_declares_no_geometry():
    events = [{"event_id": "E2", "event_type": "outage", "affected_area": "Nowhere", "municipality": "Nowhere",
               "source_ref": "luma", "confidence": 60}]
    event = _entity(build_streams([], events, NOW, geo=GEO), "outage @ Nowhere")
    assert "location" not in event
    assert "geometry_precision" not in event["evidence_state"]


def test_proximity_power_feed_is_computed_with_a_weak_match_basis():
    streams = _full_streams()
    edge = next(r for r in streams["relationships"] if r["relationship_type"] == "energized_by")
    assert edge["match_basis"] == "spatial_proximity"
    assert edge["evidence_state"]["epistemic_class"] == "COMPUTED"
    assert all("match_basis" not in r for r in streams["relationships"] if r["relationship_type"] != "energized_by")


def test_plant_code_duplicate_is_computed():
    edge = next(r for r in _full_streams()["relationships"] if r["relationship_type"] == "duplicate_of")
    assert edge["evidence_state"]["epistemic_class"] == "COMPUTED"
    assert "plant_code" in edge["evidence_state"]["basis_note"]


def test_curated_relationships_stay_curated():
    streams = _full_streams()
    for r in streams["relationships"]:
        if r["relationship_type"] in ("operated_by", "located_in", "affected_by"):
            assert r["evidence_state"]["epistemic_class"] == "CURATED"


def _alert_rows():
    return {r["attributes"]["aguayluz_alert_id"]: r for r in _full_streams()["alerts"]}


def test_generated_alert_is_computed_and_exact_point_is_observed():
    declaration = _alert_rows()["ALERT_seismic_1"]["evidence_state"]
    assert declaration["epistemic_class"] == "COMPUTED"
    assert declaration["geometry_precision"] == "OBSERVED_POINT"
    assert declaration["temporal_precision"] == "EXACT_TIMESTAMP"


def test_approximate_alert_point_is_never_observed():
    declaration = _alert_rows()["ALERT_weather_1"]["evidence_state"]
    assert declaration["geometry_precision"] == "REPRESENTATIVE_POINT"
    assert declaration["coordinate_method"] == "APPROXIMATE"


def test_hand_authored_alert_is_curated_without_geometry():
    row = _alert_rows()["ALERT-HAND-1"]
    assert row["evidence_state"]["epistemic_class"] == "CURATED"
    assert "location" not in row
    assert "geometry_precision" not in row["evidence_state"]


def test_exact_confidence_without_coordinates_declares_no_geometry():
    streams = build_streams([], [], NOW, alerts=[_alert("ALERT_seismic_2", latitude=None, longitude=None)])
    assert "geometry_precision" not in streams["alerts"][0]["evidence_state"]


@pytest.mark.parametrize(
    "published_at, expected",
    [("2026-01-01T10:00:00Z", "EXACT_TIMESTAMP"), ("2026-01-01T10:00:00-04:00", "EXACT_TIMESTAMP"),
     ("2026-01-01", "DATE_ONLY"), ("2026-13-45", None), ("sometime in 2026", None), ("2026-13-45T99:00", None)],
)
def test_alert_temporal_precision_is_never_invented(published_at, expected):
    streams = build_streams([], [], NOW, alerts=[_alert("ALERT-HAND-2", published_at=published_at)])
    assert streams["alerts"][0]["evidence_state"].get("temporal_precision") == expected


def test_no_row_declares_an_observation_state():
    for rows in _full_streams().values():
        for row in rows:
            assert "observation_state" not in row["evidence_state"]
            assert "observation_absence_basis" not in row["evidence_state"]
