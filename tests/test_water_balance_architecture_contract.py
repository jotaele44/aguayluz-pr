from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" / "water-balance" / "v0.1"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "water_balance_architecture_v0_1" / "fixture_suite.json"
INVENTORY_PATH = ROOT / "docs" / "architecture" / "water_balance_component_inventory_v0.1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    schema = _load(SCHEMA_ROOT / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_design_schemas_and_positive_fixtures_validate() -> None:
    fixtures = _load(FIXTURE_PATH)
    inventory = _load(INVENTORY_PATH)

    _validator("water-balance-contract.schema.json").validate(fixtures["positive_contract"])
    _validator("nested-balance-assessment.schema.json").validate(fixtures["positive_assessment"])
    _validator("component-compatibility.schema.json").validate(inventory)


def test_fixture_taxonomy_is_complete_and_fail_closed() -> None:
    fixtures = _load(FIXTURE_PATH)
    expected = {
        "positive",
        "negative",
        "missing",
        "stale",
        "contradictory",
        "double_counted",
        "meter_reset",
        "time_skew",
        "unit_error",
        "underdetermined",
    }
    cases = fixtures["cases"]

    assert {case["scenario"] for case in cases} == expected
    assert len(cases) == len(expected)
    assert all(case["incident_promotion_eligible"] is False for case in cases)
    assert all(case["expected_closure_status"] in {
        "closed",
        "within_uncertainty",
        "open",
        "underdetermined",
        "contradictory",
        "not_evaluated",
    } for case in cases)


def test_inventory_authorizes_no_runtime_or_data_migration() -> None:
    inventory = _load(INVENTORY_PATH)

    assert inventory["design_only"] is True
    assert inventory["source_main_sha"] == "17c843595b5cdfbcef4e5f7b1ac6c662092e335d"
    assert inventory["components"]
    assert all(component["runtime_changed"] is False for component in inventory["components"])
    assert all(component["data_migration_authorized"] is False for component in inventory["components"])


def test_assessment_residual_cannot_be_promoted_or_exported() -> None:
    assessment = _load(FIXTURE_PATH)["positive_assessment"]

    assert assessment["residual"]["proof_state"] == "model_only"
    assert assessment["incident_promotion_eligible"] is False
    assert assessment["federation_export_eligible"] is False
    assert "not proof" in assessment["attribution"]["non_proof_statement"]
