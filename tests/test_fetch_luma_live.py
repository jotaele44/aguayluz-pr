"""Offline tests for scripts/fetch_luma_live.py source and provenance handling."""
import hashlib
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_luma_live  # noqa: E402
from fetch_luma_live import (  # noqa: E402
    EXIT_SOURCE_UNAVAILABLE,
    SourceInvalid,
    SourceUnavailable,
    fetch_regions,
    fetch_towns,
)


class _Response:
    def __init__(self, raw: bytes):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.raw


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
    assert "403" in msg and "WAF" in msg


def test_network_error_becomes_typed_source_unavailable(monkeypatch):
    monkeypatch.setattr(
        fetch_luma_live.urllib.request,
        "urlopen",
        _raise(urllib.error.URLError("connection refused")),
    )
    with pytest.raises(SourceUnavailable):
        fetch_towns(["SAN JUAN"], timeout=1.0)


def test_non_403_http_error_still_typed(monkeypatch):
    err = urllib.error.HTTPError(fetch_luma_live.TOWNS_URL, 500, "Server Error", {}, None)
    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _raise(err))
    with pytest.raises(SourceUnavailable) as ei:
        fetch_towns(["SAN JUAN"], timeout=1.0)
    assert "500" in str(ei.value)


def test_read_timeout_becomes_typed_source_unavailable(monkeypatch):
    monkeypatch.setattr(
        fetch_luma_live.urllib.request,
        "urlopen",
        _raise(TimeoutError("timed out")),
    )
    with pytest.raises(SourceUnavailable) as ei:
        fetch_towns(["SAN JUAN"], timeout=1.0)
    assert "MiLUMA" in str(ei.value)


def test_regions_minimum_schema_and_arithmetic(monkeypatch):
    raw = json.dumps(
        {
            "regions": [
                {
                    "name": "SAN JUAN",
                    "totalClients": 1000,
                    "totalClientsWithoutService": 25,
                }
            ]
        }
    ).encode()
    monkeypatch.setattr(
        fetch_luma_live.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(raw),
    )
    doc = fetch_regions(timeout=1.0)
    assert doc["regions"][0]["totalClientsWithoutService"] == 25


def test_regions_affected_cannot_exceed_total(monkeypatch):
    raw = json.dumps(
        {
            "regions": [
                {
                    "name": "SAN JUAN",
                    "totalClients": 10,
                    "totalClientsWithoutService": 11,
                }
            ]
        }
    ).encode()
    monkeypatch.setattr(
        fetch_luma_live.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(raw),
    )
    with pytest.raises(SourceInvalid):
        fetch_regions(timeout=1.0)


def test_main_returns_dedicated_exit_code_and_deletes_stale_temp_files(
    monkeypatch, capsys, tmp_path
):
    towns = tmp_path / "towns.json"
    regions = tmp_path / "regions.json"
    meta = tmp_path / "manifest.json"
    for path in (towns, regions, meta):
        path.write_text("STALE")

    err = urllib.error.HTTPError(fetch_luma_live.TOWNS_URL, 403, "Forbidden", {}, None)
    monkeypatch.setattr(fetch_luma_live, "municipio_keys", lambda _path: ["SAN JUAN"])
    monkeypatch.setattr(fetch_luma_live.urllib.request, "urlopen", _raise(err))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_luma_live.py",
            "--out",
            str(towns),
            "--regions-out",
            str(regions),
            "--manifest-out",
            str(meta),
        ],
    )

    rc = fetch_luma_live.main()

    assert rc == EXIT_SOURCE_UNAVAILABLE
    assert "source-unavailable" in capsys.readouterr().err
    assert not towns.exists()
    assert not regions.exists()
    assert not meta.exists()


def test_main_preserves_exact_response_bytes_and_binds_manifest(monkeypatch, tmp_path):
    towns_raw = b'{"SAN JUAN":[{"zone":"CUPEY","area":"SAN JUAN"}]}\n'
    regions_raw = (
        b'{"regions":[{"name":"SAN JUAN","totalClients":1000,'
        b'"totalClientsWithoutService":25}]}\n'
    )
    responses = iter([towns_raw, regions_raw])

    monkeypatch.setattr(fetch_luma_live, "municipio_keys", lambda _path: ["SAN JUAN"])
    monkeypatch.setattr(
        fetch_luma_live.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(next(responses)),
    )

    towns = tmp_path / "towns.json"
    regions = tmp_path / "regions.json"
    meta = tmp_path / "manifest.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_luma_live.py",
            "--out",
            str(towns),
            "--regions-out",
            str(regions),
            "--manifest-out",
            str(meta),
        ],
    )

    assert fetch_luma_live.main() == 0
    assert towns.read_bytes() == towns_raw
    assert regions.read_bytes() == regions_raw

    receipt = json.loads(meta.read_text())
    assert receipt["towns"]["status"] == "PASS"
    assert receipt["regions"]["status"] == "PASS"
    assert receipt["towns"]["response_sha256"] == hashlib.sha256(towns_raw).hexdigest()
    assert receipt["regions"]["response_sha256"] == hashlib.sha256(regions_raw).hexdigest()
    assert receipt["towns"]["request_key_count"] == 1
