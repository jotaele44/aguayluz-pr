from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research.resource_balance.pilots.patillas_guayama_v0_3 import (
    admit_balance_window,
    load_admission_scenarios,
    load_json,
    rate_to_interval_volume,
    real_window_readiness,
    run_complete_synthetic_window,
    stage_to_storage,
    validate_stage_storage_model,
    verify_receipt_payload,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "research/resource_balance/pilots/patillas_guayama_v0_3"


def fixture_map() -> dict[str, dict]:
    payload = load_admission_scenarios(PILOT / "admission_fixtures.json")
    return {item["scenario_id"]: item for item in payload}


def test_evidence_manifest_matches_committed_fixture_bytes() -> None:
    manifest = load_json(PILOT / "evidence_manifest.json")
    assert manifest["pinned_main_sha"] == "17c843595b5cdfbcef4e5f7b1ac6c662092e335d"
    assert manifest["pinned_parent_head"] == "40fc362d7cb11cdabe3cde04733b41ceac97eb77"
    for entry in manifest["entries"]:
        raw = (PILOT / entry["path"]).read_bytes()
        assert len(raw) == entry["size_bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_authoritative_source_receipt_is_hash_bound() -> None:
    receipt = load_json(PILOT / "authoritative_source_receipt.json")
    assert verify_receipt_payload(receipt) is True
    assert receipt["report"]["doi"] == "10.3133/sim3471"
    assert receipt["data_release"]["doi"] == "10.5066/P9Y2SCY1"
    assert receipt["capture_state"] == "authoritative_source_identified_table_bytes_not_materialized"


def test_real_stage_storage_model_is_identified_but_not_materialized() -> None:
    model = load_json(PILOT / "lago_patillas_stage_storage_model.json")
    errors = validate_stage_storage_model(model)
    assert "stage_storage_table_not_materialized" in errors
    assert model["datum"] == "PRVD02"
    assert model["anchors"] == [
        {
            "stage_m_prvd02": 67.55,
            "storage_m3": 12960000.0,
            "anchor_kind": "spillway_capacity",
        }
    ]
    assert model["eligible_for_real_balance"] is False


def test_stage_to_storage_interpolates_and_never_extrapolates() -> None:
    model = load_json(PILOT / "synthetic_stage_storage_model.json")
    result = stage_to_storage(
        60.5,
        model,
        observed_datum="PRVD02",
        source_hash="a" * 64,
        allow_synthetic=True,
    )
    assert result["storage_m3"] == 5500000.0
    assert result["receipt"]["interpolated"] is True
    assert result["receipt"]["extrapolated"] is False
    assert result["receipt"]["claim_status"] == "derived"
    with pytest.raises(ValueError, match="stage_out_of_model_range"):
        stage_to_storage(
            63.0,
            model,
            observed_datum="PRVD02",
            source_hash="a" * 64,
            allow_synthetic=True,
        )
    with pytest.raises(ValueError, match="stage_datum_mismatch"):
        stage_to_storage(
            60.5,
            model,
            observed_datum="mean_sea_level",
            source_hash="a" * 64,
            allow_synthetic=True,
        )


def test_rate_to_interval_volume_is_replayable_in_m3() -> None:
    result = rate_to_interval_volume(
        1.0,
        "m3/s",
        "2026-07-28T00:00:00-04:00",
        "2026-07-29T00:00:00-04:00",
        uncertainty_abs_rate=0.01,
        source_hash="b" * 64,
    )
    assert result["volume_m3"] == 86400.0
    assert result["uncertainty_abs_m3"] == 864.0
    assert result["receipt"]["duration_seconds"] == 86400.0
    assert result["receipt"]["output"]["unit"] == "m3"
    with pytest.raises(ValueError, match="unsupported_rate_unit"):
        rate_to_interval_volume(
            1,
            "MGD",
            "2026-07-28T00:00:00-04:00",
            "2026-07-29T00:00:00-04:00",
            uncertainty_abs_rate=0,
            source_hash="b" * 64,
        )


@pytest.mark.parametrize(
    ("scenario_id", "expected_error"),
    [
        ("missing_treatment", "missing:direct_treatment_withdrawal_rate"),
        ("partial_window", "missing:canal_operational_loss_volume"),
        ("stale_window", "window_stale"),
        ("revised_observation", "revision_not_current:direct_treatment_withdrawal_rate"),
        ("contradictory_duplicate", "contradictory_duplicate:downstream_flow_rate"),
        ("datum_mismatch", "datum_mismatch:reservoir_stage_end"),
        ("stage_out_of_range", "stage_out_of_range:reservoir_stage_end"),
        ("sensor_drift", "sensor_not_verified:upstream_inflow_rate"),
    ],
)
def test_negative_admission_fixtures_fail_closed(
    scenario_id: str, expected_error: str
) -> None:
    scenarios = fixture_map()
    policy = load_json(PILOT / "admission_policy.json")
    model = load_json(PILOT / "synthetic_stage_storage_model.json")
    result = admit_balance_window(scenarios[scenario_id], policy, model)
    assert result["status"] == "rejected"
    assert expected_error in result["errors"]
    assert result["root_cause_claim"] is None


def test_complete_synthetic_window_closes_nested_balances() -> None:
    result = run_complete_synthetic_window(PILOT)
    assert result["admission"]["status"] == "admitted"
    assert result["storage_change_m3"] == pytest.approx(300000.0)
    assert result["reservoir_balance"]["status"] == "balanced"
    assert result["reservoir_balance"]["residual"] == pytest.approx(0.0, abs=1e-8)
    assert result["canal_balance"]["status"] == "balanced"
    assert result["canal_balance"]["residual"] == pytest.approx(0.0, abs=1e-8)
    assert result["root_cause_claim"] is None
    assert result["inference"] == "The proof does not establish a real Lago Patillas balance."
    assert len(result["transform_receipts"]) == 6
    assert all(
        receipt["claim_status"] == "derived"
        for receipt in result["transform_receipts"].values()
    )


def test_real_window_is_not_executed_without_every_required_input() -> None:
    readiness = real_window_readiness(PILOT)
    assert readiness["status"] == "blocked"
    assert readiness["real_balance_executed"] is False
    assert "stage_storage_table_not_materialized" in readiness["blockers"]
    assert "missing_synchronized_T1_direct_treatment_withdrawal" in readiness["blockers"]
    assert readiness["root_cause_claim"] is None


def test_activation_surfaces_remain_disabled() -> None:
    policy = load_json(PILOT / "admission_policy.json")
    assert policy["pinned_parent_head"] == "40fc362d7cb11cdabe3cde04733b41ceac97eb77"
    assert all(value is False for value in policy["activation"].values())
