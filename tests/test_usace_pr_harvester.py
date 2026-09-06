from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from aguayluz.usace_corpus import (
    assert_arithmetic_closure,
    canonicalize_usace_url,
    discover_contentdm_search,
    discover_saj_environmental_documents,
    download_url,
    inspect_fixture_text,
)


def test_afpims_url_is_rewritten_without_using_name_as_identity() -> None:
    raw = "https://saj.usace.afpims.mil/Portals/44/a.pdf#page=2"
    assert canonicalize_usace_url(raw) == "https://www.saj.usace.army.mil/Portals/44/a.pdf"


def test_saj_environmental_adapter_preserves_raw_project_and_expands_family() -> None:
    html = """
    <table>
      <tr><td>Puerto Rico</td></tr>
      <tr>
        <td>Rio Culebrinas, Flood Control, Section 204 CAP</td>
        <td>Detailed Project Report</td>
        <td>
          <a href="/main.pdf">Main Text</a>
          <a href="https://saj.usace.afpims.mil/ea.pdf">EA</a>
          <a href="/B.pdf">-B, Geotechnical</a>
        </td>
      </tr>
      <tr><td></td><td></td><td><a href="/coastal.pdf">Application for Coastal Zone Consistency Concurrence</a></td></tr>
      <tr><td>U.S. Virgin Islands</td></tr>
      <tr><td>Should Not Be Included</td><td></td><td><a href="/no.pdf">No</a></td></tr>
    </table>
    """
    rows = discover_saj_environmental_documents(
        html,
        source_id="saj",
        source_page="https://www.saj.usace.army.mil/environmental/",
        retrieved_utc="2026-09-06T00:00:00+00:00",
    )
    assert [row.document_raw for row in rows] == [
        "Main Text",
        "EA",
        "-B, Geotechnical",
        "Application for Coastal Zone Consistency Concurrence",
    ]
    assert all(row.project_raw == "Rio Culebrinas, Flood Control, Section 204 CAP" for row in rows)
    assert rows[1].url_canonical == "https://www.saj.usace.army.mil/ea.pdf"


def test_contentdm_adapter_preserves_candidate_set() -> None:
    payload = {
        "items": [
            {
                "collectionAlias": "p16021coll7",
                "itemLink": "/digital/collection/p16021coll7/id/24544/",
                "title": "Survey report: Rio Puerto Nuevo, Puerto Rico",
                "subCollection": "Project Management Reports, Jacksonville District",
            },
            {
                "collectionAlias": "p16021coll7",
                "pointer": "24545",
                "title": "Different manifestation",
                "subCollection": "Project Management Reports, Jacksonville District",
            },
        ]
    }
    rows = discover_contentdm_search(
        payload,
        source_id="contentdm",
        source_page="https://usace.contentdm.oclc.org/digital/api/search",
        retrieved_utc="2026-09-06T00:00:00+00:00",
    )
    assert len(rows) == 2
    assert rows[0].url_canonical.endswith("/p16021coll7/id/24544/")
    assert rows[1].url_canonical.endswith("/p16021coll7/id/24545/")


def test_download_freezes_bytes_and_receipt(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"fixture-pdf-bytes",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        receipt = download_url(
            client,
            "https://example.test/report.pdf",
            source_id="fixture",
            output_dir=tmp_path,
        )
    assert Path(receipt.output_path).read_bytes() == b"fixture-pdf-bytes"
    receipt_json = json.loads(Path(receipt.output_path + ".receipt.json").read_text())
    assert receipt_json["sha256"] == receipt.sha256
    assert receipt_json["byte_count"] == len(b"fixture-pdf-bytes")


def test_arithmetic_closure_rejects_unclassified() -> None:
    assert assert_arithmetic_closure(
        [
            {"disposition": "RETRIEVED"},
            {"disposition": "EXCLUDED"},
            {"disposition": "UNAVAILABLE"},
            {"disposition": "UNRESOLVED"},
        ]
    ) == {
        "source_total": 4,
        "retrieved": 1,
        "excluded": 1,
        "unavailable": 1,
        "unresolved": 1,
    }
    with pytest.raises(ValueError):
        assert_arithmetic_closure([{"disposition": "DISCOVERED"}])


def test_fixture_detects_mixed_logical_sections_and_borings() -> None:
    text = """
    APPENDIX B GEOTECHNICAL STUDIES
    CB-CUL-01 CB-CUL-02 CB-CUL-15
    APPENDIX C DESIGN AND COST ESTIMATES
    """
    result = inspect_fixture_text(text)
    assert result["appendices_detected"] == ["B", "C"]
    assert result["boring_ids"] == ["01", "02", "15"]
    assert result["has_geotechnical"] is True
    assert result["has_design_cost"] is True
