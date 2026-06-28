"""Generic maintenance detectors + end-to-end runner behaviour."""

from __future__ import annotations

import json

from aguayluz.maintenance import REPORT_RELPATH, detect, run_maintenance
from aguayluz.maintenance import state as state_mod


def test_missing_federation_json_is_critical(tmp_path):
    state = state_mod.collect_repo_state(tmp_path)  # empty dir, no federation.json
    findings = detect.detect_missing_required_files("aguayluz-pr", tmp_path, state)
    assert any(f.category == "manifest" and f.severity == "critical" for f in findings)


def test_runner_blocks_on_missing_manifest(tmp_path):
    report = run_maintenance(root=tmp_path, mode="audit", write=False)
    assert report.promotion_blocked is True
    assert report.critical_count >= 1


def test_invalid_json_output_is_error(tmp_path):
    fed = {
        "program_id": "aguayluz-pr",
        "canonical_outputs": {"base44_export": "outputs/base44_export.json"},
    }
    (tmp_path / "federation.json").write_text(json.dumps(fed), encoding="utf-8")
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "base44_export.json").write_text("{not json", encoding="utf-8")
    state = state_mod.collect_repo_state(tmp_path)
    findings = detect.detect_invalid_json("aguayluz-pr", tmp_path, state)
    assert any(f.category == "schema" and f.severity == "error" for f in findings)


def test_clean_repo_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("EPA_WATERS_API_KEY", "x" * 20)
    fed = {
        "program_id": "aguayluz-pr",
        "source_truth": {"runtime_required_keys": ["EPA_WATERS_API_KEY"]},
        "canonical_outputs": {},
    }
    (tmp_path / "federation.json").write_text(json.dumps(fed), encoding="utf-8")
    report = run_maintenance(root=tmp_path, mode="audit", write=True)
    assert report.promotion_blocked is False
    written = tmp_path / REPORT_RELPATH
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    for key in ("repo", "maintenance_version", "findings_count", "critical_count", "promotion_blocked"):
        assert key in data
