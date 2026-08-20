from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from aguayluz.models import validate_against_schema

REPO = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO / "tools" / "build_real_data_partial_export.py"

_spec = importlib.util.spec_from_file_location("build_real_data_partial_export", TOOL_PATH)
assert _spec and _spec.loader
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)


def _args(out: Path) -> argparse.Namespace:
    return argparse.Namespace(
        assets="data/utility_assets.jsonl",
        events="data/service_events.jsonl",
        dependencies="data/alert_dependency_edges.jsonl",
        recovery_projects="data/recovery_projects.jsonl",
        source_registry="registry/utility_source_registry.v1.json",
        taxonomy="config/continuity_risk_taxonomy.v1.json",
        out=str(out),
        generated_at="2026-08-17T01:15:00Z",
        asset_limit=12,
        event_limit=12,
        project_limit=12,
        edge_limit=12,
    )


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_new_schema_contracts_accept_bounded_examples() -> None:
    outage = {
        "event_id": "AYL_EVT_20260817_demo",
        "event_type": "outage",
        "affected_area": "San Juan",
        "source_ref": "https://example.invalid/source-record-id",
        "evidence_tier": "T2",
        "confidence": 60,
        "review_status": "needs_review",
    }
    recovery = {
        "project_id": "AYL_PRJ_DEMO_001",
        "project_name": "Demonstration hardening project",
        "project_type": "grid_hardening",
        "status": "planned",
        "source_ref": "https://example.invalid/project-record-id",
        "evidence_tier": "T1",
        "confidence": 80,
        "review_status": "needs_review",
    }
    validate_against_schema("outage_event", outage)
    validate_against_schema("recovery_project", recovery)


def test_proxy_continuity_schema_forbids_identity_promotion() -> None:
    candidate = {
        "edge_id": "CR-EDGE-WP-DEMO",
        "from_id": "PWR_DEMO",
        "to_id": "WTR_DEMO",
        "risk_type": "water_asset_power_dependency_candidate",
        "relationship_status": "candidate",
        "identity_binding": "proxy",
        "source_ref": "data/alert_dependency_edges.jsonl#EDGE-WP-DEMO",
        "confidence": 44,
        "review_status": "needs_review",
        "evidence_required": True,
    }
    validate_against_schema("continuity_risk_edge", candidate)
    promoted = {
        **candidate,
        "relationship_status": "verified",
        "identity_binding": "authoritative",
        "review_status": "accepted",
        "evidence_required": False,
    }
    with pytest.raises(ValidationError):
        validate_against_schema("continuity_risk_edge", promoted)


def test_recurring_source_registry_has_unique_water_and_power_contracts() -> None:
    registry = json.loads((REPO / "registry/utility_source_registry.v1.json").read_text("utf-8"))
    validate_against_schema("recurring_source_registry", registry)
    ids = [row["source_id"] for row in registry["sources"]]
    assert len(ids) == len(set(ids))
    assert {row["domain"] for row in registry["sources"]} >= {"water", "power"}

    luma = next(row for row in registry["sources"] if row["source_id"] == "luma_miluma_outages")
    assert luma["access_state"] == "permission_constrained"
    assert luma["enabled_by_default"] is False

    waters = next(row for row in registry["sources"] if row["source_id"] == "epa_waters_nhdplus")
    assert waters["access_state"] == "api_key_required"
    assert waters["coverage_state"] == "partial"


def test_continuity_taxonomy_preserves_proxy_only_classes() -> None:
    taxonomy = json.loads((REPO / "config/continuity_risk_taxonomy.v1.json").read_text("utf-8"))
    rows = {row["risk_type"]: row for row in taxonomy["classes"]}
    power_water = rows["water_asset_power_dependency_candidate"]
    fuel = rows["fuel_sensitive_candidate"]
    assert power_water["identity_semantics"] == "PROXY_ONLY"
    assert fuel["identity_semantics"] == "PROXY_ONLY"
    assert power_water["evidence_required"] is True
    assert fuel["evidence_required"] is True
    assert set(power_water["allowed_status"]) <= {"candidate", "provisional"}
    assert set(fuel["allowed_status"]) <= {"candidate", "provisional"}


def test_repository_real_data_partial_export_is_deterministic_and_whole_row(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    manifest_a = _builder.build(_args(out_a))
    manifest_b = _builder.build(_args(out_b))

    assert manifest_a == manifest_b
    assert manifest_a["data_status"] == "PRODUCTION_REAL_DATA_PARTIAL"
    assert manifest_a["coverage"]["complete"] is False
    assert manifest_a["coverage"]["utility_assets_selected"] > 0
    assert manifest_a["coverage"]["outage_events_selected"] > 0
    assert manifest_a["coverage"]["continuity_risk_edges_selected"] > 0
    assert manifest_a["coverage"]["recovery_projects_selected"] == 0
    assert manifest_a["caveats"]["vpu21_hydro_enrichment"]["status"] == "PROVISIONAL_PARTIAL"
    assert manifest_a["caveats"]["vpu21_hydro_enrichment"]["no_extrapolation"] is True

    for name in (
        "utility_assets.jsonl",
        "outage_events.jsonl",
        "recovery_projects.jsonl",
        "continuity_risk_edges.jsonl",
        "manifest.json",
    ):
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()

    source_assets = _jsonl(REPO / "data/utility_assets.jsonl")
    source_events = _jsonl(REPO / "data/service_events.jsonl")
    exported_assets = _jsonl(out_a / "utility_assets.jsonl")
    exported_events = _jsonl(out_a / "outage_events.jsonl")
    assert all(row in source_assets for row in exported_assets)
    assert all(row in source_events for row in exported_events)
    assert (out_a / "recovery_projects.jsonl").read_bytes() == b""

    edges = _jsonl(out_a / "continuity_risk_edges.jsonl")
    assert any(row["risk_type"] == "water_asset_power_dependency_candidate" for row in edges)
    for row in edges:
        if row["risk_type"] in {
            "water_asset_power_dependency_candidate",
            "fuel_sensitive_candidate",
        }:
            assert row["relationship_status"] in {"candidate", "provisional"}
            assert row["identity_binding"] == "proxy"
            assert row["evidence_required"] is True
            assert row["review_status"] in {"needs_review", "blocked"}

    validate_against_schema("real_data_partial_manifest", manifest_a)
