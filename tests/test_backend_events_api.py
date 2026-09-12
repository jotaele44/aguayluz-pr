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


def test_event_density_closes_arithmetic_and_preserves_unresolved(monkeypatch):
    monkeypatch.setattr(
        backend,
        "_events",
        [
            {
                "event_id": "matched",
                "municipality": "San Juan",
                "start_time": "2026-09-01T00:00:00Z",
            },
            {
                "event_id": "unknown",
                "municipality": "Unknown Place",
                "start_time": "2026-09-02T00:00:00Z",
            },
            {
                "event_id": "missing",
                "municipality": None,
                "start_time": "2026-09-03T00:00:00Z",
            },
        ],
    )

    with TestClient(backend.app) as test_client:
        body = test_client.get("/municipios/event_density").json()

    assert body["by_geoid"] == {"72127": 1}
    assert body["matched_count"] == 1
    assert body["unresolved_count"] == 2
    assert body["unresolved_by_name"] == {"Unknown Place": 1, "__NULL__": 1}
    assert body["matched_count"] + body["unresolved_count"] == body["total_events"] == 3
    assert body["scope"] == {
        "aggregation_key": "event.municipality exact source string",
        "normalization": "NONE",
        "identity_effect": "NONE",
        "geometry_effect": "NONE",
        "state": "CANDIDATE_NOT_IDENTITY",
    }
    assert all(source["sha256"] for source in body["provenance"]["event_sources"])
    assert body["provenance"]["municipio_source"]["row_count"] == 78


@pytest.mark.parametrize(
    ("query", "detail"),
    [
        ("since=bad", "since must be an ISO-8601 timestamp"),
        (
            "since=2026-09-03T00:00:00Z&until=2026-09-01T00:00:00Z",
            "since must not be after until",
        ),
    ],
)
def test_event_density_rejects_invalid_time_windows(client, query, detail):
    response = client.get(f"/municipios/event_density?{query}")

    assert response.status_code == 400
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "features",
    [
        [
            {"properties": {"name": "A", "geoid": "1"}},
            {"properties": {"name": "A", "geoid": "2"}},
        ],
        [
            {"properties": {"name": "A", "geoid": "1"}},
            {"properties": {"name": "B", "geoid": "1"}},
        ],
    ],
)
def test_municipio_index_rejects_duplicate_names_and_geoids(features):
    with pytest.raises(ValueError):
        backend._build_municipio_geoid_index({"features": features})
