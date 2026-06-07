"""Tests for `aguayluz.foia.generate_targets` and the roster script."""

from __future__ import annotations

import json
from pathlib import Path

from aguayluz.foia import (
    _classify_review_item,
    _target_id,
    generate_targets,
    load_agencies,
)
from aguayluz.models import validate_against_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENCIES = load_agencies(REPO_ROOT / "config" / "foia_agencies.yaml")


# ---------- classifier ----------


def test_review_missing_coords_water_goes_to_prasa():
    agency, missing = _classify_review_item({
        "record_ref": "AYL_AST_FRS_PRASA_X",
        "reason": "asset missing snap coordinates",
    })
    assert agency == "PRASA"
    assert missing == ["latitude", "longitude"]


def test_review_missing_coords_event_goes_to_fema():
    agency, missing = _classify_review_item({
        "record_ref": "AYL_EVT_20170920_fema_4339_pw1",
        "reason": "asset missing snap coordinates",
    })
    assert agency == "FEMA"
    assert "coordinates" in missing


def test_review_missing_coords_luma_record_goes_to_luma():
    agency, missing = _classify_review_item({
        "record_ref": "AYL_AST_HIFLD_PR_LUMA_SUB_8101",
        "reason": "asset missing snap coordinates",
    })
    assert agency == "LUMA"


def test_review_out_of_bbox_goes_to_epa():
    agency, missing = _classify_review_item({
        "record_ref": "AYL_AST_NYC",
        "reason": "input snap coords (40.7, -74.0) outside PR bbox",
    })
    assert agency == "EPA"
    assert missing == ["geographic_correction"]


def test_review_no_flowlines_goes_to_epa():
    agency, missing = _classify_review_item({
        "record_ref": "AYL_AST_X",
        "reason": "WATERS pointindexing returned no flowlines",
    })
    assert agency == "EPA"
    assert missing == ["nhdplus_v2_1_reach"]


def test_review_validation_failed_goes_to_fema():
    agency, missing = _classify_review_item({
        "record_ref": "badid",
        "reason": "event validation failed: ValidationError",
    })
    assert agency == "FEMA"


# ---------- target id determinism ----------


def test_target_id_is_stable():
    a = _target_id(
        agency="PRASA", missing_fields=frozenset(["latitude", "longitude"]),
        record_ref="AYL_AST_X",
    )
    b = _target_id(
        agency="PRASA", missing_fields=frozenset(["longitude", "latitude"]),
        record_ref="AYL_AST_X",
    )
    assert a == b
    assert a.startswith("AYL_FOIA_TGT_")


def test_target_id_changes_with_inputs():
    a = _target_id(
        agency="PRASA", missing_fields=frozenset(["latitude"]),
        record_ref="AYL_AST_X",
    )
    b = _target_id(
        agency="FEMA", missing_fields=frozenset(["latitude"]),
        record_ref="AYL_AST_X",
    )
    assert a != b


# ---------- generate_targets ----------


def test_review_item_produces_target():
    targets = generate_targets(
        review_items=[{
            "record_ref": "AYL_AST_FRS_X",
            "reason": "asset missing snap coordinates",
            "severity": "warn",
        }],
        reconciliation_findings=[],
        partial_assets=[],
        agencies=AGENCIES,
    )
    assert len(targets) == 1
    assert targets[0]["agency"] == "PRASA"
    assert "latitude" in targets[0]["missing_fields"]


def test_missing_coverage_finding_produces_fema_target():
    targets = generate_targets(
        review_items=[],
        reconciliation_findings=[{
            "finding_id": "AYL_FIND_x",
            "kind": "missing_coverage",
            "event_id": "AYL_EVT_20170920_fema_4339_pw1",
            "municipality": "Yauco",
            "details": "FEMA project affects Yauco, no asset record",
            "severity": "warn",
            "confidence": 70,
        }],
        partial_assets=[],
        agencies=AGENCIES,
    )
    assert len(targets) == 1
    assert targets[0]["agency"] == "FEMA"
    assert targets[0]["supporting_evidence"]["municipality"] == "Yauco"


def test_partial_asset_produces_epa_target():
    targets = generate_targets(
        review_items=[],
        reconciliation_findings=[],
        partial_assets=[{
            "asset_id": "AYL_AST_FRS_VPU21_X",
            "attribute_coverage": "partial",
            "municipality": "Bayamon",
        }],
        agencies=AGENCIES,
    )
    assert len(targets) == 1
    assert targets[0]["agency"] == "EPA"
    assert "VPUAttributeExtensionNLCD_VPU21" in targets[0]["missing_fields"]


def test_dedup_by_agency_and_field_set():
    """Two assets in the same agency missing the same fields → 1 target."""
    targets = generate_targets(
        review_items=[
            {"record_ref": "AYL_AST_FRS_A", "reason": "asset missing snap coordinates"},
            {"record_ref": "AYL_AST_FRS_B", "reason": "asset missing snap coordinates"},
        ],
        reconciliation_findings=[],
        partial_assets=[],
        agencies=AGENCIES,
    )
    assert len(targets) == 1


def test_non_missing_coverage_findings_skipped():
    targets = generate_targets(
        review_items=[],
        reconciliation_findings=[
            {"finding_id": "F1", "kind": "stale_asset"},
            {"finding_id": "F2", "kind": "consistent"},
        ],
        partial_assets=[],
        agencies=AGENCIES,
    )
    assert targets == []


def test_agency_metadata_threaded_through():
    targets = generate_targets(
        review_items=[{
            "record_ref": "AYL_AST_FRS_X",
            "reason": "asset missing snap coordinates",
        }],
        reconciliation_findings=[],
        partial_assets=[],
        agencies=AGENCIES,
    )
    assert targets[0]["agency_contact_email"] == "acceso.records@acueductospr.com"
    assert targets[0]["sla_business_days"] == 10


# ---------- schema round-trip ----------


def test_roster_validates_against_schema():
    targets = generate_targets(
        review_items=[{
            "record_ref": "AYL_AST_FRS_X",
            "reason": "asset missing snap coordinates",
            "severity": "warn",
        }],
        reconciliation_findings=[{
            "finding_id": "F1",
            "kind": "missing_coverage",
            "event_id": "AYL_EVT_20170920_fema_4339_pw1",
            "municipality": "Yauco",
            "details": "test",
            "severity": "warn",
            "confidence": 70,
        }],
        partial_assets=[{
            "asset_id": "AYL_AST_FRS_VPU21",
            "attribute_coverage": "partial",
            "municipality": "Bayamon",
        }],
        agencies=AGENCIES,
    )
    roster = {
        "module_id": "aguayluz-pr",
        "roster_id": "AYL_FOIA_20260606_test",
        "generated_at": "2026-06-06T12:00:00Z",
        "targets": targets,
    }
    validate_against_schema("foia_roster", roster)


def test_empty_inputs_produce_empty_roster():
    targets = generate_targets(
        review_items=[],
        reconciliation_findings=[],
        partial_assets=[],
        agencies=AGENCIES,
    )
    assert targets == []


# ---------- script integration ----------


def test_script_writes_roster_file(tmp_path):
    """End-to-end: seeded outputs/ produces outputs/foia_roster.json."""
    import subprocess
    import sys as _sys

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "review_queue.json").write_text(json.dumps({
        "module_id": "aguayluz-pr",
        "generated_at": "2026-06-06T12:00:00Z",
        "items": [{
            "record_ref": "AYL_AST_FRS_X",
            "reason": "asset missing snap coordinates",
            "severity": "warn",
        }],
    }), encoding="utf-8")
    (outputs / "reconciliation_report.json").write_text(json.dumps({
        "module_id": "aguayluz-pr",
        "run_id": "20260606T120000Z_test",
        "vector": "TEST",
        "generated_at": "2026-06-06T12:00:00Z",
        "findings": [],
        "summary": {"consistent_count": 0, "status_mismatches": 0,
                    "missing_coverage": 0, "stale_assets": 0},
    }), encoding="utf-8")
    (outputs / "utility_assets.json").write_text(json.dumps([]), encoding="utf-8")

    proc = subprocess.run(
        [
            _sys.executable, str(REPO_ROOT / "scripts" / "generate_foia_roster.py"),
            "--outputs-dir", str(outputs),
        ],
        capture_output=True, text=True, check=False, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert (outputs / "foia_roster.json").exists()
    roster = json.loads((outputs / "foia_roster.json").read_text(encoding="utf-8"))
    assert roster["module_id"] == "aguayluz-pr"
    assert len(roster["targets"]) == 1
    assert roster["targets"][0]["agency"] == "PRASA"
