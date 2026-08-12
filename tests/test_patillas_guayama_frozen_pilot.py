from __future__ import annotations

import copy
from pathlib import Path

import pytest

from research.resource_balance.pilots.patillas_guayama_v0_2 import (
    STATUS_EQUIVALENCE,
    apply_sensor_bias,
    compare_legacy_and_shared,
    frozen_observation_status,
    legacy_laguna_balance,
    load_json,
    parse_time,
    real_baseline_result,
    shared_balance_from_legacy,
    validate_topology,
    verify_source_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "research/resource_balance/pilots/patillas_guayama_v0_2"


def scenarios() -> dict[str, dict]:
    payload = load_json(PILOT / "scenario_fixtures.json")
    return {item["scenario_id"]: item for item in payload["scenarios"]}


def test_source_manifest_hashes_and_pinned_main() -> None:
    assert verify_source_manifest(PILOT) == []
    manifest = load_json(PILOT / "source_manifest.json")
    assert manifest["pinned_main_sha"] == "17c843595b5cdfbcef4e5f7b1ac6c662092e335d"
    assert len(manifest["entries"]) == 7
    assert all(item["capture_kind"] == "canonical_extract" for item in manifest["entries"])


def test_real_baseline_fails_closed_without_root_cause() -> None:
    result = real_baseline_result(PILOT)
    assert result["balance_result"]["status"] == "insufficient_data"
    assert result["balance_result"]["attribution"]["cause"] == "unresolved"
    assert result["balance_result"]["attribution"]["claim_status"] == "unresolved"
    assert result["eligibility"]["root_cause_claim"] is None
    assert "storage_change" in result["eligibility"]["missing_required_quantities"]
    assert result["topology_errors"] == []


def test_real_observations_are_provisional_context_only() -> None:
    frozen = load_json(PILOT / "frozen_observations.json")
    assert frozen["adjudication"] == "real_provisional_context_only"
    assert all(item["eligible_for_balance"] is False for item in frozen["observations"])
    assert all(item["role"] == "context" for item in frozen["observations"])
    status = frozen_observation_status(frozen["observations"])
    assert status["status"] == "insufficient_data"
    assert status["max_skew_hours"] > 24


@pytest.mark.parametrize(
    ("scenario_id", "legacy_status", "shared_status", "residual"),
    [
        ("positive_control_balanced", "balanced_within_tolerance", "balanced", 0.0),
        ("within_uncertainty", "balanced_within_tolerance", "within_uncertainty", 5.0),
        ("unaccounted_deficit", "unexplained_positive_residual", "unaccounted_deficit", 20.0),
        ("unaccounted_surplus", "contradictory_negative_residual", "unaccounted_surplus", -20.0),
    ],
)
def test_legacy_and_shared_numeric_equivalence(
    scenario_id: str, legacy_status: str, shared_status: str, residual: float
) -> None:
    comparison = compare_legacy_and_shared(scenarios()[scenario_id])
    assert comparison["equivalent"] is True
    assert comparison["legacy"]["status"] == legacy_status
    assert comparison["shared"]["status"] == shared_status
    assert comparison["legacy"]["residual"] == residual
    assert comparison["shared"]["residual"] == residual
    assert comparison["legacy"]["root_cause_claim"] is None
    assert comparison["shared"]["attribution"]["cause"] == "unresolved"


def test_missing_metric_maps_to_insufficient_data() -> None:
    scenario = scenarios()["missing_treatment"]
    comparison = compare_legacy_and_shared(scenario)
    assert comparison["legacy"]["status"] == "incomplete"
    assert comparison["shared"]["status"] == "insufficient_data"
    assert comparison["equivalent"] is True


def test_mixed_units_fail_closed_in_both_paths() -> None:
    comparison = compare_legacy_and_shared(scenarios()["mixed_unit"])
    assert comparison["legacy"]["status"] == "mixed_or_unsupported_units"
    assert "one canonical unit" in comparison["shared_error"]
    assert comparison["equivalent"] is True


def test_stale_scenario_is_not_balance_eligible() -> None:
    scenario = scenarios()["stale_window"]
    times = [parse_time(item["observed_at"]) for item in scenario["values"].values()]
    reference = parse_time("2026-07-28T00:00:00-04:00")
    assert all((reference - item).total_seconds() > 36 * 3600 for item in times)
    result = shared_balance_from_legacy({}, scenario["scenario_id"])
    assert result["status"] == "insufficient_data"


def test_topology_cycle_is_detected() -> None:
    topology = load_json(PILOT / "topology_state.json")
    mutation = scenarios()["topology_contradiction"]["topology_mutation"]["add_edge"]
    broken = copy.deepcopy(topology)
    broken["edges"].append(mutation)
    errors = validate_topology(broken)
    assert any(item.startswith("cycle:") for item in errors)


def test_sensor_bias_is_inference_and_changes_numeric_result() -> None:
    scenario = scenarios()["sensor_bias"]
    uncorrected = legacy_laguna_balance(scenario["values"])
    corrected_values = apply_sensor_bias(
        scenario["values"], scenario["bias"]["metric"], scenario["bias"]["additive_correction"]
    )
    corrected = legacy_laguna_balance(corrected_values)
    assert uncorrected["residual"] == 5.0
    assert corrected["residual"] == 0.0
    correction = corrected_values["canal_release"]["bias_correction"]
    assert correction["claim_status"] == "inference"
    assert correction["requires_calibration_evidence"] is True


def test_hierarchical_boundaries_cover_required_levels() -> None:
    topology = load_json(PILOT / "topology_state.json")
    kinds = {item["boundary_kind"] for item in topology["boundaries"]}
    assert {"system", "watershed", "reservoir", "treatment", "distribution"} <= kinds
    by_id = {item["boundary_id"]: item for item in topology["boundaries"]}
    assert by_id["boundary:patillas:reservoir"]["upstream_boundary_id"] == "boundary:patillas:watershed"
    assert by_id["boundary:guayama:treatment"]["upstream_boundary_id"] == "boundary:patillas:reservoir"
    assert by_id["boundary:guayama:distribution-and-intakes"]["upstream_boundary_id"] == "boundary:guayama:treatment"


def test_expected_loss_model_is_explicitly_unavailable() -> None:
    model = load_json(PILOT / "expected_loss_model.json")
    assert model["status"] == "not_validated"
    assert model["eligible_for_balance"] is False
    assert model["amount"] is None


def test_status_mapping_is_explicit_and_no_unauthorized_activity_claims() -> None:
    assert STATUS_EQUIVALENCE["unexplained_positive_residual"] == {"unaccounted_deficit"}
    scenario = scenarios()["unaccounted_deficit"]
    shared = compare_legacy_and_shared(scenario)["shared"]
    notes = " ".join(shared["attribution"]["notes"]).lower()
    assert "unauthorized use" in notes
    assert shared["attribution"]["confidence"] == 0
