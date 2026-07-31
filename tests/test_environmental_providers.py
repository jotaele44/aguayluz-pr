from __future__ import annotations

from fastapi.testclient import TestClient

from server.backend.app import app
from server.backend.environmental_providers import (
    NEON_PR_SITES,
    PROVIDERS,
    poll_provider,
    provider_registry,
)

client = TestClient(app)


def test_registry_covers_authoritative_environmental_sources(monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    rows = provider_registry()
    assert {row["code"] for row in rows} == {
        "neon",
        "usgs",
        "nws",
        "nasa",
        "lter",
        "wqp",
        "drna",
    }
    assert all(row["tier"] == "T1" for row in rows)
    assert next(row for row in rows if row["code"] == "neon")["configured"] is False


def test_neon_registry_contains_four_puerto_rico_sites():
    assert {row["site_code"] for row in NEON_PR_SITES} == {
        "GUAN",
        "LAJA",
        "CUPE",
        "GUIL",
    }


def test_polling_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AGUAYLUZ_EXTERNAL_POLLING_ENABLED", raising=False)
    assert poll_provider("usgs")["status"] == "disabled"


def test_neon_token_is_never_returned(monkeypatch):
    monkeypatch.setenv("NEON_API_TOKEN", "sentinel-secret-value")
    monkeypatch.delenv("AGUAYLUZ_EXTERNAL_POLLING_ENABLED", raising=False)
    payload = poll_provider("neon")
    assert "sentinel-secret-value" not in repr(payload)
    assert "sentinel-secret-value" not in repr(provider_registry())


def test_provider_routes_are_read_only_without_live_opt_in(monkeypatch):
    monkeypatch.delenv("AGUAYLUZ_EXTERNAL_POLLING_ENABLED", raising=False)
    response = client.get("/environmental-providers")
    assert response.status_code == 200
    assert response.json()["total"] == len(PROVIDERS)
    health = client.get("/environmental-providers/health")
    assert health.status_code == 200
    assert health.json()["external_network_used"] is False


def test_unknown_provider_fails_closed():
    response = client.get("/environmental-providers/health?provider=bogus")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "unknown_environmental_provider"
