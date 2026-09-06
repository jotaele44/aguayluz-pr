from __future__ import annotations

import io
from pathlib import Path
import zipfile

from aguayluz.usace_enterprise_adapters import (
    discover_dspace7_page,
    discover_pal_resource_links,
    dspace_page_meta,
    fetch_dspace7_all,
    pal_search_capability_receipt,
)
from aguayluz.usace_manifestation import (
    classify_zip_identity,
    download_manifestation,
    validate_payload_signature,
)
from aguayluz.usace_waterbody_binding import (
    WaterbodyRecord,
    adjudicate,
    bind_with_evidence,
    discover_name_candidates,
)


def _zip_bytes(name: str = "a.txt", data: bytes = b"x", compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        archive.writestr(name, data)
    return buffer.getvalue()


def test_dspace_page_schema() -> None:
    payload = {
        "_embedded": {
            "searchResult": {
                "_embedded": {
                    "objects": [
                        {"_embedded": {"indexableObject": {"uuid": "abc", "name": "Puerto Rico report"}}}
                    ]
                },
                "page": {"number": 0, "totalPages": 1, "totalElements": 1},
            }
        }
    }
    rows = discover_dspace7_page(
        payload,
        source_id="erdc",
        source_page="https://erdc-library.erdc.dren.mil/server/api/discover/search/objects",
    )
    assert len(rows) == 1
    assert rows[0].url_canonical.endswith("/items/abc")
    assert dspace_page_meta(payload) == (0, 1, 1)


def test_pal_links_and_bounded_capability() -> None:
    html = (
        '<a href="/resource?title=X&documentId=abc">X</a>'
        '<a href="/api/download?id=abc&filename=x.pdf">PDF</a>'
    )
    rows = discover_pal_resource_links(
        html,
        source_id="pal",
        source_page="https://publibrary.sec.usace.army.mil/search",
    )
    assert len(rows) == 2
    receipt = pal_search_capability_receipt(
        {"source_id": "pal", "search_request_schema_bound": False}
    )
    assert receipt["api_documented"] is True
    assert receipt["state"] == "BLOCKED_SEARCH_REQUEST_SCHEMA"


def test_signature_rejects_html_masquerading_as_pdf() -> None:
    assert validate_payload_signature("x.pdf", b"%PDF-1.7\n", "application/pdf") == "PASS_SIGNATURE"
    try:
        validate_payload_signature("x.pdf", b"<html>oops</html>", "text/html")
    except ValueError:
        pass
    else:
        raise AssertionError("HTML masquerading as PDF was accepted")


def test_zip_identity_algebra() -> None:
    left = _zip_bytes(compression=zipfile.ZIP_STORED)
    right = _zip_bytes(compression=zipfile.ZIP_DEFLATED)
    assert classify_zip_identity(left, right) in {"BYTE_IDENTICAL", "PURE_RECOMPRESSION"}
    renamed = _zip_bytes(name="other.txt")
    assert classify_zip_identity(left, renamed) == "SAME_PAYLOADS_DIFFERENT_PATHS"
    changed = _zip_bytes(data=b"y")
    assert classify_zip_identity(left, changed) == "DISTINCT_PAYLOADS"


def test_name_only_never_proves_waterbody_identity() -> None:
    waterbody = WaterbodyRecord(
        "gnis_1",
        "Río Culebrinas",
        stable_ids=("GNIS:1",),
        aliases=("Rio Culebrinas",),
    )
    candidates = discover_name_candidates("Rio Culebrinas Flood Control Project", [waterbody])
    assert candidates[0].state == "CANDIDATE_NOT_IDENTITY"
    hard = bind_with_evidence("project", waterbody, "STABLE_ID", "GNIS:1")
    assert adjudicate([hard])["state"] == "PASS"


class _FakeResponse:
    def __init__(
        self,
        content: bytes,
        url: str,
        status_code: int = 200,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.content = content
        self.url = url
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)

    def get(self, url: str, **kwargs):
        return self.responses.pop(0)


def test_same_filename_different_bytes_gets_hash_suffix(tmp_path: Path) -> None:
    first = download_manifestation(
        _FakeClient([_FakeResponse(b"%PDF-1.4\nA", "https://x.test/a.pdf", content_type="application/pdf")]),
        "https://x.test/a.pdf",
        source_id="s",
        output_dir=tmp_path,
    )
    second = download_manifestation(
        _FakeClient([_FakeResponse(b"%PDF-1.4\nB", "https://x.test/a.pdf", content_type="application/pdf")]),
        "https://x.test/a.pdf",
        source_id="s",
        output_dir=tmp_path,
    )
    assert first.sha256 != second.sha256
    assert first.output_path != second.output_path
    assert "__" in second.output_path


def test_dspace_duplicate_uuid_dedupes() -> None:
    payload = {
        "_embedded": {
            "searchResult": {
                "_embedded": {
                    "objects": [
                        {"_embedded": {"indexableObject": {"uuid": "abc", "name": "X"}}},
                        {"_embedded": {"indexableObject": {"uuid": "abc", "name": "X duplicate"}}},
                    ]
                },
                "page": {"number": 0, "totalPages": 1, "totalElements": 1},
            }
        }
    }

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    class Client:
        def get(self, url: str):
            return Response()

    rows, receipt = fetch_dspace7_all(
        Client(),
        {
            "source_id": "erdc",
            "url": "https://erdc-library.erdc.dren.mil",
            "query": "Puerto Rico",
            "page_size": 100,
        },
    )
    assert len(rows) == 1
    assert receipt.duplicate_candidate_count == 1
    assert receipt.state == "PASS"


def test_dspace_page_mismatch_fails_closed() -> None:
    payload = {
        "_embedded": {
            "searchResult": {
                "_embedded": {"objects": []},
                "page": {"number": 1, "totalPages": 1, "totalElements": 0},
            }
        }
    }

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    class Client:
        def get(self, url: str):
            return Response()

    try:
        fetch_dspace7_all(
            Client(),
            {"source_id": "erdc", "url": "https://erdc-library.erdc.dren.mil"},
        )
    except RuntimeError as exc:
        assert "page mismatch" in str(exc)
    else:
        raise AssertionError("page mismatch did not fail closed")


def test_tied_hard_evidence_remains_unresolved() -> None:
    left = WaterbodyRecord("a", "Río A")
    right = WaterbodyRecord("b", "Río B")
    result = adjudicate(
        [
            bind_with_evidence("project", left, "STABLE_ID", "A"),
            bind_with_evidence("project", right, "AUTHORITATIVE_BINDING", "B"),
        ]
    )
    assert result["state"] == "UNRESOLVED_TIED_HARD_EVIDENCE"
    assert result["cardinality"] == "1:N"
