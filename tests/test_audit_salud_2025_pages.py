import struct
from pathlib import Path

import pytest
from scripts.audit_salud_2025_pages import (
    CANDIDATE_STATE,
    candidate_receipt,
    png_dimensions,
    validate_candidate,
)


PDF_SHA = "a" * 64
PAGE_SHA = "b" * 64


def _page_lookup():
    return {
        ("10747", 1): {
            "source_record_id": "10747",
            "page_number": 1,
            "render_sha256": PAGE_SHA,
        }
    }


def _candidate(**overrides):
    row = {
        "candidate_id": "salud:10747:p1:r1",
        "source_record_id": "10747",
        "source_pdf_sha256": PDF_SHA,
        "page_number": 1,
        "page_render_sha256": PAGE_SHA,
        "row_ordinal_on_page": 1,
        "extraction_method": "MANUAL_PAGE_REVIEW",
        "state": CANDIDATE_STATE,
        "fields": {"pwsid_raw": "PR0000001"},
    }
    row.update(overrides)
    return row


def test_png_dimensions_reads_ihdr(tmp_path):
    path = tmp_path / "page.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + struct.pack(">II", 1320, 1020)
    )
    assert png_dimensions(path) == (1320, 1020)


def test_candidate_must_bind_exact_pdf_and_page_hash(monkeypatch):
    from scripts import audit_salud_2025_pages as audit

    monkeypatch.setitem(audit.SOURCES["10747"], "sha256", PDF_SHA)
    row = validate_candidate(_candidate(), page_lookup=_page_lookup())
    assert row["state"] == CANDIDATE_STATE

    with pytest.raises(ValueError, match="source PDF hash mismatch"):
        validate_candidate(
            _candidate(source_pdf_sha256="c" * 64),
            page_lookup=_page_lookup(),
        )

    with pytest.raises(ValueError, match="rendered page hash mismatch"):
        validate_candidate(
            _candidate(page_render_sha256="d" * 64),
            page_lookup=_page_lookup(),
        )


def test_candidate_cannot_self_promote_to_verified(monkeypatch):
    from scripts import audit_salud_2025_pages as audit

    monkeypatch.setitem(audit.SOURCES["10747"], "sha256", PDF_SHA)
    with pytest.raises(ValueError, match="must remain CANDIDATE_UNVERIFIED"):
        validate_candidate(
            _candidate(state="VERIFIED"),
            page_lookup=_page_lookup(),
        )


def test_candidate_method_is_bounded(monkeypatch):
    from scripts import audit_salud_2025_pages as audit

    monkeypatch.setitem(audit.SOURCES["10747"], "sha256", PDF_SHA)
    with pytest.raises(ValueError, match="unsupported extraction_method"):
        validate_candidate(
            _candidate(extraction_method="AUTO_CANONICAL"),
            page_lookup=_page_lookup(),
        )


def test_candidate_denominator_closes_without_verifying_rows(monkeypatch):
    from scripts import audit_salud_2025_pages as audit

    monkeypatch.setitem(audit.SOURCES["10747"], "sha256", PDF_SHA)
    rows, accounting = candidate_receipt(
        [_candidate()],
        page_lookup=_page_lookup(),
    )
    assert len(rows) == 1
    assert accounting == {
        "candidate_source": 1,
        "candidate_unverified": 1,
        "candidate_verified": 0,
        "candidate_rejected": 0,
        "accounted": 1,
        "delta": 0,
        "state": "PASS",
    }


def test_duplicate_page_row_identity_is_rejected(monkeypatch):
    from scripts import audit_salud_2025_pages as audit

    monkeypatch.setitem(audit.SOURCES["10747"], "sha256", PDF_SHA)
    with pytest.raises(ValueError, match="duplicate candidate page-row identity"):
        candidate_receipt(
            [
                _candidate(candidate_id="one"),
                _candidate(candidate_id="two"),
            ],
            page_lookup=_page_lookup(),
        )
