"""NEON provider health probe.

The contract that matters: check_health NEVER raises. A provider outage must
degrade a refresh run to a warning, not abort it before the USGS/NOAA/EPA steps.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from aguayluz.neon import endpoints
from aguayluz.neon.client import NeonClient
from aguayluz.neon.health import check_health

BASE = endpoints.DEFAULT_BASE_URL
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sites_payload() -> dict:
    doc = json.loads((FIXTURES / "neon_sites_d04_sample.json").read_text())
    return {"data": doc["data"]}


def test_health_anonymous_is_reachable_not_authenticated(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(
        url=f"{BASE}/sites", json=_sites_payload(),
        headers={"X-RateLimit-Remaining": "198"},
    )
    rec = check_health()
    assert rec["provider"] == "NEON"
    assert rec["reachable"] is True
    # Anonymous access is expected and fine — the metadata endpoints are open.
    assert rec["authenticated"] is False
    assert rec["token_present"] is False
    assert rec["error"] is None
    assert rec["rate_limit_remaining"] == 198
    assert rec["pr_site_count"] == 4
    assert rec["api_version"] == "v0"
    assert isinstance(rec["latency_ms"], int)
    assert rec["checked_at"].endswith("Z")


def test_health_with_accepted_token_is_authenticated(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    monkeypatch.setenv("NEON_API_TOKEN", "good-token")
    httpx_mock.add_response(url=f"{BASE}/sites", json=_sites_payload())
    rec = check_health()
    assert rec["reachable"] is True
    assert rec["authenticated"] is True
    assert rec["token_present"] is True


def test_health_rejected_token_is_reachable_but_not_authenticated(httpx_mock, monkeypatch):
    """A bad token is reachable-but-broken, and must be distinguishable from anonymous."""
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    monkeypatch.setenv("NEON_API_TOKEN", "stale-token")
    httpx_mock.add_response(
        url=f"{BASE}/sites", status_code=403,
        json={"error": {"status": 403, "detail": "Access Denied"}, "data": None},
    )
    rec = check_health()
    assert rec["reachable"] is True
    assert rec["authenticated"] is False
    assert rec["token_present"] is True          # <- what separates it from anonymous
    assert "token rejected" in rec["error"]


def test_health_transport_failure_never_raises(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_exception(httpx.ConnectError("name resolution failed"))
    rec = check_health()
    assert rec["reachable"] is False
    assert rec["error"] and "ConnectError" in rec["error"]
    assert rec["pr_site_count"] is None


def test_health_accepts_injected_client(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(url=f"{BASE}/sites", json=_sites_payload())
    with NeonClient() as client:
        rec = check_health(client)
    assert rec["reachable"] is True


def test_health_is_json_serializable(httpx_mock, monkeypatch):
    """scripts/ingest_neon.py writes this straight to outputs/neon_health.json."""
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(url=f"{BASE}/sites", json=_sites_payload())
    json.dumps(check_health())
