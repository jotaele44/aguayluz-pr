"""Schema validation: golden valid + selected invalid cases per entity."""

from __future__ import annotations

import json

import pytest
from jsonschema import ValidationError

from aguayluz.models import (
    AguayluzBridgeSummary,
    Base44Export,
    ServiceEvent,
    UtilityAsset,
    validate_against_schema,
)

# ---------------- utility_asset ----------------

def test_utility_asset_valid(utility_asset_valid):
    validate_against_schema("utility_asset", utility_asset_valid)
    UtilityAsset(**utility_asset_valid)


def test_utility_asset_rejects_confidence_over_100(utility_asset_valid):
    bad = {**utility_asset_valid, "confidence": 101}
    with pytest.raises(ValidationError):
        validate_against_schema("utility_asset", bad)


def test_utility_asset_rejects_bad_asset_type(utility_asset_valid):
    bad = {**utility_asset_valid, "asset_type": "spaceship"}
    with pytest.raises(ValidationError):
        validate_against_schema("utility_asset", bad)


def test_utility_asset_rejects_out_of_pr_bbox(utility_asset_valid):
    # NYC coords — must be routed to review queue, schema rejects.
    bad = {**utility_asset_valid, "lat": 40.7128, "lon": -74.0060}
    with pytest.raises(ValidationError):
        validate_against_schema("utility_asset", bad)


def test_utility_asset_accepts_null_coords(utility_asset_valid):
    ok = {**utility_asset_valid, "lat": None, "lon": None}
    validate_against_schema("utility_asset", ok)


def test_utility_asset_rejects_extra_field(utility_asset_valid):
    bad = {**utility_asset_valid, "secret_extra": "leak"}
    with pytest.raises(ValidationError):
        validate_against_schema("utility_asset", bad)


def test_utility_asset_rejects_bad_attribute_coverage(utility_asset_valid):
    bad = {**utility_asset_valid, "attribute_coverage": "mostly"}
    with pytest.raises(ValidationError):
        validate_against_schema("utility_asset", bad)


# ---------------- service_event ----------------

def test_service_event_valid(service_event_valid):
    validate_against_schema("service_event", service_event_valid)
    ServiceEvent(**service_event_valid)


def test_service_event_rejects_bad_id_pattern(service_event_valid):
    bad = {**service_event_valid, "event_id": "EVT_BAD"}
    with pytest.raises(ValidationError):
        validate_against_schema("service_event", bad)


def test_service_event_rejects_bad_event_type(service_event_valid):
    bad = {**service_event_valid, "event_type": "fireworks"}
    with pytest.raises(ValidationError):
        validate_against_schema("service_event", bad)


# ---------------- bridge_summary ----------------

def test_bridge_summary_valid():
    s = {
        "module_id": "aguayluz-pr",
        "summary_id": "AYL_SUM_20260606_demo",
        "assets_total": 0,
        "events_total": 0,
        "municipalities_covered": [],
        "service_risk_summary": "no records yet",
        "infrastructure_dependencies": [],
        "linked_modules": ["spiderweb-pr", "moneysweep-pr"],
        "confidence": 0,
        "review_status": "needs_review",
    }
    validate_against_schema("aguayluz_bridge_summary", s)
    AguayluzBridgeSummary(**s)


def test_bridge_summary_rejects_wrong_module_id():
    s = {
        "module_id": "spiderweb-pr",
        "summary_id": "AYL_SUM_20260606_demo",
        "assets_total": 0,
        "events_total": 0,
        "municipalities_covered": [],
        "service_risk_summary": "",
        "infrastructure_dependencies": [],
        "linked_modules": [],
        "confidence": 0,
        "review_status": "needs_review",
    }
    with pytest.raises(ValidationError):
        validate_against_schema("aguayluz_bridge_summary", s)


# ---------------- base44_export ----------------

def test_base44_export_valid(base44_export_valid):
    validate_against_schema("base44_export", base44_export_valid)
    Base44Export(**base44_export_valid)


def test_base44_export_rejects_bad_status(base44_export_valid):
    bad = {**base44_export_valid, "status": "OK"}
    with pytest.raises(ValidationError):
        validate_against_schema("base44_export", bad)


def test_base44_export_rejects_bad_run_id(base44_export_valid):
    bad = {**base44_export_valid, "run_id": "yesterday"}
    with pytest.raises(ValidationError):
        validate_against_schema("base44_export", bad)


# ---------------- source_manifest / review_queue / integration_report (sanity) ----------------

def test_source_manifest_minimal_valid():
    data = {
        "module_id": "aguayluz-pr",
        "generated_at": "2026-06-06T12:00:00Z",
        "entries": [
            {
                "source_ref": "https://api.epa.gov/waters/oas30",
                "source_hash": None,
                "tier": "T1",
                "access_date": "2026-06-06",
                "citation": "EPA WATERS OAS v0.1.0",
                "notes": None,
            }
        ],
    }
    validate_against_schema("source_manifest", data)


def test_review_queue_minimal_valid():
    data = {
        "module_id": "aguayluz-pr",
        "generated_at": "2026-06-06T12:00:00Z",
        "items": [
            {
                "record_ref": "AYL_AST_X",
                "reason": "out of PR bbox",
                "severity": "warn",
                "evidence_tier": "T2",
                "confidence": 30,
                "notes": None,
            }
        ],
    }
    validate_against_schema("review_queue", data)


def test_integration_report_minimal_valid():
    data = {
        "module_id": "aguayluz-pr",
        "run_id": "20260606T120000Z_demo",
        "vector": "AGUAYLUZ_WATER_POWER_INFRASTRUCTURE_INTELLIGENCE",
        "generated_at": "2026-06-06T12:00:00Z",
        "coverage": {
            "expected": 1,
            "located": 1,
            "ingested": 1,
            "deduped": 1,
            "unresolved": 0,
            "gaps": [],
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
    assert len(schemas) == 12, f"expected 12 schemas, found {len(schemas)}"
    for p in schemas:
        s = json.loads(p.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(s)
