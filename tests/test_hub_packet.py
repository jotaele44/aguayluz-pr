"""Tests for `aguayluz.hub_packet.build_hub_packet` / `verify_packet_signature`."""

from __future__ import annotations

import json
from pathlib import Path

from aguayluz.hub_packet import (
    PACKET_VERSION,
    build_hub_packet,
    verify_packet_signature,
)
from aguayluz.models import validate_against_schema


def _seed_outputs(outputs_dir, *, with_handoffs: bool = True):  # type: ignore[no-untyped-def]
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "base44_export.json").write_text(json.dumps({
        "module_id": "aguayluz-pr",
        "run_id": "20260606T120000Z_test",
        "vector": "TEST",
        "status": "PASS",
        "coverage_pct": 100.0,
        "records_total": 1,
        "records_review": 0,
        "records_blocked": 0,
        "confidence_avg": 70.0,
        "source_manifest_path": "outputs/source_manifest.json",
        "integration_report_path": "outputs/integration_report.json",
        "sanitized_summary": "test",
        "top_findings": [],
        "contradictions": [],
        "gaps": [],
        "next_actions": [],
        "federation_handoffs": [],
    }), encoding="utf-8")
    (outputs_dir / "utility_assets.json").write_text(
        json.dumps([{"asset_id": "A1", "asset_name": "X"}]),
        encoding="utf-8",
    )
    (outputs_dir / "service_events.json").write_text("[]", encoding="utf-8")
    (outputs_dir / "reconciliation_report.json").write_text(json.dumps({
        "module_id": "aguayluz-pr",
        "run_id": "20260606T120000Z_test",
        "vector": "TEST",
        "generated_at": "2026-06-06T12:00:00Z",
        "findings": [],
        "summary": {
            "consistent_count": 2,
            "status_mismatches": 0,
            "missing_coverage": 1,
            "stale_assets": 1,
        },
    }), encoding="utf-8")
    if with_handoffs:
        (outputs_dir / "handoff_thehub-pr.json").write_text(json.dumps({
            "module_id": "aguayluz-pr",
            "target_module_id": "thehub-pr",
            "run_id": "20260606T120000Z_test",
            "vector": "TEST",
            "generated_at": "2026-06-06T12:00:00Z",
            "confidence_floor": 50,
            "join_keys": [],
            "payload": {},
        }), encoding="utf-8")


# ---------- shape ----------


def test_packet_required_fields(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    packet = build_hub_packet(
        outputs_dir=outputs,
        run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    for field in (
        "packet_version", "module_id", "run_id", "generated_at",
        "signature_sha256", "envelope", "handoffs", "entities",
    ):
        assert field in packet, f"missing field: {field}"
    assert packet["packet_version"] == PACKET_VERSION
    assert packet["module_id"] == "aguayluz-pr"


def test_packet_validates_against_schema(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    packet = build_hub_packet(
        outputs_dir=outputs,
        run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    validate_against_schema("hub_packet", packet)


def test_packet_inlines_entities(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    packet = build_hub_packet(
        outputs_dir=outputs,
        run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    assert packet["entities"]["utility_assets"] == [{"asset_id": "A1", "asset_name": "X"}]
    assert packet["entities"]["service_events"] == []
    assert packet["entities"]["bridge_summary"] is None
    assert packet["entities"]["reconciliation_summary"] == {
        "consistent_count": 2,
        "status_mismatches": 0,
        "missing_coverage": 1,
        "stale_assets": 1,
    }


def test_packet_inlines_handoffs(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    packet = build_hub_packet(
        outputs_dir=outputs,
        run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    assert len(packet["handoffs"]) == 1
    assert packet["handoffs"][0]["target_module_id"] == "thehub-pr"


def test_packet_without_handoffs(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs, with_handoffs=False)
    packet = build_hub_packet(
        outputs_dir=outputs,
        run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    assert packet["handoffs"] == []


# ---------- signature ----------


def test_signature_is_deterministic(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    p1 = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    p2 = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_other",
        generated_at="2026-06-07T13:00:00Z",
    )
    # run_id + generated_at are envelope-fields (already in inputs); the signature
    # is over envelope+handoffs+entities only, so it stays stable across re-runs
    # with identical underlying data.
    assert p1["signature_sha256"] == p2["signature_sha256"]


def test_signature_changes_when_assets_change(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    p1 = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    # Mutate the assets file.
    (outputs / "utility_assets.json").write_text(
        json.dumps([
            {"asset_id": "A1", "asset_name": "X"},
            {"asset_id": "A2", "asset_name": "Y"},
        ]),
        encoding="utf-8",
    )
    p2 = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    assert p1["signature_sha256"] != p2["signature_sha256"]


def test_verify_passes_on_intact_packet(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    packet = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    assert verify_packet_signature(packet) is True


def test_verify_detects_tamper(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    packet = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    # Mutate an inlined entity without recomputing the signature.
    packet["entities"]["utility_assets"].append({"asset_id": "EVIL", "asset_name": "INJECTED"})
    assert verify_packet_signature(packet) is False


def test_verify_detects_envelope_swap(tmp_path):
    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    packet = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    packet["envelope"]["status"] = "FAIL"
    assert verify_packet_signature(packet) is False


def test_verify_handles_missing_signature():
    assert verify_packet_signature({"envelope": {}, "handoffs": [], "entities": {}}) is False


# ---------- empty/missing outputs ----------


def test_packet_with_missing_inputs_still_builds(tmp_path):
    outputs = tmp_path / "outputs_empty"
    outputs.mkdir()
    packet = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    assert packet["envelope"] == {}
    assert packet["entities"]["utility_assets"] == []
    assert packet["entities"]["reconciliation_summary"] == {
        "consistent_count": 0, "status_mismatches": 0,
        "missing_coverage": 0, "stale_assets": 0,
    }


def test_reconciliation_summary_handles_missing_summary_fields(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "reconciliation_report.json").write_text(
        json.dumps({"findings": [], "summary": {"missing_coverage": 3}}),
        encoding="utf-8",
    )
    packet = build_hub_packet(
        outputs_dir=outputs, run_id="20260606T120000Z_test",
        generated_at="2026-06-06T12:00:00Z",
    )
    # Only the field set in input is non-zero; others default to 0.
    assert packet["entities"]["reconciliation_summary"]["missing_coverage"] == 3
    assert packet["entities"]["reconciliation_summary"]["consistent_count"] == 0


# ---------- script integration ----------


def test_script_writes_signature_sidecar(tmp_path):
    """The script writes both hub_packet.json and hub_packet.sha256."""
    import subprocess
    import sys as _sys

    outputs = tmp_path / "outputs"
    _seed_outputs(outputs)
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [
            _sys.executable, str(repo_root / "scripts" / "export_hub_packet.py"),
            "--outputs-dir", str(outputs),
        ],
        capture_output=True, text=True, check=False, cwd=repo_root,
    )
    assert proc.returncode == 0, proc.stderr
    assert (outputs / "hub_packet.json").exists()
    assert (outputs / "hub_packet.sha256").exists()

    # Sidecar format: `<hash>  hub_packet.json`
    sidecar = (outputs / "hub_packet.sha256").read_text(encoding="utf-8").strip()
    packet = json.loads((outputs / "hub_packet.json").read_text(encoding="utf-8"))
    assert sidecar.startswith(packet["signature_sha256"])
