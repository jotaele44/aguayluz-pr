from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.failure_localization import FailureLocalizationControlPlane  # noqa: E402
from research.failure_localization.contracts import digest  # noqa: E402
from research.failure_localization.operational_adapters import (  # noqa: E402
    BUNDLE_SCHEMA,
    INPUT_SCHEMA,
    FailureLocalizationOperationalAdapters,
    OperationalAdapterError,
)

FIXTURE_PATH = (
    ROOT
    / "tests/fixtures/failure_localization_operational_adapter_scenarios_v0_1.json"
)
SCHEMA_PATH = (
    ROOT
    / "schemas/failure-localization/v0.2/"
    "failure_localization_operational_adapters.schema.json"
)


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def envelope(
    input_id: str,
    kind: str,
    payload: dict,
    *,
    observed_at: str = "2026-08-04T20:50:00Z",
    freshness: str = "current",
    disclosure: str = "operator_restricted",
) -> dict:
    return {
        "schema_version": INPUT_SCHEMA,
        "input_id": input_id,
        "input_kind": kind,
        "source_id": f"synthetic-prasa-{kind}",
        "observed_at": observed_at,
        "received_at": "2026-08-04T20:55:00Z",
        "sha256": digest(payload),
        "evidence_tier": "T4",
        "freshness": freshness,
        "quality": "valid",
        "disclosure": disclosure,
        "authority": "synthetic_fixture",
        "review_status": "accepted",
        "payload": payload,
    }


def build_bundle(scenario: str) -> dict:
    fixture = load_fixture()
    records: list[dict] = []
    for asset in fixture["asset_identities"]:
        payload = {
            "source_asset_id": asset["ref"],
            "canonical_asset_id": asset["canonical"],
            "asset_type": asset["type"],
            "name": asset["name"],
            "system_id": fixture["system_id"],
            "attributes": asset.get("attributes", {}),
            "max_age_seconds": 7200,
        }
        records.append(
            envelope(
                f"ASSET_{asset['ref']}",
                "asset_identity",
                payload,
                disclosure=asset["disclosure"],
            )
        )
    for index, membership in enumerate(fixture["memberships"], 1):
        payload = {
            "asset_ref": membership["asset"],
            "pressure_zone_ref": membership["zone"],
            "service_area_ref": membership["service"],
            "max_age_seconds": 7200,
        }
        records.append(envelope(f"MEMBERSHIP_{index}", "pressure_zone_membership", payload))
    for edge in fixture["topology"]:
        payload = {
            "source_edge_id": edge["ref"],
            "from_asset_ref": edge["from"],
            "to_asset_ref": edge["to"],
            "edge_type": edge.get("type", "FEEDS"),
            "topology_state": "operator_declared",
            "attributes": {
                "expected_pressure_drop": 2.0,
                "pressure_tolerance": 5.0,
            },
            "max_age_seconds": 7200,
        }
        records.append(envelope(f"TOPOLOGY_{edge['ref']}", "hydraulic_topology", payload))
    for short in fixture["scenarios"][scenario]:
        payload = {
            "observation_id": short["id"],
            "target_type": short.get("target_type", "asset"),
            "target_ref": short["target"],
            "value": short["value"],
            "expected_value": short.get("expected"),
            "tolerance": short.get("tolerance"),
            "uncertainty": short.get("uncertainty", 1.0),
            "assertion": short.get("assertion", "measurement"),
            "max_age_seconds": short.get("max_age_seconds", 7200),
        }
        records.append(
            envelope(
                short["id"],
                short["kind"],
                payload,
                observed_at=short.get("observed_at", "2026-08-04T20:50:00Z"),
                freshness=short.get("freshness", "current"),
            )
        )
    return {
        "schema_version": BUNDLE_SCHEMA,
        "bundle_id": f"SYNTHETIC_PRASA_{scenario.upper()}",
        "mode": "offline_replay",
        "synthetic_fixture": True,
        "operational_claims_forbidden": True,
        "records": records,
    }


def replay(tmp_path: Path, scenario: str, *, bundle: dict | None = None):
    fixture = load_fixture()
    plane = FailureLocalizationControlPlane(
        tmp_path,
        default_max_age_seconds=7200,
        operator_view_enabled=False,
    )
    adapter = FailureLocalizationOperationalAdapters(
        plane,
        synthetic_fixture_mode=True,
    )
    selected = bundle or build_bundle(scenario)
    run = adapter.replay_bundle(
        selected,
        as_of=fixture["as_of"],
        system_id=fixture["system_id"],
        idempotency_key=f"replay:{scenario}",
    )
    return plane, adapter, run


def hypotheses(run: dict) -> set[str]:
    return {item["hypothesis"] for item in run["assessment"]["candidates"]}


def test_fixture_inputs_are_complete_hash_bound_and_synthetic():
    required = {
        "source_id",
        "observed_at",
        "received_at",
        "sha256",
        "evidence_tier",
        "freshness",
        "quality",
        "disclosure",
        "authority",
    }
    for scenario in load_fixture()["scenarios"]:
        for record in build_bundle(scenario)["records"]:
            assert required <= record.keys()
            assert record["sha256"] == digest(record["payload"])
            assert record["evidence_tier"] == "T4"
            assert record["authority"] == "synthetic_fixture"


def test_versioned_schema_validates_inputs_receipts_and_run(tmp_path):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    bundle = build_bundle("known_break")
    for record in bundle["records"]:
        validator.validate(record)
    plane, _, run = replay(tmp_path, "known_break", bundle=bundle)
    for receipt in plane.store.read("operational_adapter_receipts"):
        validator.validate(receipt)
    validator.validate(run)


@pytest.mark.parametrize(
    ("scenario", "hypothesis"),
    [
        ("known_break", "transmission_main_break"),
        ("hidden_leak", "hidden_leak_or_main_break"),
        ("pump_failure", "pump_failure"),
        ("valve_misconfiguration", "valve_misconfiguration_or_closure"),
        ("tank_depletion", "tank_depletion"),
        ("power_loss", "power_loss_at_pumping_asset"),
        ("unresolved", "unresolved_service_delivery_failure"),
    ],
)
def test_operational_replays_generate_bounded_nonexact_candidates(
    tmp_path, scenario, hypothesis
):
    _, _, run = replay(tmp_path, scenario)
    assert run["status"] == "admitted"
    assert run["maximum_operational_grade"] == "L3"
    assert hypothesis in hypotheses(run)
    assert all(
        item["localization_grade"] in {"L0", "L1", "L2", "L3"}
        and item["exact_failure_claim"] is False
        for item in run["assessment"]["candidates"]
    )
    assert run["automatic_control_actions"] is False
    assert run["notifications_enabled"] is False
    assert run["production_promotion_enabled"] is False


def test_multicausal_replay_preserves_pump_and_valve_hypotheses(tmp_path):
    _, _, run = replay(tmp_path, "multicausal")
    assert {"pump_failure", "valve_misconfiguration_or_closure"} <= hypotheses(run)


def test_bad_payload_hash_is_rejected_and_receipted(tmp_path):
    bundle = build_bundle("unresolved")
    bad = envelope(
        "BAD_HASH",
        "outage",
        {
            "observation_id": "BAD_HASH",
            "target_type": "asset",
            "target_ref": "SERVICE",
            "value": "outage",
            "max_age_seconds": 7200,
        },
    )
    bad["sha256"] = "0" * 64
    bundle["records"].append(bad)
    plane, _, run = replay(tmp_path, "bad-hash", bundle=bundle)
    receipt = next(
        row
        for row in plane.store.read("operational_adapter_receipts")
        if row["input_id"] == "BAD_HASH"
    )
    assert receipt["admission_status"] == "rejected"
    assert receipt["reason_codes"] == ["operational_input_sha256_mismatch"]
    assert any("BAD_HASH" in blocker for blocker in run["blockers"])
    assert all(not item["exact_failure_claim"] for item in run["assessment"]["candidates"])


def test_missing_topology_caps_operational_localization_at_l2(tmp_path):
    bundle = build_bundle("pump_failure")
    bundle["records"] = [
        item for item in bundle["records"] if item["input_kind"] != "hydraulic_topology"
    ]
    _, _, run = replay(tmp_path, "missing-topology", bundle=bundle)
    assert run["status"] == "degraded"
    assert run["maximum_operational_grade"] == "L2"
    assert "hydraulic_topology_absent" in run["blockers"]
    assert all(not item["exact_failure_claim"] for item in run["assessment"]["candidates"])


def test_stale_telemetry_is_preserved_but_excluded_from_current_diagnosis(tmp_path):
    _, _, run = replay(tmp_path, "stale_telemetry")
    assert run["status"] == "degraded"
    assert run["assessment"]["stale_observation_ids"] == ["OBS_STALE_OUTAGE"]
    assert run["assessment"]["candidates"][0]["hypothesis"] == "unknown"


def test_identifier_conflict_fails_closed_to_l0(tmp_path):
    bundle = build_bundle("hidden_leak")
    conflict_payload = {
        "source_asset_id": "MAIN",
        "canonical_asset_id": "AYL_MAIN_CONFLICT",
        "asset_type": "transmission",
        "name": "Conflicting synthetic main",
        "system_id": "SYS_EAST",
        "attributes": {},
        "max_age_seconds": 7200,
    }
    bundle["records"].append(
        envelope("ASSET_MAIN_CONFLICT", "asset_identity", conflict_payload)
    )
    _, _, run = replay(tmp_path, "identifier-conflict", bundle=bundle)
    assert run["status"] == "degraded"
    assert run["maximum_operational_grade"] == "L0"
    assert any("source_identifier_conflict:MAIN" in item for item in run["blockers"])
    assert all(not item["exact_failure_claim"] for item in run["assessment"]["candidates"])


def test_synthetic_field_result_cannot_set_authority_or_field_confirmation(tmp_path):
    bundle = build_bundle("hidden_leak")
    payload = {
        "observation_id": "OBS_SYNTHETIC_FIELD",
        "target_type": "asset",
        "target_ref": "MAIN",
        "value": "excavation_confirmed_break",
        "assertion": "excavation_confirmed_break",
        "uncertainty": 0.0,
        "max_age_seconds": 7200,
    }
    bundle["records"].append(envelope("OBS_SYNTHETIC_FIELD", "field_result", payload))
    plane, _, run = replay(tmp_path, "synthetic-field", bundle=bundle)
    stored = next(
        row
        for row in plane.store.read("observations")
        if row["observation_id"] == "OBS_SYNTHETIC_FIELD"
    )
    assert stored["authoritative"] is False
    assert stored["field_confirmed"] is False
    assert all(item["localization_grade"] != "L4" for item in run["assessment"]["candidates"])


def test_replay_is_idempotent_and_ledgers_remain_append_only(tmp_path):
    bundle = build_bundle("known_break")
    plane, adapter, first = replay(tmp_path, "known-break", bundle=bundle)
    receipt_count = len(plane.store.read("operational_adapter_receipts"))
    observation_count = len(plane.store.read("observations"))
    second = adapter.replay_bundle(
        bundle,
        as_of=load_fixture()["as_of"],
        system_id=load_fixture()["system_id"],
        idempotency_key="replay:known-break",
    )
    assert second["adapter_run_id"] == first["adapter_run_id"]
    assert second["replayed"] is True
    assert len(plane.store.read("operational_adapter_receipts")) == receipt_count
    assert len(plane.store.read("observations")) == observation_count


def test_live_credentials_or_polling_are_rejected_before_persistence(tmp_path):
    bundle = build_bundle("unresolved")
    bundle["token"] = "forbidden"
    plane = FailureLocalizationControlPlane(tmp_path)
    adapter = FailureLocalizationOperationalAdapters(plane, synthetic_fixture_mode=True)
    with pytest.raises(OperationalAdapterError, match="active_or_credential_key_forbidden"):
        adapter.replay_bundle(
            bundle,
            as_of=load_fixture()["as_of"],
            system_id=load_fixture()["system_id"],
            idempotency_key="forbidden",
        )
    assert plane.store.read("operational_adapter_receipts") == []
    assert plane.store.read("operational_adapter_runs") == []
