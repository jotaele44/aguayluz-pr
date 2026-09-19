"""Regression tests for the MiLUMA regional aggregate API."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.main as backend  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

def test_luma_regions_endpoint_closes_arithmetic_and_preserves_scope(monkeypatch):
    rows = [
        {
            "status_id": "AYL_LUMA_REGION_20260919T060000Z_SAN_JUAN",
            "region_raw": "SAN JUAN",
            "region_normalized": "SAN JUAN",
            "total_customers": 1000,
            "affected_customers": 25,
            "affected_pct": 2.5,
            "observed_at": "2026-09-19T06:00:00Z",
            "source_ref": "https://example.test/regions",
            "source_hash": "a" * 64,
            "evidence_tier": "T2",
            "confidence": 80,
            "review_status": "needs_review",
        },
        {
            "status_id": "AYL_LUMA_REGION_20260919T060000Z_PONCE",
            "region_raw": "PONCE",
            "region_normalized": "PONCE",
            "total_customers": 500,
            "affected_customers": 5,
            "affected_pct": 1.0,
            "observed_at": "2026-09-19T06:00:00Z",
            "source_ref": "https://example.test/regions",
            "source_hash": "a" * 64,
            "evidence_tier": "T2",
            "confidence": 80,
            "review_status": "needs_review",
        },
    ]
    monkeypatch.setattr(backend, "_luma_region_status", rows)

    with TestClient(backend.app) as client:
        body = client.get("/outages/regions").json()

    assert body["total"] == 2
    assert body["observed_at"] == "2026-09-19T06:00:00Z"
    assert body["snapshot_consistent"] is True
    assert body["totals"] == {
        "customers": 1500,
        "affected": 30,
        "affected_pct": 2.0,
    }
    assert body["arithmetic_closed"] is True
    assert body["freshness"]["current_state_max_age_seconds"] == 3600
    assert "not a MiLUMA publication SLA" in body["freshness"]["policy_basis"]
    assert body["scope"] == {
        "record_class": "regional_aggregate_snapshot",
        "event_identity_effect": "NONE",
        "normalization_identity_effect": "NONE",
    }
    assert [row["region_raw"] for row in body["items"]] == ["SAN JUAN", "PONCE"]

def test_luma_regions_endpoint_surfaces_mixed_snapshot_times(monkeypatch):
    rows = [
        {
            "total_customers": 10,
            "affected_customers": 1,
            "observed_at": "2026-09-19T06:00:00Z",
        },
        {
            "total_customers": 10,
            "affected_customers": 2,
            "observed_at": "2026-09-19T06:01:00Z",
        },
    ]
    monkeypatch.setattr(backend, "_luma_region_status", rows)

    with TestClient(backend.app) as client:
        body = client.get("/outages/regions").json()

    assert body["snapshot_consistent"] is False
    assert body["observed_at"] is None
    assert body["totals"]["customers"] == 20
    assert body["totals"]["affected"] == 3

def test_luma_regions_old_snapshot_is_not_current_state_eligible(monkeypatch):
    monkeypatch.setattr(
        backend,
        "_luma_region_status",
        [
            {
                "total_customers": 100,
                "affected_customers": 1,
                "observed_at": "2025-03-03T01:38:40Z",
            }
        ],
    )

    with TestClient(backend.app) as client:
        body = client.get("/outages/regions").json()

    assert body["snapshot_consistent"] is True
    assert body["arithmetic_closed"] is True
    assert body["freshness"]["current_state_eligible"] is False
    assert body["freshness"]["snapshot_age_seconds"] > 3600


def test_runtime_luma_event_filter_excludes_stale_future_and_invalid_rows():
    now = datetime(2026, 9, 19, 6, 30, tzinfo=timezone.utc)
    rows = [
        {"event_id": "current", "start_time": "2026-09-19T06:00:00Z"},
        {"event_id": "stale", "start_time": "2026-09-19T05:00:00Z"},
        {"event_id": "future", "start_time": "2026-09-19T06:31:00Z"},
        {"event_id": "invalid", "start_time": "not-a-time"},
    ]

    kept = backend._current_luma_event_rows(rows, now=now)

    assert [row["event_id"] for row in kept] == ["current"]
