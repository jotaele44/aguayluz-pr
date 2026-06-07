"""Tests for `scripts/audit_classifier.py`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import audit_classifier  # type: ignore[import-not-found]  # noqa: E402
from aguayluz.ingest.frs_client import FRS_BASE_URL  # noqa: E402


def _frs_envelope(facilities: list[dict]) -> dict:
    return {"Results": {"FRSFacility": facilities}}


def _facility(reg_id: str, name: str, *, lat: str | None = "18.4", lon: str | None = "-66.2") -> dict:
    return {
        "RegistryId": reg_id,
        "FacilityName": name,
        "CityName": "BAYAMON",
        "StateAbbr": "PR",
        "Latitude83": lat,
        "Longitude83": lon,
    }


# ---------- audit_city ----------


def test_audit_city_returns_zero_for_empty_response(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FRS_BASE_URL}?state_abbr=PR&output=JSON&city_name=GHOST",
        json=_frs_envelope([]),
        status_code=200,
    )
    result = audit_classifier.audit_city(state="PR", city="GHOST")
    assert result["total"] == 0
    assert result["utility_count"] == 0
    assert result["utility_pct"] == 0.0


def test_audit_city_classifies_real_pattern(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json=_frs_envelope([
            _facility("1", "BAYAMON WATER TREATMENT PLANT"),
            _facility("2", "PRASA BAYAMON NORTE WWTP"),
            _facility("3", "BAYAMON CONCRETE IND"),
            _facility("4", "APOLONIA APARTMENTS"),
        ]),
        status_code=200,
    )
    result = audit_classifier.audit_city(state="PR", city="BAYAMON")
    # 2 utility (water + wastewater), 2 non-utility (apartments + concrete).
    assert result["total"] == 4
    assert result["utility_count"] == 2
    assert result["utility_pct"] == 50.0


def test_audit_city_counts_records_with_coords(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json=_frs_envelope([
            _facility("1", "BAYAMON WTP", lat="18.4", lon="-66.2"),
            _facility("2", "PRASA WWTP", lat=None, lon=None),
        ]),
        status_code=200,
    )
    result = audit_classifier.audit_city(state="PR", city="BAYAMON")
    assert result["utility_count"] == 2
    assert result["with_coords"] == 1
    assert result["without_coords"] == 1


# ---------- evaluate ----------


def test_evaluate_within_tolerance_returns_empty():
    reference = {
        "minimum_utility_pct": 0.5,
        "tolerance_pct_points": 0.5,
        "reference_run": {"total": 600, "utility_pct": 1.0},
    }
    observation = {"city": "BAYAMON", "total": 620, "utility_pct": 1.2}
    assert audit_classifier.evaluate(observation, reference) == []


def test_evaluate_flags_below_minimum():
    reference = {
        "minimum_utility_pct": 1.0,
        "tolerance_pct_points": 0.5,
        "reference_run": {"total": 600, "utility_pct": 1.5},
    }
    observation = {"city": "BAYAMON", "total": 600, "utility_pct": 0.3}
    findings = audit_classifier.evaluate(observation, reference)
    assert any("classifier likely degraded" in f for f in findings)


def test_evaluate_flags_tolerance_drift():
    reference = {
        "minimum_utility_pct": 0.5,
        "tolerance_pct_points": 0.5,
        "reference_run": {"total": 600, "utility_pct": 1.0},
    }
    observation = {"city": "BAYAMON", "total": 600, "utility_pct": 2.0}
    findings = audit_classifier.evaluate(observation, reference)
    assert any("drifted >0.50pp from reference" in f for f in findings)


def test_evaluate_flags_total_record_drift():
    """Big swing in facility count suggests EPA added/removed records."""
    reference = {
        "minimum_utility_pct": 0.5,
        "tolerance_pct_points": 0.5,
        "reference_run": {"total": 600, "utility_pct": 1.0},
    }
    observation = {"city": "BAYAMON", "total": 900, "utility_pct": 1.0}  # +50%
    findings = audit_classifier.evaluate(observation, reference)
    assert any("facility_total" in f and "drifted" in f for f in findings)


def test_evaluate_skips_total_check_when_reference_missing():
    reference = {
        "minimum_utility_pct": 0.5,
        "tolerance_pct_points": 0.5,
        "reference_run": {"utility_pct": 1.0},  # no total
    }
    observation = {"city": "BAYAMON", "total": 600, "utility_pct": 1.0}
    findings = audit_classifier.evaluate(observation, reference)
    assert all("facility_total" not in f for f in findings)


# ---------- CLI ----------


def test_cli_write_then_check_passes(tmp_path, httpx_mock):
    """Write a reference from one observation, then --check against the same
    observation → exit 0."""
    facilities = [
        _facility("1", "BAYAMON WATER TREATMENT PLANT"),
        _facility("2", "PRASA BAYAMON NORTE WWTP"),
        _facility("3", "BAYAMON CONCRETE IND"),
    ]
    ref = tmp_path / "ref.json"
    httpx_mock.add_response(method="GET", json=_frs_envelope(facilities), status_code=200)
    rc = audit_classifier.main([
        "--write-reference",
        "--city", "BAYAMON",
        "--reference-path", str(ref),
    ])
    assert rc == 0
    assert ref.exists()

    httpx_mock.add_response(method="GET", json=_frs_envelope(facilities), status_code=200)
    rc = audit_classifier.main([
        "--check",
        "--city", "BAYAMON",
        "--reference-path", str(ref),
    ])
    assert rc == 0


def test_cli_check_returns_2_when_reference_missing(tmp_path, httpx_mock):
    httpx_mock.add_response(method="GET", json=_frs_envelope([]), status_code=200)
    rc = audit_classifier.main([
        "--check",
        "--city", "BAYAMON",
        "--reference-path", str(tmp_path / "missing.json"),
    ])
    assert rc == 2


def test_cli_check_returns_1_on_drift(tmp_path, httpx_mock):
    """Write reference with 50% rate, then check against 0% → exit 1."""
    good = [
        _facility("1", "PRASA WWTP"),
        _facility("2", "BAYAMON CONCRETE IND"),
    ]
    ref = tmp_path / "ref.json"
    httpx_mock.add_response(method="GET", json=_frs_envelope(good), status_code=200)
    audit_classifier.main([
        "--write-reference",
        "--city", "BAYAMON",
        "--reference-path", str(ref),
        "--minimum-pct", "5.0",  # raise the bar so the drift fires
    ])

    drifted = [_facility("X", "NOT A UTILITY")] * 3
    httpx_mock.add_response(method="GET", json=_frs_envelope(drifted), status_code=200)
    rc = audit_classifier.main([
        "--check",
        "--city", "BAYAMON",
        "--reference-path", str(ref),
    ])
    assert rc == 1


def test_committed_reference_loads_and_has_required_keys():
    data = json.loads(
        (REPO_ROOT / "tests" / "baseline" / "classifier_rate.json").read_text(encoding="utf-8")
    )
    assert "minimum_utility_pct" in data
    assert "tolerance_pct_points" in data
    assert "reference_run" in data
    assert "utility_pct" in data["reference_run"]


@pytest.mark.parametrize("severity_text", [
    "classifier rate: within tolerance",
    "classifier drift detected",
])
def test_cli_output_includes_severity_marker(severity_text):
    """Both success and failure outputs are scannable from CI logs."""
    # No subprocess here — just verify the strings exist in the script source
    # so we don't regress the operator-readable status lines.
    text = (REPO_ROOT / "scripts" / "audit_classifier.py").read_text(encoding="utf-8")
    assert severity_text in text
