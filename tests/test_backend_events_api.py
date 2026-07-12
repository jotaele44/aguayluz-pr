"""Tests for the GET /events endpoint's default bounding + pagination.

The service_events corpus carries the full EPA SDWIS violation history (tens of
thousands of rows), so a bare /events must NOT dump the whole corpus on a normal
dashboard load. These tests assert the default page size, the true `total`, the
recent-first ordering, and the explicit-limit overrides. Skipped when
fastapi/httpx aren't installed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.main as backend  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    # 1200 synthetic events with ascending timestamps (2020-01-01 .. onward), so
    # the newest is the last one inserted — lets us assert recent-first ordering.
    events = [
        {
            "event_id": f"EVT_{i:05d}",
            "event_type": "water_quality_violation",
            "start_time": f"2020-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00",
            "affected_area": "PR",
        }
        for i in range(1200)
    ]
    monkeypatch.setattr(backend, "_events", events)
    with TestClient(backend.app) as c:
        yield c


def test_default_limit_bounds_response(client):
    r = client.get("/events")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1200  # true corpus size still reported
    assert len(body["items"]) == backend.DEFAULT_EVENTS_LIMIT  # bounded page


def test_default_is_recent_first(client):
    body = client.get("/events").json()
    # Newest synthetic event (highest index) must come first.
    assert body["items"][0]["event_id"] == "EVT_01199"
    starts = [e["start_time"] for e in body["items"]]
    assert starts == sorted(starts, reverse=True)


def test_explicit_limit_is_honored(client):
    body = client.get("/events", params={"limit": 10}).json()
    assert len(body["items"]) == 10
    assert body["total"] == 1200


def test_negative_limit_returns_all(client):
    body = client.get("/events", params={"limit": -1}).json()
    assert len(body["items"]) == 1200


def test_offset_paginates(client):
    first = client.get("/events", params={"limit": 100}).json()
    second = client.get("/events", params={"limit": 100, "offset": 100}).json()
    assert first["items"][0]["event_id"] != second["items"][0]["event_id"]
    assert len({e["event_id"] for e in first["items"] + second["items"]}) == 200
