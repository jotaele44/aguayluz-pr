"""End-to-end check of validation gates on a clean repo (M1 expected state)."""

from __future__ import annotations

from aguayluz.validation import GATE_FUNCS, assert_schemas_resolvable, run_gates


def test_all_gate_ids_present():
    assert set(GATE_FUNCS) == {
        "G01_SCHEMA",
        "G02_SOURCE_MANIFEST",
        "G03_CONFIDENCE",
        "G04_REVIEW_QUEUE",
        "G05_COVERAGE_LEDGER",
        "G06_BASE44_EXPORT",
        "G07_NO_SECRETS",
        "G08_TESTS",
    }


def test_schemas_resolvable():
    assert_schemas_resolvable()


def test_clean_repo_has_no_blocking_failures():
    """On the empty M1 scaffold: G07 (secrets), G08 (tests-present) must PASS;
    output-dependent gates SKIP. No FAIL anywhere."""
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
