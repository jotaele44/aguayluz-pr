"""Behavioral regressions for malformed exports and explicit validation gate states."""

from __future__ import annotations

import json

import pytest

from aguayluz import validation as gates


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "OUTPUTS_DIR", tmp_path)
    return tmp_path


def write(outputs, name, payload):
    (outputs / name).write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("payload", ["{", "[{}]", "null"])
def test_schema_gate_rejects_malformed_or_invalid_entity(outputs, payload):
    (outputs / "utility_assets.json").write_text(payload, encoding="utf-8")
    result = gates.gate_g01_schema()
    assert result.status == "FAIL"
    assert "utility_assets.json" in result.details


def test_schema_gate_counts_omitted_error_diagnostics(outputs):
    write(outputs, "utility_assets.json", [{} for _ in range(7)])
    result = gates.gate_g01_schema()
    assert result.status == "FAIL"
    assert "(+2 more)" in result.details


def test_schema_gate_validates_object_envelope_with_real_schema(outputs):
    write(outputs, "review_queue.json", {
        "module_id": "aguayluz-pr", "generated_at": "2026-09-08T00:00:00Z",
        "items": [{"record_ref": "asset:1", "reason": "unresolved source", "severity": "block"}],
    })
    assert gates.gate_g01_schema().status == "PASS"
    assert gates.gate_g04_review_queue().status == "PASS"


def test_source_manifest_required_when_entity_output_exists(outputs):
    write(outputs, "utility_assets.json", [])
    assert gates.gate_g02_source_manifest().status == "FAIL"


@pytest.mark.parametrize("payload", ["{", "{}", "[]"])
def test_source_manifest_rejects_invalid_envelope(outputs, payload):
    (outputs / "source_manifest.json").write_text(payload, encoding="utf-8")
    assert gates.gate_g02_source_manifest().status == "FAIL"


def test_manifest_empty_is_warning_and_valid_entry_is_structural_pass(outputs):
    manifest = {"module_id": "aguayluz-pr", "generated_at": "2026-09-08T00:00:00Z", "entries": []}
    write(outputs, "source_manifest.json", manifest)
    assert gates.gate_g02_source_manifest().status == "WARN"
    manifest["entries"] = [{"source_ref": "fixture:source", "tier": "T1", "access_date": "2026-09-08"}]
    write(outputs, "source_manifest.json", manifest)
    result = gates.gate_g02_source_manifest()
    assert result.status == "PASS"
    assert json.loads(result.details)["sources"] == 1


@pytest.mark.parametrize("filename", sorted(gates._ENTITY_ARRAY_FILES))
def test_manifest_requires_exact_reference_coverage(outputs, filename):
    ref = "fixture: Á  source"
    write(outputs, "source_manifest.json", {
        "module_id": "aguayluz-pr", "generated_at": "2026-09-08T00:00:00Z",
        "entries": [{"source_ref": ref, "tier": "T1", "access_date": "2026-09-08"}],
    })
    rows = [{"source_ref": ref}, {"source_ref": ref.strip().lower()},
            {"source_ref": "fixture:missing"}, None, {"source_ref": []}]
    write(outputs, filename, rows)
    result = gates.gate_g02_source_manifest()
    assert result.status == "FAIL"
    details = json.loads(result.details)
    assert (details["entities"], details["bound"], details["missing"], details["invalid"]) == (5, 1, 2, 2)
    assert details["identity_effect"] == "NONE"
    assert json.loads((outputs / filename).read_text()) == rows
    write(outputs, filename, [{"source_ref": ref}] * 3)
    result = gates.gate_g02_source_manifest()
    assert result.status == "PASS"
    assert json.loads(result.details)["bound"] == 3


def test_manifest_preserves_all_version_candidates(outputs):
    entries = [{"source_ref": "fixture:source", "tier": "T1", "access_date": "2026-09-08",
                "source_hash": digest} for digest in ("a" * 64, "b" * 64)]
    write(outputs, "source_manifest.json", {
        "module_id": "aguayluz-pr", "generated_at": "2026-09-08T00:00:00Z", "entries": entries,
    })
    write(outputs, "utility_assets.json", [{"source_ref": "fixture:source"}] * 2)
    result = gates.gate_g02_source_manifest()
    assert result.status == "WARN"
    details = json.loads(result.details)
    assert details["bound"] == details["multiple_candidates"] == 2
    assert [issue["manifest_indices"] for issue in details["issues"]] == [[0, 1], [0, 1]]


@pytest.mark.parametrize("payload", ["{", "null", "{}"])
def test_manifest_cannot_pass_unreadable_entity_collection(outputs, payload):
    write(outputs, "source_manifest.json", {
        "module_id": "aguayluz-pr", "generated_at": "2026-09-08T00:00:00Z", "entries": [],
    })
    (outputs / "utility_assets.json").write_text(payload)
    assert gates.gate_g02_source_manifest().status == "FAIL"


@pytest.mark.parametrize("filename", ["utility_assets.json", "service_events.json"])
@pytest.mark.parametrize("review_status", ["needs_review", "blocked"])
def test_review_queue_required_for_pending_records(outputs, filename, review_status):
    write(outputs, filename, [{"review_status": review_status}])
    assert gates.gate_g04_review_queue().status == "FAIL"


@pytest.mark.parametrize("filename", ["utility_assets.json", "service_events.json"])
def test_unparseable_pending_entities_do_not_pass_review_gate(outputs, filename):
    (outputs / filename).write_text("{", encoding="utf-8")
    assert gates.gate_g04_review_queue().status == "FAIL"


def test_invalid_review_queue_is_not_accepted_as_present(outputs):
    write(outputs, "review_queue.json", {"items": []})
    assert gates.gate_g04_review_queue().status == "FAIL"


def test_hub_export_rejects_secret_even_inside_valid_envelope(outputs):
    envelope = {
        "module_id": "aguayluz-pr", "run_id": "20260908T000000Z_fixture",
        "vector": "test", "status": "WARN", "coverage_pct": 0,
        "records_total": 0, "records_review": 0, "records_blocked": 0,
        "confidence_avg": 0, "source_manifest_path": "source_manifest.json",
        "integration_report_path": "integration_report.json",
        "sanitized_summary": "No promoted records", "top_findings": [],
        "contradictions": [], "gaps": [], "next_actions": [],
    }
    write(outputs, "hub_export.json", envelope)
    assert gates.gate_g06_hub_export().status == "PASS"
    # Construct a synthetic AWS-shaped canary without embedding a scanner hit.
    envelope["sanitized_summary"] = "AK" + "IA" + "A" * 16
    write(outputs, "hub_export.json", envelope)
    assert gates.gate_g06_hub_export().status == "FAIL"


@pytest.mark.parametrize("gate,filename", [
    (gates.gate_g05_coverage_ledger, "integration_report.json"),
    (gates.gate_g06_hub_export, "hub_export.json"),
])
def test_invalid_required_envelopes_fail_closed(outputs, gate, filename):
    write(outputs, filename, {})
    assert gate().status == "FAIL"


def test_confidence_gate_detects_low_confidence_accepted_record(outputs):
    write(outputs, "utility_assets.json", [{"review_status": "accepted", "confidence": 49}])
    assert gates.gate_g03_confidence().status == "WARN"
    write(outputs, "utility_assets.json", [{"review_status": "accepted", "confidence": 50}])
    assert gates.gate_g03_confidence().status == "PASS"


def test_gate_disable_and_nonblocking_override_remain_explicit(monkeypatch):
    calls = []

    def failing_gate():
        calls.append("ran")
        return gates.GateResult("fixture", "FAIL", "missing evidence")

    monkeypatch.setattr(gates, "GATE_FUNCS", {"fixture": failing_gate})
    disabled = gates.run_gates({"fixture": {"enabled": False}})
    assert disabled.by_id("fixture").status == "SKIP"
    assert calls == []
    warning = gates.run_gates({"fixture": {"blocking": False}})
    assert warning.by_id("fixture").status == "WARN"
    assert "underlying: missing evidence" in warning.by_id("fixture").details
    failure = gates.run_gates({})
    assert not failure.all_blocking_passed
    assert failure.as_rows() == [("fixture", "FAIL", "missing evidence")]


def test_gate_directories_are_independent_during_concurrent_runs(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    manifest = {"module_id": "aguayluz-pr", "generated_at": "2026-09-12T00:00:00Z",
                "entries": [{"source_ref": "fixture:present", "tier": "T1", "access_date": "2026-09-12"}]}
    for directory in (good, bad):
        write(directory, "source_manifest.json", manifest)
    write(good, "utility_assets.json", [{"source_ref": "fixture:present"}])
    write(bad, "utility_assets.json", [{"source_ref": "fixture:missing"}])
    original = gates.OUTPUTS_DIR
    rendezvous = Barrier(2)

    def concurrent_gate(*, outputs_dir):
        rendezvous.wait(timeout=10)
        return gates.gate_g02_source_manifest(outputs_dir=outputs_dir)

    monkeypatch.setattr(gates, "GATE_FUNCS", {"G02_SOURCE_MANIFEST": concurrent_gate})
    with ThreadPoolExecutor(max_workers=2) as executor:
        reports = list(executor.map(lambda path: gates.run_gates({}, outputs_dir=path), (good, bad)))
    assert [report.by_id("G02_SOURCE_MANIFEST").status for report in reports] == ["PASS", "FAIL"]
    assert original == gates.OUTPUTS_DIR
