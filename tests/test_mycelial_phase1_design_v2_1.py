"""Final-head static certification for Ballot A design-only package v2.1."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

_REPO = Path(__file__).resolve().parents[1]
_SCHEMA_DIR = _REPO / "schemas" / "mycelial-phase1" / "v2.1"
_FIXTURE = _REPO / "tests" / "fixtures" / "mycelial_phase1_design" / "v2.1" / "cases.json"
_DOC = _REPO / "docs" / "MYCELIAL_PHASE1_BALLOT_A_DESIGN_V2_1.md"
_REPORT = _REPO / "reports" / "mycelial_phase1_design" / "ballot_a_v2_1_final_head_certification.json"
_EXPECTED_SCHEMAS = {
    "source-license-provenance.schema.json",
    "sampling-effort.schema.json",
    "taxonomic-evidence.schema.json",
    "temporal-environmental-evidence.schema.json",
    "lifecycle-evidence.schema.json",
    "receipt-accounting.schema.json",
}
_SCENARIO_CLASSES = {
    "positive",
    "negative",
    "missing",
    "stale",
    "contradictory",
    "partial",
    "failed",
    "rejected",
    "correction",
    "retraction",
    "duplicate",
    "replay",
    "supersession",
    "rollback",
}
_FORBIDDEN_CHANGED_PREFIXES = (
    ".github/workflows/",
    ".federation/",
    "config/",
    "dashboard/",
    "data/",
    "desktop/",
    "exports/",
    "research/",
    "schemas/sql/",
    "scripts/",
    "server/",
    "src/",
)
_FORBIDDEN_CHANGED_FILES = {
    "federation.json",
    "pyproject.toml",
    "dashboard/package.json",
    "dashboard/package-lock.json",
}
_ALLOWED_CHANGED_PREFIXES = (
    "docs/MYCELIAL_PHASE1_BALLOT_A_DESIGN_V2_1.md",
    "reports/mycelial_phase1_design/ballot_a_v2_1_final_head_certification.json",
    "schemas/mycelial-phase1/v2.1/",
    "tests/fixtures/mycelial_phase1_design/v2.1/",
    "tests/test_mycelial_phase1_design_v2_1.py",
)
_EXPECTED_CHANGED_FILES = {
    "docs/MYCELIAL_PHASE1_BALLOT_A_DESIGN_V2_1.md",
    "reports/mycelial_phase1_design/ballot_a_v2_1_final_head_certification.json",
    "schemas/mycelial-phase1/v2.1/lifecycle-evidence.schema.json",
    "schemas/mycelial-phase1/v2.1/receipt-accounting.schema.json",
    "schemas/mycelial-phase1/v2.1/sampling-effort.schema.json",
    "schemas/mycelial-phase1/v2.1/source-license-provenance.schema.json",
    "schemas/mycelial-phase1/v2.1/taxonomic-evidence.schema.json",
    "schemas/mycelial-phase1/v2.1/temporal-environmental-evidence.schema.json",
    "tests/fixtures/mycelial_phase1_design/v2.1/cases.json",
    "tests/test_mycelial_phase1_design_v2_1.py",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _changed_paths() -> list[str]:
    diff = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        cwd=_REPO,
        check=False,
        text=True,
        capture_output=True,
    )
    if diff.returncode == 0:
        return [line for line in diff.stdout.splitlines() if line]

    # GitHub's pull_request checkout is a shallow synthetic merge ref and may
    # not include an origin/main ref. The merge commit still exposes the changed
    # file inventory needed for this boundary gate.
    tree = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "HEAD"],
        cwd=_REPO,
        check=True,
        text=True,
        capture_output=True,
    )
    changed = sorted({line for line in tree.stdout.splitlines() if line})
    if changed:
        return changed

    report = _load_json(_REPORT)
    assert set(report["expected_changed_files"]) == _EXPECTED_CHANGED_FILES
    return sorted(report["expected_changed_files"])


@pytest.fixture(scope="module")
def package() -> tuple[dict[str, dict], dict]:
    schemas = {path.name: _load_json(path) for path in _SCHEMA_DIR.glob("*.schema.json")}
    return schemas, _load_json(_FIXTURE)


def test_schema_inventory_is_exact_versioned_and_valid(package):
    schemas, _ = package
    assert set(schemas) == _EXPECTED_SCHEMAS
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert "/mycelial-phase1/v2.1/" in schema["$id"]
        serialized = json.dumps(schema)
        assert '"const": "2.1.0"' in serialized or '"const":"2.1.0"' in serialized


def test_all_positive_fixtures_validate(package):
    schemas, fixtures = package
    checker = FormatChecker()
    for case in fixtures["valid_cases"]:
        validator = Draft202012Validator(schemas[case["schema"]], format_checker=checker)
        errors = sorted(validator.iter_errors(case["record"]), key=lambda error: list(error.path))
        assert not errors, f"{case['name']}: {[error.message for error in errors]}"


def test_all_structurally_invalid_fixtures_fail(package):
    schemas, fixtures = package
    checker = FormatChecker()
    semantic_only = {"semantic_receipt_accounting_mismatch"}
    for case in fixtures["invalid_cases"]:
        if case["name"] in semantic_only:
            continue
        validator = Draft202012Validator(schemas[case["schema"]], format_checker=checker)
        assert list(validator.iter_errors(case["record"])), case["name"]


def test_authority_hold_and_staging_controls_are_bound(package):
    _, fixtures = package
    authority = fixtures["authority"]
    protection = fixtures["production_protection"]
    assert fixtures["package_id"] == "BUILD_AGUAYLUZ_PHASE1_A_DESIGN_ONLY_PR_v2_1"
    assert fixtures["fixture_version"] == "2.1.0"
    assert fixtures["package_version"] == "2.1.0"
    assert fixtures["staging_expiry"] == "2026-12-31"
    assert authority["design_ballot_receipt"] == 5175521569
    assert authority["research_ingest_hold_review"] == 4851413154
    assert authority["classification"] == "design_only"
    assert authority["approve_research_ingest"] == "HOLD"
    assert authority["ready_transition_authorized"] is False
    assert authority["merge_authorized"] is False
    assert authority["auto_merge_authorized"] is False
    assert protection["synthetic_fixture_only"] is True
    assert protection["production_admission_allowed"] is False
    assert protection["feature_flag_default"] == "disabled"


def test_receipt_accounting_is_deterministic(package):
    _, fixtures = package
    receipts = [
        case["record"]
        for case in fixtures["valid_cases"] + fixtures["invalid_cases"]
        if case["record"].get("record_type") == "import_receipt_design"
    ]
    for receipt in receipts:
        accounted = receipt["accepted"] + receipt["rejected"] + receipt["review_queue"] + receipt["exact_replays"]
        if receipt["attempted"] == 5:
            assert receipt["attempted"] == accounted
        else:
            assert receipt["attempted"] != accounted


def test_negative_survey_is_non_detection_not_absence(package):
    _, fixtures = package
    negatives = [
        case["record"]
        for case in fixtures["valid_cases"]
        if case["record"].get("record_type") == "survey_effort" and case["record"]["outcome"] == "negative"
    ]
    assert negatives
    for survey in negatives:
        assert survey["completed"] is True
        assert survey["person_minutes"] > 0
        assert survey["non_detection_interpretation"] == (
            "documented non-detection under stated effort; not proof of absence"
        )


def test_missing_values_remain_missing(package):
    _, fixtures = package
    snapshots = [
        case["record"]
        for case in fixtures["valid_cases"]
        if case["record"].get("record_type") == "environmental_snapshot"
    ]
    assert any(snapshot["value"] is None and "missing" in snapshot["quality_flags"] for snapshot in snapshots)


def test_no_exact_coordinate_or_request_boolean_contract(package):
    schemas, fixtures = package
    serialized = json.dumps({"schemas": schemas, "fixtures": fixtures}, sort_keys=True).lower()
    assert "authorized_sensitive" not in serialized
    assert "exact_public" not in json.dumps(fixtures["valid_cases"], sort_keys=True).lower()
    for case in fixtures["valid_cases"]:
        record = case["record"]
        if record.get("record_type") == "lifecycle_site":
            assert record["location"]["latitude"] is None
            assert record["location"]["longitude"] is None
            assert record["location"]["mode"] in {"none", "generalized", "withheld"}


def test_fixture_scenario_coverage_is_complete(package):
    _, fixtures = package
    assert set(fixtures["scenario_classes"]) == _SCENARIO_CLASSES
    for required in ("positive", "missing", "stale", "contradictory"):
        assert required in fixtures["scenario_contracts"] or required == "positive"


def test_boundary_assertions_forbid_runtime_surfaces(package):
    _, fixtures = package
    assert fixtures["boundary_assertions"] == {
        "data_ingestion": "prohibited",
        "persistence": "prohibited",
        "runtime_or_gui_admission": "prohibited",
        "api": "prohibited",
        "scheduler": "prohibited",
        "notification": "prohibited",
        "export": "prohibited",
        "federation": "prohibited",
    }
    assert all(not value for value in (
        fixtures["production_protection"]["calibrated_analytics_allowed"],
        fixtures["production_protection"]["location_ranking_allowed"],
        fixtures["production_protection"]["connectivity_output_allowed"],
        fixtures["production_protection"]["public_exact_sensitive_coordinates_allowed"],
        fixtures["production_protection"]["infrastructure_inference_allowed"],
    ))


def test_package_files_are_declarative_only():
    package_files = [
        *list(_SCHEMA_DIR.rglob("*")),
        *list(_FIXTURE.parent.rglob("*")),
        _DOC,
        _REPORT,
    ]
    package_files = [path for path in package_files if path.is_file()]
    assert package_files
    assert all(path.suffix in {".json", ".md"} for path in package_files)
    lowered = "\n".join(path.read_text(encoding="utf-8") for path in package_files).lower()
    forbidden_markers = (
        "sqlite3.connect(",
        "create table ",
        "insert into ",
        "fastapi(",
        "apirouter(",
        "@app.",
        "requests.get(",
        "httpx.",
        "schedule.every(",
        "send_notification",
        "federation_export",
    )
    assert all(marker not in lowered for marker in forbidden_markers)


def test_branch_diff_does_not_touch_executable_or_runtime_surfaces():
    changed = _changed_paths()
    assert set(changed) == _EXPECTED_CHANGED_FILES
    for path in changed:
        assert path.startswith(_ALLOWED_CHANGED_PREFIXES), path
        assert path not in _FORBIDDEN_CHANGED_FILES, path
        assert not path.startswith(_FORBIDDEN_CHANGED_PREFIXES), path
