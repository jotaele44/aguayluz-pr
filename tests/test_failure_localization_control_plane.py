from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.failure_localization import FailureLocalizationControlPlane  # noqa: E402

FIXTURE_PATH = ROOT / "tests/fixtures/failure_localization_scenarios_v0_1.json"
SCHEMA_PATH = ROOT / "schemas/failure-localization/v0.1/failure_localization_contracts.schema.json"


def load_fixture() -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    defaults = fixture.pop("observation_defaults")
    expanded = {}
    for scenario, rows in fixture["scenarios"].items():
        expanded[scenario] = []
        for short in rows:
            row = dict(defaults)
            row.update({"observation_id": short["id"], "metric": short["m"], "value": short["v"]})
            if "a" in short:
                row["asset_id"] = short["a"]
            if "e" in short:
                row["edge_id"] = short["e"]
            aliases = {
                "at": "observed_at", "x": "expected_value", "t": "tolerance",
                "u": "uncertainty", "tier": "evidence_tier", "auth": "authoritative",
                "field": "field_confirmed", "assertion": "assertion",
                "age": "max_age_seconds", "source": "source_id",
            }
            for key, target in aliases.items():
                if key in short:
                    row[target] = short[key]
            expanded[scenario].append(row)
    fixture["scenarios"] = expanded
    return fixture


def build_plane(tmp_path: Path, scenario: str, *, operator: bool = False):
    fixture = load_fixture()
    plane = FailureLocalizationControlPlane(
        tmp_path, default_max_age_seconds=7200, operator_view_enabled=operator
    )
    graph_receipt = plane.configure_graph(
        fixture["graph"], idempotency_key=f"graph:{scenario}"
    )
    for observation in fixture["scenarios"][scenario]:
        plane.ingest_observation(
            observation,
            idempotency_key=f"obs:{observation['observation_id']}",
        )
    assessment = plane.assess(
        as_of=fixture["as_of"], system_id="SYS_EAST", idempotency_key=f"assess:{scenario}"
    )
    return plane, assessment, graph_receipt


def candidate_for(assessment: dict, hypothesis: str) -> dict:
    return next(item for item in assessment["candidates"] if item["hypothesis"] == hypothesis)


def authoritative_observation(observation_id: str, asset_id: str, assertion: str, *, field=False):
    return {
        "schema_version": "aguayluz.failure-observation/v0.1",
        "observation_id": observation_id,
        "observed_at": "2026-08-04T20:59:00Z",
        "asset_id": asset_id,
        "metric": "field_confirmation" if field else "failure_assertion",
        "value": assertion,
        "source_id": "prasa-work-order",
        "source_kind": "operator_record",
        "evidence_tier": "T1",
        "authoritative": True,
        "field_confirmed": field,
        "assertion": assertion,
        "review_status": "accepted",
        "quality": "valid",
        "max_age_seconds": 7200,
        "uncertainty": 0.0,
        "related_asset_ids": [],
    }


def test_graph_and_observation_contracts_fail_closed(tmp_path):
    fixture = load_fixture()
    plane = FailureLocalizationControlPlane(tmp_path)
    duplicate = copy.deepcopy(fixture["graph"])
    duplicate["assets"].append(copy.deepcopy(duplicate["assets"][0]))
    with pytest.raises(ValueError, match="duplicate_asset_id"):
        plane.configure_graph(duplicate, idempotency_key="bad")

    graph = plane.configure_graph(fixture["graph"], idempotency_key="graph")
    replay = plane.configure_graph(fixture["graph"], idempotency_key="graph")
    assert graph["graph_id"] == replay["graph_id"]
    assert replay["replayed"] is True

    invalid = copy.deepcopy(fixture["scenarios"]["unresolved"][0])
    invalid["edge_id"] = "AYL_EDGE_EAST_09"
    with pytest.raises(ValueError, match="exactly_one_target"):
        plane.ingest_observation(invalid, idempotency_key="invalid")


def test_versioned_schema_validates_graph_observation_and_assessment(tmp_path):
    plane, assessment, graph = build_plane(tmp_path, "known_break")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(graph)
    validator.validate(plane.store.read("observations")[0])
    validator.validate(assessment)


def test_known_break_and_hidden_leak_stop_at_l3(tmp_path):
    _, known, _ = build_plane(tmp_path / "known", "known_break")
    _, hidden, _ = build_plane(tmp_path / "hidden", "hidden_leak")
    known_candidate = candidate_for(known, "transmission_main_break")
    hidden_candidate = candidate_for(hidden, "hidden_leak_or_main_break")
    for candidate in (known_candidate, hidden_candidate):
        assert candidate["localization_grade"] == "L3"
        assert candidate["exact_failure_claim"] is False
        assert "acoustic_leak_survey" in candidate["required_field_tests"]
    assert any(
        row["model_residual_is_not_failure_proof"]
        for row in known["mass_balance"]
        if row.get("residual") is not None
    )


@pytest.mark.parametrize(
    ("scenario", "hypothesis"),
    [
        ("pump_failure", "pump_failure"),
        ("valve_misconfiguration", "valve_misconfiguration_or_closure"),
        ("tank_depletion", "tank_depletion"),
        ("power_loss", "power_loss_at_pumping_asset"),
        ("unresolved", "unresolved_service_delivery_failure"),
    ],
)
def test_failure_families_generate_bounded_candidates(tmp_path, scenario, hypothesis):
    _, assessment, _ = build_plane(tmp_path, scenario)
    candidate = candidate_for(assessment, hypothesis)
    assert candidate["localization_grade"] in {"L1", "L2", "L3"}
    assert candidate["confidence"] >= 35
    assert candidate["required_field_tests"]
    assert candidate["exact_failure_claim"] is False


def test_multicausal_case_preserves_competing_hypotheses(tmp_path):
    _, assessment, _ = build_plane(tmp_path, "multicausal")
    hypotheses = {item["hypothesis"] for item in assessment["candidates"]}
    assert "source_water_shortage" in hypotheses
    assert "pump_failure" in hypotheses
    pump = candidate_for(assessment, "pump_failure")
    assert "OBS_MULTI_POWER" in pump["supporting_evidence_ids"]


def test_stale_observation_is_excluded_not_silently_promoted(tmp_path):
    fixture = load_fixture()
    plane = FailureLocalizationControlPlane(tmp_path, default_max_age_seconds=60)
    plane.configure_graph(fixture["graph"], idempotency_key="graph")
    stale = copy.deepcopy(fixture["scenarios"]["unresolved"][0])
    stale["observation_id"] = "OBS_STALE_OUTAGE"
    stale["observed_at"] = "2026-08-04T18:00:00Z"
    stale["max_age_seconds"] = 60
    plane.ingest_observation(stale, idempotency_key="stale")
    assessment = plane.assess(
        as_of=fixture["as_of"], system_id="SYS_EAST", idempotency_key="assess"
    )
    assert assessment["stale_observation_ids"] == ["OBS_STALE_OUTAGE"]
    assert assessment["candidates"][0]["hypothesis"] == "unknown"
    assert assessment["candidates"][0]["contradictions"] == ["only_stale_observations_available"]


def test_l4_requires_current_authoritative_t1_exact_asset_evidence(tmp_path):
    plane, assessment, _ = build_plane(tmp_path, "hidden_leak")
    candidate = candidate_for(assessment, "hidden_leak_or_main_break")

    weak = authoritative_observation("OBS_WEAK", "AYL_MAIN_EAST", "confirmed_main_break")
    weak["evidence_tier"] = "T2"
    plane.ingest_observation(weak, idempotency_key="weak")
    with pytest.raises(ValueError, match="l4_authoritative"):
        plane.promote_candidate(
            assessment_id=assessment["assessment_id"],
            candidate_id=candidate["candidate_id"],
            requested_grade="L4",
            evidence_observation_ids=["OBS_WEAK"],
            reviewer="operator-review",
            occurred_at="2026-08-04T21:00:00Z",
            idempotency_key="promote:weak",
        )

    exact = authoritative_observation("OBS_EXACT", "AYL_MAIN_EAST", "confirmed_main_break")
    plane.ingest_observation(exact, idempotency_key="exact")
    promoted = plane.promote_candidate(
        assessment_id=assessment["assessment_id"],
        candidate_id=candidate["candidate_id"],
        requested_grade="L4",
        evidence_observation_ids=["OBS_EXACT"],
        reviewer="operator-review",
        occurred_at="2026-08-04T21:00:00Z",
        idempotency_key="promote:l4",
    )
    assert candidate_for(promoted, "hidden_leak_or_main_break")["localization_grade"] == "L4"


def test_l5_requires_field_confirmation_after_l4_and_history_is_append_only(tmp_path):
    plane, assessment, _ = build_plane(tmp_path, "hidden_leak")
    candidate = candidate_for(assessment, "hidden_leak_or_main_break")
    exact = authoritative_observation("OBS_EXACT", "AYL_MAIN_EAST", "confirmed_main_break")
    field = authoritative_observation(
        "OBS_FIELD", "AYL_MAIN_EAST", "excavation_confirmed_break", field=True
    )
    plane.ingest_observation(exact, idempotency_key="exact")
    plane.ingest_observation(field, idempotency_key="field")

    with pytest.raises(ValueError, match="promotion_sequence"):
        plane.promote_candidate(
            assessment_id=assessment["assessment_id"],
            candidate_id=candidate["candidate_id"],
            requested_grade="L5",
            evidence_observation_ids=["OBS_FIELD"],
            reviewer="crew",
            occurred_at="2026-08-04T21:00:00Z",
            idempotency_key="too-soon",
        )

    plane.promote_candidate(
        assessment_id=assessment["assessment_id"],
        candidate_id=candidate["candidate_id"],
        requested_grade="L4",
        evidence_observation_ids=["OBS_EXACT"],
        reviewer="operator",
        occurred_at="2026-08-04T21:00:00Z",
        idempotency_key="l4",
    )
    final = plane.promote_candidate(
        assessment_id=assessment["assessment_id"],
        candidate_id=candidate["candidate_id"],
        requested_grade="L5",
        evidence_observation_ids=["OBS_FIELD"],
        reviewer="field-crew",
        occurred_at="2026-08-04T21:01:00Z",
        idempotency_key="l5",
    )
    final_candidate = candidate_for(final, "hidden_leak_or_main_break")
    assert final_candidate["localization_grade"] == "L5"
    assert final_candidate["exact_failure_claim"] is True
    assert [event["to_grade"] for event in final_candidate["promotion_history"]] == ["L4", "L5"]
    assert plane.store.read("assessments")[0]["candidates"][0]["localization_grade"] != "L5"
    assert all(event["control_action_authorized"] is False for event in final["promotion_events"])


def test_public_view_redacts_restricted_control_asset_and_operator_is_gated(tmp_path):
    plane, assessment, _ = build_plane(tmp_path, "pump_failure")
    candidate = candidate_for(assessment, "pump_failure")
    public = plane.current_assessment(assessment["assessment_id"], view_mode="public")
    public_candidate = candidate_for(public, "pump_failure")
    assert public_candidate["target_asset_ids"] != candidate["target_asset_ids"]
    assert public_candidate["public_redaction"]["exact_operator_details_withheld"] is True
    with pytest.raises(PermissionError, match="operator_view_disabled"):
        plane.current_assessment(assessment["assessment_id"], view_mode="operator")

    operator_plane, operator_assessment, _ = build_plane(
        tmp_path / "operator", "pump_failure", operator=True
    )
    operator_candidate = candidate_for(
        operator_plane.current_assessment(
            operator_assessment["assessment_id"], view_mode="operator"
        ),
        "pump_failure",
    )
    assert operator_candidate["target_asset_ids"] == ["AYL_PUMP_EAST"]


def test_assessment_replay_is_deterministic_and_control_actions_remain_disabled(tmp_path):
    fixture = load_fixture()
    plane, first, _ = build_plane(tmp_path, "known_break")
    replay = plane.assess(
        as_of=fixture["as_of"], system_id="SYS_EAST", idempotency_key="assess:known_break"
    )
    assert replay["assessment_id"] == first["assessment_id"]
    assert replay["automatic_control_actions"] is False
    assert replay["notifications_enabled"] is False
    assert replay["production_promotion_enabled"] is False
