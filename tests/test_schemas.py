"""Schema validation: golden valid + selected invalid cases per entity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from aguayluz.models import (
    AguayluzBridgeSummary,
    HubExport,
    NaturalFeature,
    ServiceEvent,
    UtilityAsset,
    validate_against_schema,
)

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def schemas_dir() -> Path:
    return _REPO / "schemas"


# ---------------- utility_asset ----------------

def test_utility_asset_validates():
    data = {
        "asset_id": "USGS_50059000",
        "asset_type": "surface_water_station",
        "name": "Rio Grande de Loiza at Caguas, PR",
        "operator": "USGS",
        "status": "active",
        "municipality": "Caguas",
        "lat": 18.2408,
        "lon": -66.0124,
        "source_ref": "USGS:50059000",
        "source_hash": "abc123",
        "evidence_tier": "T1",
        "confidence": 1.0,
        "review_status": "accepted",
    }
    validate_against_schema("utility_asset", data)


def test_utility_asset_rejects_bad_evidence_tier():
    data = {
        "asset_id": "X",
        "asset_type": "other",
        "name": "X",
        "status": "unknown",
        "source_ref": "src",
        "source_hash": "abc",
        "evidence_tier": "T9",
        "confidence": 0.5,
        "review_status": "needs_review",
    }
    with pytest.raises(ValidationError):
        validate_against_schema("utility_asset", data)


# ---------------- service_event ----------------

def test_service_event_validates():
    data = {
        "event_id": "AYL_EVT_test",
        "event_type": "outage",
        "affected_area": "Test area",
        "status_text": "active",
        "source_ref": "source:test",
        "source_hash": "abc123",
        "evidence_tier": "T1",
        "confidence": 1.0,
        "review_status": "accepted",
    }
    validate_against_schema("service_event", data)


def test_service_event_rejects_unknown_type():
    data = {
        "event_id": "AYL_EVT_test",
        "event_type": "not_a_real_type",
        "affected_area": "Test area",
        "status_text": "active",
        "source_ref": "source:test",
        "source_hash": "abc123",
        "evidence_tier": "T1",
        "confidence": 1.0,
        "review_status": "accepted",
    }
    with pytest.raises(ValidationError):
        validate_against_schema("service_event", data)


# ---------------- natural_feature ----------------

def test_natural_feature_validates():
    data = {
        "feature_id": "NHD_FCODE_46006",
        "feature_type": "stream_river",
        "name": "Rio Example",
        "source_ref": "NHD:test",
        "source_hash": "abc123",
        "evidence_tier": "T1",
        "confidence": 1.0,
        "review_status": "accepted",
    }
    validate_against_schema("natural_feature", data)


# ---------------- bridge summary ----------------

def test_bridge_summary_validates():
    data = {
        "schema_version": "aguayluz_bridge_summary_v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "assets": {"total": 1},
        "events": {"total": 2},
        "sources": {"total": 3},
    }
    validate_against_schema("aguayluz_bridge_summary", data)


# ---------------- hub export ----------------

def test_hub_export_validates():
    data = {
        "schema_version": "aguayluz_hub_export_v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "producer": "aguayluz-pr",
        "records": [],
    }
    validate_against_schema("hub_export", data)


# ---------------- model constructors ----------------

def test_utility_asset_model():
    model = UtilityAsset(
        asset_id="X",
        asset_type="other",
        name="Test",
        operator=None,
        status="unknown",
        municipality=None,
        lat=None,
        lon=None,
        source_ref="test",
        source_hash="hash",
        evidence_tier="T1",
        confidence=1.0,
        review_status="accepted",
    )
    assert model.asset_id == "X"


def test_service_event_model():
    model = ServiceEvent(
        event_id="E",
        event_type="unknown",
        affected_area="Test",
        municipality=None,
        zone=None,
        status_text="unknown",
        start_time=None,
        end_time=None,
        source_ref="test",
        source_hash="hash",
        evidence_tier="T1",
        confidence=1.0,
        review_status="accepted",
        linked_asset_ids=[],
    )
    assert model.event_id == "E"


def test_natural_feature_model():
    model = NaturalFeature(
        feature_id="N",
        feature_type="other",
        name="Test",
        municipality=None,
        lat=None,
        lon=None,
        source_ref="test",
        source_hash="hash",
        evidence_tier="T1",
        confidence=1.0,
        review_status="accepted",
    )
    assert model.feature_id == "N"


def test_bridge_summary_model():
    model = AguayluzBridgeSummary(
        schema_version="aguayluz_bridge_summary_v1",
        generated_at="2026-01-01T00:00:00Z",
        assets={"total": 1},
        events={"total": 1},
        sources={"total": 1},
    )
    assert model.schema_version == "aguayluz_bridge_summary_v1"


def test_hub_export_model():
    model = HubExport(
        schema_version="aguayluz_hub_export_v1",
        generated_at="2026-01-01T00:00:00Z",
        producer="aguayluz-pr",
        records=[],
    )
    assert model.producer == "aguayluz-pr"


# ---------------- integration_report ----------------

def test_integration_report_validates():
    data = {
        "schema_version": "integration_report_v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "repo": "jotaele44/aguayluz-pr",
        "summary": {
            "checks_total": 1,
            "checks_passed": 1,
            "checks_failed": 0,
            "coverage_pct": 100.0,
        },
        "gates": [
            {"id": "G01_SCHEMA", "status": "PASS", "details": None},
        ],
    }
    validate_against_schema("integration_report", data)


# ---------------- schema files themselves are valid JSON Schema ----------------

def test_every_schema_loads_and_validates_itself(schemas_dir):
    from jsonschema import Draft202012Validator
    schemas = list(schemas_dir.glob("*.schema.json"))
    assert len(schemas) == 25, f"expected 25 schemas, found {len(schemas)}"
    for p in schemas:
        s = json.loads(p.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(s)


# ---------------- pr_natural_feature (hydro slice) ----------------

def _first_natural_feature() -> dict:
    data = json.loads((_REPO / "data" / "geo" / "pr_natural_features.json").read_text("utf-8"))
    return data["features"][0]


def test_pr_natural_feature_schema_validates_first_feature():
    feature = _first_natural_feature()
    properties = feature["properties"]
    data = {
        "feature_id": properties["feature_id"],
        "feature_type": properties["feature_type"],
        "name": properties["name"],
        "municipality": properties.get("municipality"),
        "lat": properties.get("lat"),
        "lon": properties.get("lon"),
        "source_ref": properties["source_ref"],
        "source_hash": properties["source_hash"],
        "evidence_tier": properties["evidence_tier"],
        "confidence": properties["confidence"],
        "review_status": properties["review_status"],
    }
    validate_against_schema("pr_natural_feature", data)
