"""Offline adversarial tests for the hydro raw artifact vault."""
import hashlib
import json

import pytest

from aguayluz.hydro_intelligence.acquisition import persist_bytes, validate_url, fetch_artifact


def test_byte_exact_idempotency(tmp_path):
    first = persist_bytes(tmp_path, "eia_923", "https://www.eia.gov/f923_2026.zip",
                          b"test-payload", fetched_at="2026-10-25T00:00:00Z")
    second = persist_bytes(tmp_path, "eia_923", "https://www.eia.gov/f923_2026.zip",
                           b"test-payload", fetched_at="2026-10-26T00:00:00Z")
    assert first.sha256 == second.sha256 == hashlib.sha256(b"test-payload").hexdigest()
    assert len(list(tmp_path.rglob("*.receipt.json"))) == 1
    assert (tmp_path / "eia_923" / first.sha256[:2] / first.sha256).read_bytes() == b"test-payload"


def test_revision_is_new_artifact(tmp_path):
    a = persist_bytes(tmp_path, "eia_860m", "https://www.eia.gov/a.xlsx", b"v1")
    b = persist_bytes(tmp_path, "eia_860m", "https://www.eia.gov/a.xlsx", b"v2")
    assert a.sha256 != b.sha256
    assert len(list(tmp_path.rglob("*.receipt.json"))) == 2


@pytest.mark.parametrize("url", [
    "http://www.eia.gov/a", "https://evil.example/x",
    "https://www.eia.gov:8443/x", "file:///etc/passwd",
    "https://user:pass@www.eia.gov/x",
])
def test_reject_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_url(url, {"www.eia.gov"})


def test_reject_bad_sources(tmp_path):
    with pytest.raises(ValueError):
        persist_bytes(tmp_path, "../escape", "https://www.eia.gov", b"content")
    with pytest.raises(ValueError):
        persist_bytes(tmp_path, "eia_923", "https://www.eia.gov", b"")


def test_detect_mutated_existing_content(tmp_path):
    receipt = persist_bytes(tmp_path, "eia_923", "https://www.eia.gov", b"source")
    p = tmp_path / "eia_923" / receipt.sha256[:2] / receipt.sha256
    p.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        persist_bytes(tmp_path, "eia_923", "https://www.eia.gov", b"source")


def test_receipt_remains_raw_not_certified(tmp_path):
    receipt = persist_bytes(tmp_path, "luma_bps_daily", "https://lumapr.com/test.pdf", b"%PDF")
    assert receipt.state == "RAW_FROZEN_NOT_PARSED"
    item = next(tmp_path.rglob("*.receipt.json"))
    assert json.loads(item.read_text())["state"] == "RAW_FROZEN_NOT_PARSED"


def test_redirect_rejected_before_following(monkeypatch):
    from aguayluz.hydro_intelligence.acquisition import RejectRedirects
    with pytest.raises(ValueError, match="Redirect"):
        RejectRedirects().redirect_request(None, None, 302, "Found", {}, "https://evil.example")


def test_no_clobber_when_concurrent_writer_wins(tmp_path, monkeypatch):
    import os
    from aguayluz.hydro_intelligence import acquisition
    original_link = os.link

    def raced_link(source, target):
        target.write_bytes(b"tampered")
        raise FileExistsError()

    monkeypatch.setattr(acquisition.os, "link", raced_link)
    with pytest.raises(ValueError, match="Concurrent artifact"):
        persist_bytes(tmp_path, "eia_923", "https://www.eia.gov/test.zip", b"valid")
