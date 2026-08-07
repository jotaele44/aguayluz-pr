"""Static conformance tests for the Ballot A design-only package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

_REPO = Path(__file__).resolve().parents[1]
_SCHEMA_DIR = _REPO / "schemas" / "mycelial-phase1" / "v1"
_FIXTURE = _REPO / "tests" / "fixtures" / "mycelial_phase1_design" / "v1" / "cases.json"
_DOC = _REPO / "docs" / "MYCELIAL_PHASE1_BALLOT_A_DESIGN_V1.md"
_EXPECTED_SCHEMAS = {
    "source-license-provenance.schema.json",
    "sampling-effort.schema.json",
    "taxonomic-evidence.schema.json",
    "temporal-environmental-evidence.schema.json",
    "lifecycle-evidence.schema.json",
    "receipt-accounting.schema.json",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def package() -> tuple[dict[str, dict], dict]:
    schemas = {path.name: _load_json(path) for path in _SCHEMA_DIR.glob("*.schema.json")}
    return schemas, _load_json(_FIXTURE)


def test_schema_inventory_is_exact_and_valid(package):
    schemas, _ = package
    assert set(schemas) == _EXPECTED_SCHEMAS
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert "/mycelial-phase1/v1/" in schema["$id"]


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
        case["record"] for case in fixtures["valid_cases"]
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
        case["record"] for case in fixtures["valid_cases"]
        if case["record"].get("record_type") == "environmental_snapshot"
    ]
    assert any(snapshot["value"] is None and "missing" in snapshot["quality_flags"] for snapshot in snapshots)


def test_no_exact_coordinate_or_request_boolean_contract(package):
    schemas, fixtures = package
    serialized = json.dumps({"schemas": schemas, "fixtures": fixtures}, sort_keys=True).lower()
    assert "authorized_sensitive" not in serialized
    for case in fixtures["valid_cases"]:
        record = case["record"]
        if record.get("record_type") == "lifecycle_site":
            assert record["location"]["latitude"] is None
            assert record["location"]["longitude"] is None
            assert record["location"]["mode"] in {"none", "generalized", "withheld"}


def test_fixture_scenario_coverage_is_complete(package):
    _, fixtures = package
    assert set(fixtures["scenario_classes"]) == {
        "positive", "negative", "missing", "stale", "contradictory", "partial", "failed",
        "rejected", "correction", "retraction", "duplicate", "replay", "supersession", "rollback",
    }


def test_package_is_declarative_only():
    package_files = [
        *list(_SCHEMA_DIR.rglob("*")),
        *list(_FIXTURE.parent.rglob("*")),
        _DOC,
    ]
    package_files = [path for path in package_files if path.is_file()]
    assert package_files
    assert all(path.suffix in {".json", ".md"} for path in package_files)
    lowered = "\n".join(path.read_text(encoding="utf-8") for path in package_files).lower()
    forbidden = (
        "sqlite3.connect(", "create table ", "insert into ", "fastapi(", "apirouter(",
        "@app.", "requests.get(", "httpx.", "schedule.every(",
    )
    assert all(marker not in lowered for marker in forbidden)


def test_authority_receipts_and_hold_are_bound(package):
    _, fixtures = package
    authority = fixtures["authority"]
    assert authority["design_ballot_receipt"] == 5175521569
    assert authority["research_ingest_hold_review"] == 4851413154
    assert authority["classification"] == "design_only"
