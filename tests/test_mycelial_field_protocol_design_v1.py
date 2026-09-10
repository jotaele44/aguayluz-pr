from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "mycelial-field" / "v1"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "mycelial_field_protocol" / "v1" / "cases.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    schema = _load(SCHEMA_DIR / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_all_schemas_are_valid_draft_2020_12():
    for name in (
        "field-site.schema.json",
        "field-survey.schema.json",
        "fruiting-observation.schema.json",
    ):
        _validator(name)


def test_synthetic_fixture_classification_is_explicit():
    payload = _load(FIXTURE_PATH)
    assert payload["classification"] == "SYNTHETIC_FIXTURES_ONLY_NOT_BIOLOGICAL_DATA"


def test_fixture_expectations_match_schema_results():
    payload = _load(FIXTURE_PATH)
    for case in payload["cases"]:
        errors = list(_validator(case["schema"]).iter_errors(case["record"]))
        assert (not errors) is case["valid"], (
            case["name"],
            [error.message for error in errors],
        )


def test_valid_survey_fixtures_have_observer_arithmetic_and_monotonic_times():
    payload = _load(FIXTURE_PATH)
    for case in payload["cases"]:
        if case["schema"] != "field-survey.schema.json" or not case["valid"]:
            continue
        record = case["record"]
        assert record["observer_count"] == len(record["observer_pseudonyms"])
        if record["started_at"] is not None and record["ended_at"] is not None:
            assert _parse_time(record["started_at"]) <= _parse_time(record["ended_at"])


def test_non_detection_requires_completed_positive_effort():
    payload = _load(FIXTURE_PATH)
    valid_surveys = [
        case["record"]
        for case in payload["cases"]
        if case["schema"] == "field-survey.schema.json" and case["valid"]
    ]
    negatives = [row for row in valid_surveys if row["detection_status"] == "not_detected"]
    assert negatives
    for row in negatives:
        assert row["visit_status"] == "completed"
        assert row["person_minutes"] > 0
        assert row["non_detection_interpretation"] == (
            "documented non-detection under stated effort; not proof of absence"
        )


def test_missed_and_aborted_visits_are_not_negative_surveys():
    payload = _load(FIXTURE_PATH)
    for case in payload["cases"]:
        if case["schema"] != "field-survey.schema.json" or not case["valid"]:
            continue
        row = case["record"]
        if row["visit_status"] in {"missed", "aborted"}:
            assert row["detection_status"] != "not_detected"
            assert row["non_detection_interpretation"] is None


def test_valid_fruiting_observations_cannot_encode_non_detection_as_a_body():
    payload = _load(FIXTURE_PATH)
    for case in payload["cases"]:
        if case["schema"] != "fruiting-observation.schema.json" or not case["valid"]:
            continue
        assert case["record"]["visible_fruiting_state"] != "not_observed"


def test_valid_protocol_records_do_not_contain_exact_coordinate_keys():
    payload = _load(FIXTURE_PATH)

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    forbidden = {"latitude", "longitude", "private_latitude", "private_longitude"}
    for case in payload["cases"]:
        if not case["valid"]:
            continue
        assert forbidden.isdisjoint(set(keys(case["record"])))


def test_protocol_package_contains_no_predictive_fields():
    predictive = {
        "probability",
        "prediction",
        "predicted_probability",
        "habitat_suitability",
        "connectivity_score",
        "location_rank",
        "mycelium_extent",
    }
    for path in SCHEMA_DIR.glob("*.json"):
        assert predictive.isdisjoint(set(_load(path).get("properties", {})))
