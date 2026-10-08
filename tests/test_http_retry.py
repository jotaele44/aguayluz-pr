"""Shared retry helper: 429/5xx retry with backoff, transport errors, 4xx passthrough."""
from __future__ import annotations

import httpx
import pytest

from aguayluz.http_retry import get_with_retry, request_with_retry

URL = "https://example.invalid/data"


def test_429_retries_then_succeeds(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=429, headers={"Retry-After": "2"})
    httpx_mock.add_response(url=URL, json={"ok": True})
    slept: list[float] = []
    r = get_with_retry(URL, sleep_fn=slept.append)
    assert r.json() == {"ok": True}
    assert slept == [2.0]  # Retry-After honoured verbatim, not backed off


def test_5xx_retries_then_returns_final_response(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=URL, status_code=503, text="upstream down")
    r = get_with_retry(URL, max_retries=2, sleep_fn=lambda _s: None)
    assert r.status_code == 503
    with pytest.raises(httpx.HTTPStatusError):
        r.raise_for_status()


def test_timeout_retries_then_succeeds(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectTimeout("timed out"))
    httpx_mock.add_response(url=URL, json={"ok": True})
    slept: list[float] = []
    r = get_with_retry(URL, sleep_fn=slept.append)
    assert r.json() == {"ok": True}
    assert len(slept) == 1


def test_timeout_exhausted_raises(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("timed out"))
    with pytest.raises(httpx.ConnectTimeout):
        get_with_retry(URL, max_retries=2, sleep_fn=lambda _s: None)


def test_404_not_retried(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=404)
    r = get_with_retry(URL, sleep_fn=lambda _s: None)
    assert r.status_code == 404
    assert len(httpx_mock.get_requests()) == 1


def test_200_not_retried(httpx_mock):
    httpx_mock.add_response(url=URL, json={"ok": True})
    r = get_with_retry(URL, sleep_fn=lambda _s: None)
    assert r.json() == {"ok": True}
    assert len(httpx_mock.get_requests()) == 1


def test_request_with_retry_reuses_supplied_client(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=502)
    httpx_mock.add_response(url=URL, json={"ok": True})
    with httpx.Client() as client:
        r = request_with_retry(client, "GET", URL, sleep_fn=lambda _s: None)
    assert r.json() == {"ok": True}
