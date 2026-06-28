"""Duplicate detection + safe-correct behaviour (audit never mutates)."""

from __future__ import annotations

import json

from aguayluz.maintenance import run_maintenance
from aguayluz.maintenance.corrections import remove_exact_duplicate_jsonl_rows


def _scaffold_with_dupes(root):
    (root / "exports" / "federation").mkdir(parents=True, exist_ok=True)
    fed = {
        "program_id": "aguayluz-pr",
        "source_truth": {"runtime_required_keys": []},
        "canonical_outputs": {"stream": "exports/federation/sources.jsonl"},
    }
    (root / "federation.json").write_text(json.dumps(fed), encoding="utf-8")
    jsonl = root / "exports" / "federation" / "sources.jsonl"
    rows = ['{"id": 1}', '{"id": 2}', '{"id": 1}']  # one exact duplicate
    jsonl.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return jsonl


def test_remove_exact_duplicate_jsonl_rows(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\n{"a":1}\n{"a":2}\n', encoding="utf-8")
    removed = remove_exact_duplicate_jsonl_rows(p)
    assert removed == 1
    assert p.read_text(encoding="utf-8").count('{"a":1}') == 1


def test_audit_reports_but_does_not_mutate(tmp_path):
    jsonl = _scaffold_with_dupes(tmp_path)
    before = jsonl.read_text(encoding="utf-8")
    report = run_maintenance(root=tmp_path, mode="audit", write=False)
    dupe_findings = [f for f in report.findings if f.category == "duplicate"]
    assert len(dupe_findings) == 1
    assert dupe_findings[0].action == "none"
    assert jsonl.read_text(encoding="utf-8") == before  # untouched in audit


def test_safe_correct_removes_duplicate(tmp_path):
    jsonl = _scaffold_with_dupes(tmp_path)
    report = run_maintenance(root=tmp_path, mode="safe-correct", write=False)
    dupe_findings = [f for f in report.findings if f.category == "duplicate"]
    assert len(dupe_findings) == 1
    assert dupe_findings[0].action == "auto_corrected"
    # the exact duplicate row is gone
    lines = [ln for ln in jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines.count('{"id": 1}') == 1
    assert len(lines) == 2
