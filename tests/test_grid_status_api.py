"""Adversarial grid-status semantics: a missing value is never zero."""
from datetime import datetime, timedelta, timezone

from server.backend.grid_status_api import build_grid_status

NOW = datetime(2026, 11, 13, 18, tzinfo=timezone.utc)


def test_empty_source_is_unavailable_and_all_measures_unknown():
    result = build_grid_status([], now=NOW)
    assert result["status"] == "SOURCE_UNAVAILABLE"
    assert all(value is None for value in result["measurements"].values())
    assert result["source"]["verified_current"] is False


def test_current_raw_snapshot_is_not_live_verified():
    row = {"snapshot_ts": NOW.isoformat(), "payload_sha256": "a"*64,
           "raw_payload": {"customers_without_service": 0}}
    result = build_grid_status([row], now=NOW)
    assert result["status"] == "UNVERIFIED"
    assert result["source"]["payload_sha256"] == "a"*64
    assert result["measurements"]["customers_without_service"] is None


def test_old_snapshot_is_stale():
    row = {"snapshot_ts": (NOW - timedelta(hours=2)).isoformat(), "payload_sha256": "b"*64}
    result = build_grid_status([row], now=NOW)
    assert result["status"] == "STALE"
    assert result["source"]["age_seconds"] == 7200


def test_future_and_invalid_timestamps_are_not_current():
    rows = [{"snapshot_ts": (NOW+timedelta(days=1)).isoformat()},
            {"snapshot_ts": "not-a-date"}]
    result = build_grid_status(rows, now=NOW)
    assert result["status"] == "UNVERIFIED"
    assert result["source"]["observation_at"] is None


def test_latest_valid_evidence_wins_without_restoration_inference():
    rows = [{"snapshot_ts": (NOW-timedelta(hours=3)).isoformat(), "payload_sha256": "a"*64},
            {"snapshot_ts": (NOW-timedelta(minutes=10)).isoformat(), "payload_sha256": "c"*64}]
    result = build_grid_status(rows, now=NOW)
    assert result["source"]["payload_sha256"] == "c"*64
    assert "restoration" in " ".join(result["limitations"]).lower()
    assert not result["release_certified"]


def test_naive_now_fails():
    import pytest
    with pytest.raises(ValueError):
        build_grid_status([], now=datetime(2026, 11, 13))
