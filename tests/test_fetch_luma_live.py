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
        fetch_towns(["SAN JUAN"], timeout=1.0)
    assert "500" in str(ei.value)


def test_read_timeout_becomes_typed_source_unavailable(monkeypatch):
    # A read-phase socket timeout surfaces as a bare TimeoutError (not a URLError
    # subclass), so it must still be converted rather than escaping as a traceback.
    monkeypatch.setattr(
        fetch_luma_live.urllib.request, "urlopen", _raise(TimeoutError("timed out")),
    )
    with pytest.raises(SourceUnavailable) as ei:
        fetch_towns(["SAN JUAN"], timeout=1.0)
    assert "MiLUMA" in str(ei.value)
