"""API regressions for preserved MiLUMA regional-status snapshots."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.main as backend  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    rows = [
        {
            "snapshot_id": "LUMA_REGIONS_2026-09-19T08:00:00Z_a",
            "snapshot_ts": "2026-09-19T08:00:00Z",
            "payload_sha256": "a" * 64,
            "raw_payload": [{"region": "A", "affected": 2}],
            "schema_state": "RAW_UNFROZEN",
        },
        {
            "snapshot_id": "LUMA_REGIONS_2026-09-19T09:00:00Z_b",
            "snapshot_ts": "2026-09-19T09:00:00Z",
            "payload_sha256": "b" * 64,
            "raw_payload": [{"region": "B", "affected": 1}],
            "schema_state": "RAW_UNFROZEN",
        },
    ]
    monkeypatch.setattr(backend, "_luma_status_snapshots", rows)
    return TestClient(backend.app)


def test_outages_status_returns_latest_without_schema_promotion(client):
    response = client.get("/outages/status?limit=1")
    assert response.status_code == 200
    doc = response.json()

    assert doc["total"] == 2
    assert doc["schema_state"] == "RAW_UNFROZEN"
    assert len(doc["items"]) == 1
    assert doc["latest"]["snapshot_ts"] == "2026-09-19T09:00:00Z"
    assert doc["latest"]["raw_payload"] == [{"region": "B", "affected": 1}]
    assert "municipality" not in doc["latest"]
    assert "restoration" not in doc["latest"]


def test_outages_status_limit_is_bounded(client):
    response = client.get("/outages/status?limit=0")
    assert response.status_code == 422
