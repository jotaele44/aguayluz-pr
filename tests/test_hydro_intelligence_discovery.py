"""Deterministic offline tests: discovery, retries, quarantine, receipt immutability."""
import json
import pytest

from aguayluz.hydro_intelligence.discovery import (
    acquire_with_retry, discover_links, freeze_result_log,
)


def test_discover_only_allowlisted_source_links():
    html = b'<a href="/archive/xls/march_generator2026.xlsx">March</a><a href="https://evil.example/a.xlsx">Bad</a><a href="/news">Other</a>'
    links = discover_links("eia_860m", "https://www.eia.gov/electricity/data/eia860m/",
                           html, {"www.eia.gov"}, (".xlsx",))
    assert len(links) == 1
    assert links[0].artifact_url == "https://www.eia.gov/archive/xls/march_generator2026.xlsx"
    assert links[0].state == "DISCOVERED_NOT_ACQUIRED"


def test_retry_then_freeze(tmp_path):
    calls = []
    delays = []

    def fetcher(url, *, allowed_hosts):
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("temporary")
        return b"real bytes", "application/zip"

    result = acquire_with_retry(tmp_path, "eia_923", "https://www.eia.gov/f923_2026.zip",
                                allowed_hosts={"www.eia.gov"}, fetcher=fetcher,
                                sleeper=delays.append)
    assert result["state"] == "RAW_FROZEN_NOT_PARSED"
    assert len(calls) == 2 and delays == [1]
    assert result["receipt"]["byte_count"] == len(b"real bytes")


def test_access_denied_does_not_retry_or_emit_zero(tmp_path):
    class Forbidden(Exception):
        code = 403

    def fetcher(url, *, allowed_hosts):
        raise Forbidden("forbidden")

    outcome = acquire_with_retry(tmp_path, "luma_bps_daily", "https://lumapr.com/x.pdf",
                                 allowed_hosts={"lumapr.com"}, fetcher=fetcher)
    assert outcome["state"] == "QUARANTINED_NOT_PROMOTED"
    assert len(outcome["failures"]) == 1
    assert not list(tmp_path.rglob("*.receipt.json"))


def test_run_receipt_no_overwrite(tmp_path):
    p = tmp_path / "receipt.json"
    digest = freeze_result_log(p, [{"state": "QUARANTINED_NOT_PROMOTED"}])
    assert len(digest) == 64
    with pytest.raises(FileExistsError):
        freeze_result_log(p, [])
    assert json.loads(p.read_text())[0]["state"] == "QUARANTINED_NOT_PROMOTED"
