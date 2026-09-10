from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "mycelial-source" / "v1" / "acquisition-receipt.schema.json"
FIXTURES = (
    ROOT / "tests" / "fixtures" / "mycelial_source" / "v1" / "acquisition_receipts.json"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    schema = _load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_schema_is_valid_draft_2020_12():
    _validator()


def test_fixture_classification_is_explicit():
    payload = _load(FIXTURES)
    assert payload["classification"] == "SYNTHETIC_FIXTURES_ONLY_NOT_SOURCE_ACQUISITIONS"


def test_fixture_expectations_match_schema():
    validator = _validator()
    payload = _load(FIXTURES)
    for case in payload["cases"]:
        errors = list(validator.iter_errors(case["record"]))
        assert (not errors) is case["valid"], (
            case["name"],
            [error.message for error in errors],
        )


def test_complete_receipt_requires_original_byte_identity():
    payload = _load(FIXTURES)
    complete = next(
        case["record"]
        for case in payload["cases"]
        if case["name"] == "valid complete synthetic archive"
    )
    assert complete["original_payload"]["captured"] is True
    assert complete["original_payload"]["byte_count"] > 0
    assert len(complete["original_payload"]["sha256"]) == 64
    assert complete["admission_state"] == "not_canonical_not_model_eligible"


def test_failed_receipt_cannot_claim_uncaptured_bytes():
    payload = _load(FIXTURES)
    failed = next(
        case["record"]
        for case in payload["cases"]
        if case["name"] == "valid failed dns attempt"
    )
    assert failed["original_payload"] == {
        "captured": False,
        "byte_count": None,
        "sha256": None,
        "storage_reference": None,
    }
    assert failed["failure_class"] != "none"


def test_receipt_contract_never_grants_canonical_or_model_admission():
    schema = _load(SCHEMA)
    assert schema["properties"]["admission_state"]["const"] == (
        "not_canonical_not_model_eligible"
    )
