"""Offline tests for scripts/fetch_luma_live.py error handling.

These never touch the network: the MiLUMA endpoint is Incapsula-WAF gated (HTTP 403
to plain clients), so we mock ``urllib.request.urlopen`` to assert the fetcher turns
the WAF/403 (and generic network) failures into a typed ``SourceUnavailable`` result
plus a dedicated exit code, instead of crashing with a raw traceback.
"""
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_luma_live  # noqa: E402
from fetch_luma_live import (  # noqa: E402
    EXIT_SOURCE_UNAVAILABLE,
    SourceUnavailable,
    fetch_towns,
)


def _raise(exc):
    def _stub(*_args, **_kwargs):
        raise exc
    return _stub


def test_waf_403_becomes_typed_source_unavailable(monkeypatch):
    err = urllib.error.HTTPError(fetch_luma_live.TOWNS_URL, 403, "Forbidden", {}, None)
    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _raise(err))
    with pytest.raises(SourceUnavailable) as ei:
        fetch_towns(["SAN JUAN"], timeout=1.0)
    msg = str(ei.value)
    assert "403" in msg and "WAF" in msg  # the expected Incapsula block, clearly labelled


def test_network_error_becomes_typed_source_unavailable(monkeypatch):
    monkeypatch.setattr(
        fetch_luma_live.urllib.request, "urlopen",
        _raise(urllib.error.URLError("connection refused")),
    )
    with pytest.raises(SourceUnavailable):
        fetch_towns(["SAN JUAN"], timeout=1.0)


def test_main_returns_dedicated_exit_code_no_traceback(monkeypatch, capsys):
    # main() must swallow SourceUnavailable, print a typed one-liner, and return
    # EXIT_SOURCE_UNAVAILABLE — never let the exception escape as a crash.
    err = urllib.error.HTTPError(fetch_luma_live.TOWNS_URL, 403, "Forbidden", {}, None)
    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _raise(err))
    monkeypatch.setattr(sys, "argv", ["fetch_luma_live.py"])

    rc = fetch_luma_live.main()

    assert rc == EXIT_SOURCE_UNAVAILABLE
    assert "source-unavailable" in capsys.readouterr().err


def test_non_403_http_error_still_typed(monkeypatch):
    err = urllib.error.HTTPError(fetch_luma_live.TOWNS_URL, 500, "Server Error", {}, None)
    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _raise(err))
    with pytest.raises(SourceUnavailable) as ei:
        fetch_towns(["SAN JUAN"], timeout=1.0, max_retries=0, sleep_fn=lambda _s: None)
    assert "500" in str(ei.value)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self) -> bytes:
        return self._body


def test_5xx_retries_then_succeeds(monkeypatch):
    """A transient 503 recovers on retry instead of failing the whole snapshot."""
    err = urllib.error.HTTPError(fetch_luma_live.TOWNS_URL, 503, "Service Unavailable", {}, None)
    calls = {"n": 0}

    def _flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise err
        return _FakeResponse(b'{"SAN JUAN": []}')

    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _flaky)
    slept: list[float] = []
    doc = fetch_towns(["SAN JUAN"], timeout=1.0, sleep_fn=slept.append)
    assert doc == {"SAN JUAN": []}
    assert calls["n"] == 2
    assert slept == [0.5]


def test_403_is_never_retried(monkeypatch):
    """The Incapsula WAF block is not transient — retrying it wastes the budget."""
    err = urllib.error.HTTPError(fetch_luma_live.TOWNS_URL, 403, "Forbidden", {}, None)
    calls = {"n": 0}

    def _always_403(*_args, **_kwargs):
        calls["n"] += 1
        raise err

    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _always_403)
    with pytest.raises(SourceUnavailable):
        fetch_towns(["SAN JUAN"], timeout=1.0, sleep_fn=lambda _s: None)
    assert calls["n"] == 1


def test_read_timeout_becomes_typed_source_unavailable(monkeypatch):
    # A read-phase socket timeout surfaces as a bare TimeoutError (not a URLError
    # subclass), so it must still be converted rather than escaping as a traceback.
    monkeypatch.setattr(
        fetch_luma_live.urllib.request, "urlopen", _raise(TimeoutError("timed out")),
    )
    with pytest.raises(SourceUnavailable) as ei:
        fetch_towns(["SAN JUAN"], timeout=1.0)
    assert "MiLUMA" in str(ei.value)
