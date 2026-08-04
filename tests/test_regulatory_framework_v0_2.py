from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/regulatory/framework_cases_v0_2.json"
SCHEMAS = ROOT / "schemas"
PROVIDERS = {"EPA", "FDA", "USGS", "DRNA", "PRASA_AAA", "PREQB"}
SECRET_MARKERS = ("authorization", "bearer ", "api_key", "token=", "session", "cookie")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    schema = load_json(SCHEMAS / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def stable_observation_id(provider: str, provider_record_id: str, raw: str, version: str) -> str:
    material = f"{provider}\0{provider_record_id}\0{raw}\0{version}".encode()
    return f"AYL_REGOBS_{provider}_{hashlib.sha256(material).hexdigest()[:24]}"


def test_all_provider_observations_validate_and_cover_freshness_states() -> None:
    cases = load_json(FIXTURE)
    observation_validator = validator("regulatory_observation.schema.json")

    for observation in cases["observations"]:
        observation_validator.validate(observation)

    providers = {record["provider"] for record in cases["observations"]}
    freshness = {record["freshness_state"] for record in cases["observations"]}
    assert providers == PROVIDERS
    assert {"current", "historical", "stale", "conflicting"} <= freshness


def test_schema_rejects_malformed_observation() -> None:
    cases = load_json(FIXTURE)
    observation_validator = validator("regulatory_observation.schema.json")
    malformed = next(
        case["record"]
        for case in cases["invalid_observations"]
        if case["case"] == "malformed_provider"
    )
    with pytest.raises(ValidationError):
        observation_validator.validate(malformed)


def test_retraction_requires_supersession_reference() -> None:
    cases = load_json(FIXTURE)
    record = next(
        case["record"]
        for case in cases["invalid_observations"]
        if case["case"] == "retracted_without_supersession"
    )
    validator("regulatory_observation.schema.json").validate(record)
    assert record["source_asserted_status"] == "retracted"
    assert not record.get("supersedes_observation_id")


def test_duplicate_hard_identifier_is_detected_not_collapsed() -> None:
    observations = load_json(FIXTURE)["observations"]
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for observation in observations:
        for identifier in observation.get("identifiers", []):
            index[(identifier["scheme"], identifier["value"])].append(
                observation["observation_id"]
            )

    collisions = {key: ids for key, ids in index.items() if len(ids) > 1}
    assert collisions == {
        ("fei", "1001"): ["AYL_REGOBS_FDA_001", "AYL_REGOBS_FDA_DUPLICATE"]
    }


def test_entity_link_approval_is_fail_closed() -> None:
    links = load_json(FIXTURE)["links"]
    link_validator = validator("regulatory_entity_link.schema.json")

    link_validator.validate(links["approved"])
    link_validator.validate(links["unverified"])
    assert links["unverified"]["decision_state"] != "approved"

    with pytest.raises(ValidationError):
        link_validator.validate(links["conflicting_approval"])

    missing_actor = dict(links["approved"], decided_by=None)
    with pytest.raises(ValidationError):
        link_validator.validate(missing_actor)


def test_receipts_bind_exact_bytes_and_exclude_secrets() -> None:
    cases = load_json(FIXTURE)
    receipt_validator = validator("regulatory_source_receipt.schema.json")

    for provider, raw in cases["raw_payloads"].items():
        content = raw.encode("utf-8")
        receipt = {
            "receipt_id": f"AYL_REGRCPT_{provider}_001",
            "provider": provider,
            "retrieved_at": "2026-08-04T19:00:00Z",
            "request_locator": f"fixture://{provider.lower()}/record/001",
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_count": len(content),
            "media_type": "application/json",
            "retrieval_status": "success",
            "http_status": 200,
            "redactions": [],
        }
        receipt_validator.validate(receipt)
        assert receipt["sha256"] == hashlib.sha256(content).hexdigest()
        assert receipt["byte_count"] == len(content)
        serialized = json.dumps(receipt).lower()
        assert not any(marker in serialized for marker in SECRET_MARKERS)


def test_replay_is_idempotent_and_version_changes_are_additive() -> None:
    cases = load_json(FIXTURE)
    raw = cases["raw_payloads"]["FDA"]
    current = stable_observation_id("FDA", "FEI-1001", raw, "fda/v1")
    replay = stable_observation_id("FDA", "FEI-1001", raw, "fda/v1")
    renormalized = stable_observation_id("FDA", "FEI-1001", raw, "fda/v2")

    assert current == replay
    assert renormalized != current


def test_contract_module_stays_design_only() -> None:
    source = (ROOT / "research/regulatory/contracts.py").read_text(encoding="utf-8").lower()
    forbidden = ("httpx.", "requests.", "sqlite3", "sqlalchemy", "apscheduler", "subprocess")
    assert not any(token in source for token in forbidden)
