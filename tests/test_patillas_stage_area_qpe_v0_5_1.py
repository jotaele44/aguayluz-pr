from pathlib import Path

import pytest

from research.resource_balance.pilots.patillas_guayama_v0_5_1 import (
    load_json,
    qpe_volume_from_fragments,
    replay_public_sample,
    require_stage_geometry,
    stage_area_m2,
    verify_frozen_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "research/resource_balance/pilots/patillas_guayama_v0_5_1"


def test_stage_area_model_is_monotone_and_top_shoreline_bound() -> None:
    model = load_json(PILOT / "stage_area_model.json")
    points = [p for p in model["points"] if p["area_m2"] is not None]
    areas = [p["area_m2"] for p in points]
    assert areas == sorted(areas)
    assert stage_area_m2(67.55, model) == pytest.approx(1203713.9819335968)
    assert model["shoreline_crosscheck"]["relative_difference_percent"] < 0.5


def test_plateau_and_extrapolation_fail_closed() -> None:
    model = load_json(PILOT / "stage_area_model.json")
    with pytest.raises(ValueError, match="plateau"):
        stage_area_m2(45.0, model)
    with pytest.raises(ValueError, match="out_of_range"):
        stage_area_m2(68.0, model)


def test_frozen_noaa_bytes_cross_bind() -> None:
    receipt = load_json(PILOT / "noaa_stageiv_pr_20260808T000000Z.receipt.json")
    raw = verify_frozen_bytes(PILOT / "noaa_stageiv_pr_20260808T000000Z.tif", receipt)
    assert len(raw) == 5882
    assert receipt["bytes"]["sha256"] == "56aaa69d6d1e4ef33aac4e4c4c5ec4a2e24a7d2d9cd5f30b22805caa243d06f1"


def test_public_byte_replay_matches_frozen_geometry_but_is_not_admitted() -> None:
    fixture = load_json(PILOT / "qpe_replay_fixture.json")["public_byte_replay"]
    result = replay_public_sample(PILOT)
    assert result["precipitation_volume_m3"] == pytest.approx(fixture["expected_precipitation_volume_m3"], abs=1e-9)
    assert result["area_weighted_depth_m"] == pytest.approx(fixture["expected_area_weighted_depth_m"], abs=1e-12)
    assert result["status"] == "computed_not_admitted"
    assert result["admission_status"] == "blocked_qpe_uncertainty_unknown"
    assert result["real_balance_executed"] is False


def test_nodata_and_area_mismatch_reject() -> None:
    with pytest.raises(ValueError, match="qpe_nodata"):
        qpe_volume_from_fragments([{"depth_in": -3.4028234663852886e38, "intersection_area_m2": 10.0}], 10.0, qpe_uncertainty_fraction=0.2)
    with pytest.raises(ValueError, match="geometry_area_mismatch"):
        qpe_volume_from_fragments([{"depth_in": 0.1, "intersection_area_m2": 9.0}], 10.0, qpe_uncertainty_fraction=0.2)


def test_lower_stage_requires_stage_specific_geometry() -> None:
    with pytest.raises(ValueError, match="stage_specific_geometry_required"):
        require_stage_geometry(60.55, None)


def test_synthetic_transform_with_numeric_uncertainty_is_not_balance() -> None:
    fixture = load_json(PILOT / "qpe_replay_fixture.json")["synthetic_replay"]
    result = qpe_volume_from_fragments(fixture["cells"], fixture["geometry_area_m2"], qpe_uncertainty_fraction=fixture["qpe_uncertainty_fraction"])
    assert result["status"] == "transform_only_not_balance"
    assert result["qpe_uncertainty_m3"] is not None
    assert result["real_balance_executed"] is False
