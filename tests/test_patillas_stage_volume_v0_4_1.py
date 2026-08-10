from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research.resource_balance.pilots.patillas_guayama_v0_4_1 import (
    load_json,
    real_window_readiness,
    stage_to_storage,
    validate_stage_storage_model,
    verify_evidence_package,
    verify_receipt_payload,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "research/resource_balance/pilots/patillas_guayama_v0_4_1"


def model() -> dict:
    return load_json(PACKAGE / "lago_patillas_stage_storage_model.json")


def test_permanent_evidence_package_cross_binds() -> None:
    assert verify_evidence_package(PACKAGE) == []
    receipt = load_json(PACKAGE / "source_receipt.json")
    assert verify_receipt_payload(receipt) is True
    assert receipt["archive"]["size_bytes"] == 27_171_688
    assert receipt["archive"]["observed_md5"] == "562ed7f0458a5c84b379963a90b9c8d1"
    assert receipt["archive"]["sha256"] == (
        "3beac301b1521a197837ebb49eff701e2774385cb34f220e3546c82c5d732ea7"
    )
    assert receipt["row_count"] == 24
    assert receipt["parse_method"].endswith("no_OCR_no_manual_transcription")


def test_table_preserves_all_24_published_rows_in_source_order() -> None:
    raw = (PACKAGE / "source/Patillas2019_volume.source_order.csv").read_text()
    lines = raw.splitlines()
    assert len(lines) == 25
    assert lines[1] == "1,67.55,12.96"
    assert lines[-2:] == ["23,45.55,0.00", "24,44.55,0.00"]
    parsed = load_json(PACKAGE / "patillas_stage_volume_table.json")
    assert parsed["source_row_count"] == 24
    assert parsed["points"][0]["stage_m_prvd02"] == 44.55
    assert parsed["points"][-1] == {
        "source_fid": 1,
        "source_storage_mcm": "12.96",
        "stage_m_prvd02": 67.55,
        "storage_m3": 12_960_000,
    }


def test_materialized_model_accepts_declared_plateau_only() -> None:
    current = model()
    assert validate_stage_storage_model(current) == []
    assert current["status"] == (
        "materialized_authoritative_with_declared_precision_plateau"
    )
    assert current["eligible_for_real_balance"] is False


def test_datum_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="stage_datum_mismatch"):
        stage_to_storage(
            60.0,
            model(),
            observed_datum="mean_sea_level",
            observation_source_sha256="a" * 64,
        )


def test_truncated_table_is_rejected() -> None:
    changed = copy.deepcopy(model())
    changed["points"] = changed["points"][:-1]
    assert "truncated_or_extended_table" in validate_stage_storage_model(changed)


def test_duplicate_stage_is_rejected() -> None:
    changed = copy.deepcopy(model())
    changed["points"][2]["stage_m_prvd02"] = changed["points"][1]["stage_m_prvd02"]
    assert "duplicate_or_decreasing_stage" in validate_stage_storage_model(changed)


def test_decreasing_storage_is_rejected() -> None:
    changed = copy.deepcopy(model())
    changed["points"][3]["storage_m3"] = 100_000
    assert "decreasing_storage" in validate_stage_storage_model(changed)


def test_anchor_mismatch_is_rejected() -> None:
    changed = copy.deepcopy(model())
    changed["anchor"]["storage_m3"] = 12_950_000
    assert "anchor_mismatch" in validate_stage_storage_model(changed)


def test_plateau_is_preserved_and_interpolation_is_prohibited() -> None:
    current = model()
    at_lower = stage_to_storage(
        44.55,
        current,
        observed_datum="PRVD02",
        observation_source_sha256="b" * 64,
    )
    at_upper = stage_to_storage(
        45.55,
        current,
        observed_datum="PRVD02",
        observation_source_sha256="b" * 64,
    )
    assert at_lower["storage_m3"] == 0
    assert at_upper["storage_m3"] == 0
    with pytest.raises(
        ValueError,
        match="published_precision_plateau_interpolation_prohibited",
    ):
        stage_to_storage(
            45.0,
            current,
            observed_datum="PRVD02",
            observation_source_sha256="b" * 64,
        )


def test_out_of_range_stage_is_rejected() -> None:
    with pytest.raises(ValueError, match="stage_out_of_model_range"):
        stage_to_storage(
            68.0,
            model(),
            observed_datum="PRVD02",
            observation_source_sha256="c" * 64,
        )


def test_replay_is_deterministic_between_valid_adjacent_points() -> None:
    kwargs = {
        "stage_m_prvd02": 60.05,
        "model": model(),
        "observed_datum": "PRVD02",
        "observation_source_sha256": "d" * 64,
    }
    first = stage_to_storage(**kwargs)
    second = stage_to_storage(**kwargs)
    assert first == second
    assert first["receipt"]["interpolated"] is True
    assert first["receipt"]["extrapolated"] is False
    encoded = json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == hashlib.sha256(encoded).hexdigest()


def test_real_window_remains_blocked_and_activation_is_false() -> None:
    readiness = real_window_readiness(PACKAGE)
    assert readiness["status"] == "blocked"
    assert readiness["stage_storage_table_materialized"] is True
    assert readiness["stage_storage_verification_errors"] == []
    assert readiness["real_balance_executed"] is False
    assert readiness["root_cause_claim"] is None
    assert all(value is False for value in readiness["activation"].values())
