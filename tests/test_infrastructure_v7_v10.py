from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

_REPO = Path(__file__).resolve().parents[1]
_SCHEMAS = _REPO / "schemas"
_ONTOLOGY = _REPO / "ontology"


def _schema(name: str) -> dict:
    return json.loads((_SCHEMAS / name).read_text(encoding="utf-8"))


def _validate(name: str, record: dict) -> None:
    Draft202012Validator(_schema(name)).validate(record)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v7_v10_schemas_are_valid_json_schema() -> None:
    for name in (
        "infrastructure_geometry.schema.json",
        "infrastructure_relation.schema.json",
        "infrastructure_lifecycle_event.schema.json",
        "infrastructure_measurement.schema.json",
        "infrastructure_entity_role.schema.json",
        "infrastructure_legacy_projection.schema.json",
    ):
        Draft202012Validator.check_schema(_schema(name))


def test_geometry_manifestation_is_versioned_and_identity_neutral() -> None:
    record = {
        "geometry_id": "AYL_GEO_FIXTURE_001",
        "object_id": "AYL_FIX_ASSET_EBAS_001",
        "geometry_type": "Point",
        "geometry": {"type": "Point", "coordinates": [-66.0, 18.3]},
        "geometry_sha256": "0" * 64,
        "crs": "EPSG:4326",
        "z_state": "absent",
        "m_state": "absent",
        "valid_from": None,
        "valid_to": None,
        "derivation_method": "centroid_derived",
        "precision_m": None,
        "source_assertion_ids": ["FIXTURE_ONLY"],
        "identity_effect": "none",
        "spatial_state": "UNRESOLVED",
        "certification_state": "NONCANONICAL",
        "notes": "Synthetic regression only.",
    }
    _validate("infrastructure_geometry.schema.json", record)
    bad = {**record, "identity_effect": "establishes_identity"}
    with pytest.raises(ValidationError):
        _validate("infrastructure_geometry.schema.json", bad)


def test_network_relation_supports_temporal_typed_edges_without_identity_collapse() -> None:
    record = {
        "relation_id": "AYL_FIX_REL_POWERED_001",
        "from_object_id": "AYL_FIX_ASSET_EBAS_001",
        "relation_type": "powered_by",
        "to_object_id": "AYL_FIX_GENERATOR_001",
        "valid_from": None,
        "valid_to": None,
        "evidence_refs": ["FIXTURE_ONLY"],
        "source_assertion_ids": [],
        "identity_effect": "none",
        "confidence": None,
        "certification_state": "NONCANONICAL",
        "review_status": "fixture_only",
        "notes": None,
    }
    _validate("infrastructure_relation.schema.json", record)


def test_lifecycle_measurement_and_entity_roles_are_separate_sidecars() -> None:
    lifecycle = {
        "event_id": "AYL_LIFE_FIXTURE_001",
        "object_id": "AYL_FIX_ASSET_EBAS_001",
        "state": "ACTIVE",
        "valid_from": None,
        "valid_to": None,
        "source_assertion_ids": ["FIXTURE_ONLY"],
        "identity_effect": "none",
        "certification_state": "NONCANONICAL",
        "notes": None,
    }
    measurement = {
        "measurement_id": "AYL_MEAS_FIXTURE_001",
        "object_id": "AYL_FIX_ASSET_EBAS_001",
        "measurement_type": "firm_pumping_capacity",
        "value": 1.0,
        "unit": "MGD",
        "measurement_basis": "fixture",
        "effective_at": None,
        "source_assertion_ids": ["FIXTURE_ONLY"],
        "identity_effect": "none",
        "certification_state": "NONCANONICAL",
        "notes": None,
    }
    owner = {
        "role_id": "AYL_ROLE_FIXTURE_OWNER_001",
        "object_id": "AYL_FIX_ASSET_EBAS_001",
        "entity_ref": "AYL_FIX_ENTITY_OWNER",
        "role": "OWNER",
        "valid_from": None,
        "valid_to": None,
        "source_assertion_ids": ["FIXTURE_ONLY"],
        "identity_effect": "none",
        "certification_state": "NONCANONICAL",
        "notes": None,
    }
    operator = {
        **owner,
        "role_id": "AYL_ROLE_FIXTURE_OPERATOR_001",
        "entity_ref": "AYL_FIX_ENTITY_OPERATOR",
        "role": "OPERATOR",
    }

    _validate("infrastructure_lifecycle_event.schema.json", lifecycle)
    _validate("infrastructure_measurement.schema.json", measurement)
    _validate("infrastructure_entity_role.schema.json", owner)
    _validate("infrastructure_entity_role.schema.json", operator)
    assert owner["entity_ref"] != operator["entity_ref"]


def test_legacy_projection_is_read_only_fail_closed_and_schema_compatible_when_ready() -> None:
    module = runpy.run_path(str(_ONTOLOGY / "tools" / "project_legacy_compat.py"))
    project_object = module["project_object"]
    registry = json.loads((_ONTOLOGY / "infrastructure_terms.v0.1.json").read_text(encoding="utf-8"))
    rules = json.loads((_ONTOLOGY / "legacy_projection_rules.v0.1.json").read_text(encoding="utf-8"))
    fixture = json.loads(
        (_REPO / "tests" / "fixtures" / "ebas_vertical_slice.json").read_text(encoding="utf-8")
    )
    site, asset, _component = fixture["objects"]

    legacy_path = _REPO / "data" / "utility_assets.jsonl"
    before = _sha256(legacy_path)

    blocked = project_object(asset, registry, rules)
    _validate("infrastructure_legacy_projection.schema.json", blocked)
    assert blocked["projection_state"] == "BLOCKED_MISSING_CONTEXT"
    assert blocked["legacy_record"] is None

    context = {
        "operator": "FIXTURE_ONLY",
        "municipality": "Trujillo Alto",
        "lat": 18.3,
        "lon": -66.0,
        "geometry_type": "point",
        "status": "unknown",
        "source_ref": "FIXTURE_ONLY",
        "source_hash": None,
        "evidence_tier": "T4",
        "confidence": 0,
        "review_status": "needs_review",
    }
    ready = project_object(asset, registry, rules, context)
    after = _sha256(legacy_path)

    _validate("infrastructure_legacy_projection.schema.json", ready)
    assert ready["projection_state"] == "READY"
    assert ready["canonical_term_id"] == "AYL_TERM_SANITARY_SEWER_PUMP_STATION"
    assert ready["rules_version"] == rules["schema_version"]
    assert ready["legacy_record"]["asset_type"] == "wastewater"
    assert ready["legacy_record"]["asset_subtype"] == "pump_station"
    assert ready["compatibility_only"] is True
    assert ready["identity_effect"] == "none"
    _validate("utility_asset.schema.json", ready["legacy_record"])
    assert before == after

    with pytest.raises(ValueError, match="canonically untyped"):
        project_object(site, registry, rules, context)
