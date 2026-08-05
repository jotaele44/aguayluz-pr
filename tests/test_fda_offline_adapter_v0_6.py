from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from research.regulatory.fda_offline_adapter import FDAOfflineAdapter, OfflineFDAClient

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/regulatory/fda_offline_records_v0_6.json"
PROFILE = ROOT / "research/regulatory/fda_source_profile_v0_6.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_validator(name: str) -> Draft202012Validator:
    schema = load_json(ROOT / "schemas" / name)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def enabled_adapter() -> FDAOfflineAdapter:
    return FDAOfflineAdapter(OfflineFDAClient(load_json(FIXTURE)), enabled=True)


def test_profile_is_disabled_and_forbids_live_side_effects() -> None:
    profile = load_json(PROFILE)
    assert profile["status"] == "disabled_offline_only"
    assert profile["network_access"] is False
    assert profile["persistence"] is False
    assert profile["scheduler_registration"] is False
    assert profile["automatic_entity_promotion"] is False
    assert profile["compliance_inference"] is False


def test_adapter_defaults_to_disabled() -> None:
    adapter = FDAOfflineAdapter(OfflineFDAClient(load_json(FIXTURE)))
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.discover()


def test_discover_fetch_normalize_and_checkpoint_validate() -> None:
    adapter = enabled_adapter()
    locators, checkpoint = adapter.discover()
    assert len(locators) == 9
    assert checkpoint.cursor == 9
    assert checkpoint.fixture_revision == "fda-fixtures/v0.6"

    observation_validator = schema_validator("regulatory_observation.schema.json")
    receipt_validator = schema_validator("regulatory_source_receipt.schema.json")
    families = set()
    freshness = set()

    for locator in locators:
        raw, receipt = adapter.fetch(locator)
        receipt_validator.validate(receipt)
        observation = adapter.normalize(raw, receipt)
        observation_validator.validate(observation)
        families.add(observation["record_family"])
        freshness.add(observation["freshness_state"])

    assert families == {"entity", "permit", "inspection", "enforcement"}
    assert {"current", "historical", "stale"} <= freshness


def test_receipt_hash_binding_and_tamper_rejection() -> None:
    adapter = enabled_adapter()
    locator = adapter.discover()[0][0]
    raw, receipt = adapter.fetch(locator)
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["byte_count"] == len(raw)
    with pytest.raises(ValueError, match="hash mismatch"):
        adapter.normalize(raw + b" ", receipt)


def test_replay_is_stable_and_normalizer_versions_are_additive() -> None:
    adapter = enabled_adapter()
    locator = adapter.discover()[0][0]
    raw, receipt = adapter.fetch(locator)
    first = adapter.normalize(raw, receipt, version="fda-offline/v0.6")
    replay = adapter.normalize(raw, receipt, version="fda-offline/v0.6")
    newer = adapter.normalize(raw, receipt, version="fda-offline/v0.7")
    assert first["observation_id"] == replay["observation_id"]
    assert newer["observation_id"] != first["observation_id"]


def test_retracted_record_preserves_supersession_lineage() -> None:
    adapter = enabled_adapter()
    locators = adapter.discover()[0]
    locator = next(item for item in locators if item.provider_record_id == "REG-RETRACTED")
    raw, receipt = adapter.fetch(locator)
    observation = adapter.normalize(raw, receipt)
    assert observation["freshness_state"] == "historical"
    assert observation["source_asserted_status"] == "retracted"
    assert observation["supersedes_observation_id"] == "AYL_REGOBS_FDA_SOURCE_REG-OLD"


def test_fei_collision_and_address_contradiction_remain_unmerged() -> None:
    adapter = enabled_adapter()
    observations = []
    for locator in adapter.discover()[0]:
        raw, receipt = adapter.fetch(locator)
        observations.append(adapter.normalize(raw, receipt))

    by_fei: dict[str, list[dict]] = defaultdict(list)
    for observation in observations:
        for identifier in observation["identifiers"]:
            if identifier["scheme"] == "fei":
                by_fei[identifier["value"]].append(observation)

    collision = by_fei["1001"]
    establishment_records = [
        item for item in collision if item["payload"]["record_type"] == "establishment"
    ]
    assert len(establishment_records) == 2
    assert {item["payload"]["address"] for item in establishment_records} == {
        "Road 1, Dorado, PR",
        "Arecibo, PR",
    }
    assert all("candidate_asset_id" not in item for item in observations)
    assert all("decision_state" not in item for item in observations)


def test_checkpoint_rejects_fixture_revision_drift() -> None:
    adapter = enabled_adapter()
    _, checkpoint = adapter.discover()
    changed = load_json(FIXTURE)
    changed["fixture_revision"] = "fda-fixtures/changed"
    changed_adapter = FDAOfflineAdapter(OfflineFDAClient(changed), enabled=True)
    with pytest.raises(ValueError, match="revision mismatch"):
        changed_adapter.discover(checkpoint)


def test_module_contains_no_live_or_persistence_imports() -> None:
    source = (ROOT / "research/regulatory/fda_offline_adapter.py").read_text().lower()
    forbidden = (
        "import httpx",
        "import requests",
        "urllib.request",
        "sqlite3",
        "sqlalchemy",
        "apscheduler",
        "subprocess",
        "socket",
    )
    assert not any(token in source for token in forbidden)
