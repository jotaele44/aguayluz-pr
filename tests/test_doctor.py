"""End-to-end check that this repo's `.federation/doctor-checks.json` is
valid and that the doctor engine reports the expected classes for each
declared check -- most importantly, that presence-only and not-automatable
checks never report PASS."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from prii_doctor import run

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_manifest_loads_and_declares_the_expected_checks():
    report = run(_REPO_ROOT)
    ids = {r.check_id for r in report.results}
    assert ids == {
        "epa_waters_api_key_presence",
        "neon_api_token_presence",
        "miluma_waf_gated",
        "aee_incidents_mirror_staleness",
        "outputs_schema_validation",
    }


def test_presence_only_checks_never_report_pass():
    """Regardless of whether EPA_WATERS_API_KEY/NEON_API_TOKEN happen to be
    set in the environment running this test, presence-only checks must
    never render PASS -- presence was never validity."""
    report = run(_REPO_ROOT)
    for check_id in ("epa_waters_api_key_presence", "neon_api_token_presence"):
        result = report.by_id(check_id)
        assert result is not None
        assert result.status != "PASS", result
        assert result.diagnosability_class.value == "presence-only"


def test_not_automatable_checks_are_always_info_and_carry_last_known_state():
    """miluma_waf_gated and aee_incidents_mirror_staleness must always
    render INFO, carrying the manifest's recorded last_known_state.as_of
    date in the detail text -- proving no live probe was attempted for
    either, only the recorded state was echoed back."""
    report = run(_REPO_ROOT)
    expected_as_of = {
        "miluma_waf_gated": "2026-08-25",
        "aee_incidents_mirror_staleness": "2025-03-03",
    }
    for check_id, as_of in expected_as_of.items():
        result = report.by_id(check_id)
        assert result is not None
        assert result.status == "INFO", result
        assert result.diagnosability_class.value == "not-automatable"
        assert as_of in result.detail, result.detail


def test_schema_delegate_reflects_validate_repo_py():
    """outputs_schema_validation shells out to `python scripts/validate_repo.py`
    (the literal command this repo declares in federation.json -- by
    design, the delegate runner must run exactly that, not second-guess it)
    and must produce a local-deterministic PASS/FAIL that matches running
    the same gates directly, PROVIDED `python` resolves on PATH in this
    environment. Some shells only alias `python3`, in which case the
    subprocess correctly reports the repo's own command failing to launch
    -- that is accurate delegate behavior, not a bug, so this test only
    asserts equivalence when it can actually hold."""
    from aguayluz.validation import run_gates

    report = run(_REPO_ROOT)
    result = report.by_id("outputs_schema_validation")
    assert result is not None
    assert result.diagnosability_class.value == "local-deterministic"

    if shutil.which("python") is None:
        pytest.skip("'python' is not on PATH in this environment (only 'python3') -- "
                    "the delegate faithfully reports the repo's own declared command failing to launch.")

    gate_report = run_gates()
    if gate_report.all_blocking_passed:
        assert result.status == "PASS", result
    else:
        assert result.status == "FAIL", result
