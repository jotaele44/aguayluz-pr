from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "infrastructure-ontology" / "v0.1"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "infrastructure_ontology_v0_1" / "cases.json"
LEDGER_PATH = ROOT / "docs" / "infrastructure_ontology_overlap_ledger_v0_1.json"
UNIVERSE_PATH = ROOT / "docs" / "infrastructure_ontology_source_universe_v0_1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_design_schemas_are_draft_2020_12_and_versioned() -> None:
    expected = {
        "concept.schema.json",
        "source-term.schema.json",
        "mapping.schema.json",
        "context-rule.schema.json",
        "deprecation.schema.json",
        "normalization-receipt.schema.json",
    }
    assert {p.name for p in SCHEMA_DIR.glob("*.json")} == expected
    for path in SCHEMA_DIR.glob("*.json"):
        payload = load(path)
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert "/v0.1/" in payload["$id"]


def test_raw_terms_are_preserved_and_ambiguous_terms_fail_closed() -> None:
    fixture = load(FIXTURE_PATH)
    assert all(case["preserve_raw"] is True for case in fixture["cases"])
    ambiguous = {case["raw"] for case in fixture["cases"] if case["status"] == "ambiguous"}
    assert {"PTA", "Represa", "Pozo"}.issubset(ambiguous)
    assert all(not case["concept_ids"] for case in fixture["cases"] if case["status"] == "ambiguous")


def test_composite_label_maps_to_multiple_concepts_without_merging_assets() -> None:
    fixture = load(FIXTURE_PATH)
    case = next(item for item in fixture["cases"] if item["id"] == "eb_tk_los_alvarez")
    assert case["status"] == "composite"
    assert case["concept_ids"] == ["AYL.WATER.PUMP_STATION", "AYL.WATER.STORAGE_TANK"]
    assertions = fixture["global_assertions"]
    assert assertions == {
        "asset_merge_performed": False,
        "hydraulic_edge_created": False,
        "evidence_promoted": False,
        "runtime_wired": False,
    }


def test_fixture_serialization_is_deterministic_and_idempotent() -> None:
    payload = load(FIXTURE_PATH)
    first = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    second = json.dumps(json.loads(first), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_overlap_ledger_preserves_existing_contract_ownership() -> None:
    ledger = load(LEDGER_PATH)
    assert ledger["pinned_main_sha"] == "4a1c400c3f6288c97a7226c4fa4adaffabcc4388"
    assert {row["pr"] for row in ledger["reviewed_pull_requests"]} == {101, 119, 128, 132}
    assert ledger["new_owner"]["does_not_own"] == [
        "physical_asset_identity",
        "hydraulic_topology",
        "water_balance_entries",
        "failure_localization",
        "operational_admission",
    ]
    assert ledger["runtime_activation"] is False
    assert ledger["migration"] is False
    assert ledger["data_rewrite"] is False


def test_bounded_universe_defines_100_percent_without_claiming_global_completeness() -> None:
    universe = load(UNIVERSE_PATH)
    authorities = {row["id"] for row in universe["authorities"]}
    assert {"AAA", "EPA", "USGS", "AWWA", "DRNA", "FEMA", "NOAA", "PREPA_LUMA"}.issubset(authorities)
    assert "frozen manifest" in universe["completion_definition"]
    assert universe["runtime_activation"] is False
    assert universe["data_rewrite"] is False
