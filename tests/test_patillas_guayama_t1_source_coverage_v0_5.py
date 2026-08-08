from pathlib import Path

import pytest

from research.resource_balance.pilots.patillas_guayama_v0_5 import (
    admit_slice,
    load_json,
    load_scenarios,
    real_window_readiness,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "research/resource_balance/pilots/patillas_guayama_v0_5"


def _scenarios() -> dict[str, dict]:
    rows = load_scenarios(PILOT / "admission_fixtures.json")
    return {row["scenario_id"]: row for row in rows}


def test_complete_synthetic_t1_slice_is_admitted_but_not_executed() -> None:
    policy = load_json(PILOT / "admission_policy.json")
    result = admit_slice(_scenarios()["complete_t1_slice"], policy)
    assert result["status"] == "admitted"
    assert result["errors"] == []
    assert result["real_balance_executed"] is False
    assert result["root_cause_claim"] is None


@pytest.mark.parametrize(
    ("scenario_id", "expected_error"),
    [
        ("missing_input", "missing:direct_treatment_withdrawal_rate"),
        ("missing_rio_marin", "missing:rio_marin_inflow_rate"),
        ("missing_river_outlet", "missing:downstream_river_release_rate"),
        ("asynchronous_input", "interval_alignment:downstream_terminal_flow_rate"),
        ("provisional_input", "provisional:rio_grande_inflow_rate"),
        ("superseded_input", "revision:gate_or_canal_release_rate"),
        ("calibration_unknown", "calibration:direct_treatment_withdrawal_rate"),
        ("uncertainty_unknown", "uncertainty:evaporation_volume"),
        ("topology_contradictory", "topology:downstream_river_release_rate"),
        ("proxy_only_input", "source_classification:gate_or_canal_release_rate"),
        ("datum_mismatch", "stage_reference:reservoir_stage_end"),
    ],
)
def test_negative_synthetic_t1_fixtures_fail_closed(
    scenario_id: str, expected_error: str
) -> None:
    policy = load_json(PILOT / "admission_policy.json")
    result = admit_slice(_scenarios()[scenario_id], policy)
    assert result["status"] == "rejected"
    assert expected_error in result["errors"]
    assert result["real_balance_executed"] is False
    assert result["root_cause_claim"] is None


def test_public_source_matrix_keeps_real_window_blocked() -> None:
    readiness = real_window_readiness(PILOT)
    assert readiness["status"] == "blocked"
    assert readiness["real_balance_executed"] is False
    assert readiness["operator_requests_sent"] is False
    assert "upstream_inflow_rate" in readiness["blocking_metrics"]
    assert "downstream_river_release_rate" in readiness["blocking_metrics"]
    assert "direct_treatment_withdrawal_rate" in readiness["blocking_metrics"]
    assert "evaporation_volume" in readiness["blocking_metrics"]
    assert "documented_operational_loss_volume" in readiness["blocking_metrics"]


def test_expanded_public_sweep_sources_are_preserved() -> None:
    receipts = load_json(PILOT / "public_source_receipts.json")
    source_ids = {row["source_id"] for row in receipts["sources"]}
    assert "USGS-50093000" in source_ids
    assert "USGS-50093120" in source_ids
    assert "USGS-50093115" in source_ids
    assert "NOAA-STAGE-IV-PR" in source_ids
    assert "DRNA-CANAL-PATILLAS" in source_ids
    assert receipts["operator_requests_sent"] is False
    assert receipts["real_balance_executed"] is False


def test_activation_flags_are_all_disabled() -> None:
    policy = load_json(PILOT / "admission_policy.json")
    assert all(value is False for value in policy["activation"].values())
