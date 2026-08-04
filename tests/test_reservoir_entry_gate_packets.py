from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "architecture" / "reservoir_water_balance_entry_gate_packets_v0.5.json"
SCHEMA = ROOT / "schemas" / "water-balance" / "v0.5" / "reservoir-entry-gate-packets.schema.json"
FIXTURES = ROOT / "tests" / "fixtures" / "water_balance_entry_gates_v0_5" / "fixture_suite.json"

EXPECTED_RESERVOIRS = {
    "carraizo_lago_loiza", "la_plata", "guajataca", "patillas", "dos_bocas",
    "caonillas", "cerrillos", "cidra", "carite", "toa_vaca", "guayabal",
    "loco", "lucchetti",
}
EXPECTED_TERMS = {
    "withdrawal", "controlled_release", "spill", "transfer", "precipitation",
    "evaporation", "inflow", "outflow", "storage_state",
}
EXPECTED_EDGES = {"inflow", "outflow", "withdrawal", "controlled_release", "spill", "transfer"}
EXPECTED_FIXTURES = {
    "missing_stage_storage_curve", "unresolved_topology", "missing_withdrawal",
    "mixed_datum", "unsynchronized_intervals", "duplicate_rainfall",
    "absent_uncertainty", "restricted_operator_data",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_registry_validates_against_versioned_schema() -> None:
    schema = _load(SCHEMA)
    registry = _load(REGISTRY)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(registry)


def test_every_repository_reservoir_has_one_independent_packet() -> None:
    packets = _load(REGISTRY)["reservoir_packets"]
    ids = [packet["reservoir_id"] for packet in packets]
    assert set(ids) == EXPECTED_RESERVOIRS
    assert len(ids) == len(set(ids))
    assert len({packet["packet_id"] for packet in packets}) == len(packets)
    assert len({packet["canonical_asset_id"] for packet in packets}) == len(packets)


def test_shared_contract_is_complete_and_fail_closed() -> None:
    shared = _load(REGISTRY)["shared_entry_gate_contract"]
    assert set(shared["required_terms"]) == EXPECTED_TERMS
    assert set(shared["required_candidate_edges"]) == EXPECTED_EDGES
    assert shared["default_boundary_evidence"] == "unresolved"
    assert shared["default_edge_evidence"] == "unresolved"
    assert shared["default_term_status"] == "external_acquisition_required"
    assert shared["balance_eligible_by_default"] is False
    assert set(shared["permitted_pre_entry_result"]) == {"underdetermined", "not_evaluated"}
    assert len(shared["source_receipt_required_fields"]) == 16
    assert len(shared["stage_storage_curve_required_fields"]) == 13


def test_no_packet_is_entry_ready_or_balance_authorized() -> None:
    packets = _load(REGISTRY)["reservoir_packets"]
    assert all(packet["entry_state"] != "entry_ready" for packet in packets)
    assert all(packet["balance_execution_authorized"] is False for packet in packets)
    assert all(packet["entry_eligible"] is False for packet in packets)
    assert all(packet["exact_site_identity_state"] != "authoritative" for packet in packets)
    assert all(packet["stage_storage_curve_status"] != "present_eligible" for packet in packets)


def test_carraizo_is_reference_pilot_and_loco_fails_closed() -> None:
    by_id = {packet["reservoir_id"]: packet for packet in _load(REGISTRY)["reservoir_packets"]}
    assert by_id["carraizo_lago_loiza"]["selected_reference_pilot"] is True
    assert by_id["carraizo_lago_loiza"]["entry_state"] == "selected_blocked"
    assert by_id["loco"]["universe_status"] == "candidate_repository_named_requires_reconfirmation"
    assert by_id["loco"]["entry_state"] == "universe_identity_review"
    assert all(not packet["selected_reference_pilot"] for rid, packet in by_id.items() if rid != "carraizo_lago_loiza")


def test_storage_evidence_never_becomes_volume_without_curve() -> None:
    for packet in _load(REGISTRY)["reservoir_packets"]:
        override = packet["term_status_overrides"].get("storage_state")
        if packet["universe_status"] == "confirmed_repository_named":
            assert override == "present_ineligible"
        else:
            assert override is None
        assert packet["stage_storage_curve_status"] == "missing"


def test_schema_exposes_source_receipt_and_stage_storage_contracts() -> None:
    defs = _load(SCHEMA)["$defs"]
    shared = _load(REGISTRY)["shared_entry_gate_contract"]
    assert set(defs["SourceReceipt"]["required"]) == set(shared["source_receipt_required_fields"])
    assert set(defs["StageStorageCurve"]["required"]) == set(shared["stage_storage_curve_required_fields"])


def test_fail_closed_fixture_taxonomy_is_complete() -> None:
    suite = _load(FIXTURES)
    fixtures = suite["fixtures"]
    assert {fixture["fixture_id"] for fixture in fixtures} == EXPECTED_FIXTURES
    assert all(fixture["expected_entry_eligible"] is False for fixture in fixtures)
    assert all(fixture["expected_result"] in {"underdetermined", "not_evaluated"} for fixture in fixtures)
    assert all(value is False for value in suite["prohibitions"].values())


def test_all_runtime_and_governance_actions_remain_prohibited() -> None:
    registry = _load(REGISTRY)
    assert registry["design_only"] is True
    assert registry["parent_pr"] == 122
    assert registry["parent_head_sha"] == "1c8d0363335aaab2ab8acb36eceb69acbba2657c"
    assert registry["prohibitions"]
    assert all(value is False for value in registry["prohibitions"].values())
