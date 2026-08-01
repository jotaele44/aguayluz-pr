"""NeonClient: token resolution, the 403 split, retry, and secret hygiene.

The 403 split is the reason this client exists rather than a bare httpx.get: NEON
returns 403 both for "this endpoint needs a token" and for "your token is bad", and
those need different operator action.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from aguayluz.neon import endpoints
from aguayluz.neon.client import TOKEN_HEADER, NeonClient, resolve_token
from aguayluz.neon.errors import (
    NeonAccessDenied,
    NeonAuthError,
    NeonRateLimitExceeded,
    NeonServerError,
)

BASE = endpoints.DEFAULT_BASE_URL


# ── token resolution ──────────────────────────────────────────────────────────
def test_resolve_token_prefers_explicit(monkeypatch):
    monkeypatch.setenv("NEON_API_TOKEN", "from-env")
    assert resolve_token("explicit") == "explicit"


def test_resolve_token_env_order(monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.setenv("NEON_API_KEY", "fallback")
    assert resolve_token() == "fallback"
    monkeypatch.setenv("NEON_API_TOKEN", "primary")
    assert resolve_token() == "primary"


def test_resolve_token_returns_none_when_absent(monkeypatch):
    """Anonymous is a supported mode — unlike WatersClient, this must not raise."""
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    assert resolve_token() is None


# ── auth header ───────────────────────────────────────────────────────────────
def test_token_sent_as_x_api_token_header(httpx_mock, monkeypatch):
    """NEON authenticates on X-API-Token; Authorization: Bearer fails open."""
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(url=f"{BASE}/sites", json={"data": []})
    with NeonClient(token="tok-123") as c:
        c.get(endpoints.SITES)
    req = httpx_mock.get_requests()[0]
    assert req.headers[TOKEN_HEADER] == "tok-123"
    assert "authorization" not in {k.lower() for k in req.headers}


def test_no_token_header_when_anonymous(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(url=f"{BASE}/sites", json={"data": []})
    with NeonClient() as c:
        c.get(endpoints.SITES)
    assert TOKEN_HEADER not in httpx_mock.get_requests()[0].headers


# ── the 403 split ─────────────────────────────────────────────────────────────
def test_403_with_token_is_auth_error(httpx_mock, monkeypatch):
    """A rejected token must be loud — never a silent anonymous downgrade."""
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(
        url=f"{BASE}/sites", status_code=403,
        json={"error": {"status": 403, "detail": "Access Denied"}, "data": None},
    )
    with NeonClient(token="stale-token") as c, pytest.raises(NeonAuthError) as exc:
        c.get(endpoints.SITES)
    assert "NEON_API_TOKEN" in str(exc.value)


def test_403_without_token_is_access_denied(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    path = endpoints.data_manifest("DP4.00130.001", "CUPE", "2026-06")
    httpx_mock.add_response(
        url=f"{BASE}{path}", status_code=403,
        json={"error": {"status": 403, "detail": "Access Denied"}, "data": None},
    )
    with NeonClient() as c, pytest.raises(NeonAccessDenied) as exc:
        c.get(path)
    assert "requires a NEON API token" in str(exc.value)


def test_access_denied_is_not_auth_error():
    """The two 403 cases must not be catchable as one another."""
    assert not issubclass(NeonAccessDenied, NeonAuthError)
    assert not issubclass(NeonAuthError, NeonAccessDenied)


# ── retry ─────────────────────────────────────────────────────────────────────
def test_429_retries_then_succeeds(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(url=f"{BASE}/sites", status_code=429, headers={"Retry-After": "2"})
    httpx_mock.add_response(url=f"{BASE}/sites", json={"data": [{"siteCode": "CUPE"}]})
    slept: list[float] = []
    with NeonClient(sleep_fn=slept.append) as c:
        assert c.get(endpoints.SITES)["data"][0]["siteCode"] == "CUPE"
    assert slept == [2.0]  # Retry-After honoured verbatim, not backed off


def test_429_exhausted_raises(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    for _ in range(3):
        httpx_mock.add_response(url=f"{BASE}/sites", status_code=429)
    with (
        NeonClient(max_retries=2, sleep_fn=lambda _s: None) as c,
        pytest.raises(NeonRateLimitExceeded) as exc,
    ):
        c.get(endpoints.SITES)
    assert exc.value.attempts == 3


def test_5xx_retries_then_raises(httpx_mock, monkeypatch):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    for _ in range(3):
        httpx_mock.add_response(url=f"{BASE}/sites", status_code=503, text="upstream down")
    with (
        NeonClient(max_retries=2, sleep_fn=lambda _s: None) as c,
        pytest.raises(NeonServerError) as exc,
    ):
        c.get(endpoints.SITES)
    assert exc.value.status_code == 503


def test_404_propagates_as_http_error(httpx_mock, monkeypatch):
    """An unpublished month is a 404 and must stay distinguishable from an auth failure."""
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(url=f"{BASE}/sites", status_code=404)
    with NeonClient() as c, pytest.raises(httpx.HTTPStatusError):
        c.get(endpoints.SITES)


# ── observability + secret hygiene ────────────────────────────────────────────
def test_rate_limit_recorded_and_warned(httpx_mock, monkeypatch, caplog):
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(
        url=f"{BASE}/sites", json={"data": []}, headers={"X-RateLimit-Remaining": "3"}
    )
    with caplog.at_level(logging.WARNING, logger="aguayluz.neon"), NeonClient() as c:
        c.get(endpoints.SITES)
        assert c.rate_limit_remaining == 3
    assert "rate limit low" in caplog.text


def test_token_never_leaks_in_repr_or_logs(httpx_mock, monkeypatch, caplog):
    # Deliberately short and non-credential-shaped: a longer literal after a
    # `token =` assignment trips the repo's own G07 secret gate
    # (aguayluz.validation._SECRET_PATTERNS), which is working as intended.
    canary = "zzq-tok-9182"
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    httpx_mock.add_response(url=f"{BASE}/sites", status_code=429)
    httpx_mock.add_response(url=f"{BASE}/sites", json={"data": []})
    with (
        caplog.at_level(logging.DEBUG, logger="aguayluz.neon"),
        NeonClient(token=canary, sleep_fn=lambda _s: None) as c,
    ):
        assert canary not in repr(c)
        assert c.has_token is True
        c.get(endpoints.SITES)
    assert canary not in caplog.text
