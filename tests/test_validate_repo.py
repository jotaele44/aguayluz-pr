"""End-to-end check of validation gates on a clean repo (M1 expected state)."""

from __future__ import annotations

import pytest

from aguayluz.validation import GATE_FUNCS, assert_schemas_resolvable, run_gates


def test_all_gate_ids_present():
    assert set(GATE_FUNCS) == {
        "G01_SCHEMA",
        "G02_SOURCE_MANIFEST",
        "G03_CONFIDENCE",
        "G04_REVIEW_QUEUE",
        "G05_COVERAGE_LEDGER",
        "G06_HUB_EXPORT",
        "G07_NO_SECRETS",
        "G08_TESTS",
    }


def test_schemas_resolvable():
    assert_schemas_resolvable()


def test_clean_repo_has_no_blocking_failures(tmp_path, monkeypatch):
    """On the empty M1 scaffold: G07 (secrets), G08 (tests-present) must PASS;
    output-dependent gates SKIP. No FAIL anywhere."""
    from aguayluz import validation as v

    monkeypatch.setattr(v, "OUTPUTS_DIR", tmp_path)
    report = run_gates()
    statuses = {r.gate_id: r.status for r in report.results}
    assert statuses["G07_NO_SECRETS"] == "PASS", statuses
    assert statuses["G08_TESTS"] == "PASS", statuses
    fails = [r for r in report.results if r.status == "FAIL"]
    assert not fails, f"unexpected blocking failures on clean repo: {fails}"
    assert report.all_blocking_passed


def test_secret_pattern_detects_obvious_leak(tmp_path, monkeypatch):
    """G07 must catch an obvious key-shaped string when it lives inside a tracked file."""
    from aguayluz import validation as v

    # Stage a fake repo root with one .py file containing a leak.
    # Build the secret literal at runtime so the scanner doesn't flag THIS file.
    fake_root = tmp_path / "fakerepo"
    fake_root.mkdir()
    fake_secret = "sk_" + "live_" + "Ab" + "CdEf1234567890" + "XYZ987654321"
    (fake_root / "leak.py").write_text(
        f'API_KEY = "{fake_secret}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(v, "REPO_ROOT", fake_root)
    result = v.gate_g07_no_secrets()
    assert result.status == "FAIL", result


def test_schema_gate_does_not_count_unrecognized_json_as_validated(tmp_path, monkeypatch):
    from aguayluz import validation as v

    monkeypatch.setattr(v, "OUTPUTS_DIR", tmp_path)
    (tmp_path / "unrelated.json").write_text('{}', encoding="utf-8")
    result = v.gate_g01_schema()
    assert result.status == "SKIP"
    assert "1 unvalidated JSON file(s)" in result.details


@pytest.mark.parametrize("filename", [
    "utility_assets.json", "service_events.json", "monitoring_readings.json", "alert_events.json",
])
def test_schema_gate_requires_entity_array_root(tmp_path, monkeypatch, filename):
    from aguayluz import validation as v

    monkeypatch.setattr(v, "OUTPUTS_DIR", tmp_path)
    # Root shape must fail even when an individual entity would pass its schema.
    monkeypatch.setattr(v, "validate_against_schema", lambda *_: None)
    (tmp_path / filename).write_text('{}', encoding="utf-8")
    result = v.gate_g01_schema()
    assert result.status == "FAIL"
    assert "expected an array" in result.details


def test_schema_gate_closes_file_accounting_and_checks_each_entity(tmp_path, monkeypatch):
    from aguayluz import validation as v

    monkeypatch.setattr(v, "OUTPUTS_DIR", tmp_path)
    seen = []
    monkeypatch.setattr(v, "validate_against_schema", lambda schema, record: seen.append((schema, record)))
    (tmp_path / "utility_assets.json").write_text('[{"id":"a"},{"id":"b"}]', encoding="utf-8")
    (tmp_path / "unrelated.json").write_text('{}', encoding="utf-8")
    result = v.gate_g01_schema()
    assert result.status == "PASS"
    assert result.details == "1 file(s) validated; 1 unvalidated JSON file(s): unrelated.json"
    assert seen == [("utility_asset", {"id": "a"}), ("utility_asset", {"id": "b"})]
