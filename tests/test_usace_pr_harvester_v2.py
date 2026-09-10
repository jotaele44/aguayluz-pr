from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx

from aguayluz.usace_corpus_adapters import (
    discover_generic_index,
    discover_pr_scoped_index,
    page_has_explicit_pr_scope,
)


def _load_operator_module():
    path = Path(__file__).resolve().parents[1] / "operators" / "harvest_usace_pr_v2.py"
    spec = importlib.util.spec_from_file_location("harvest_usace_pr_v2", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pr_scoped_index_overdiscovers_without_identity_promotion() -> None:
    html = """
    <a href='/Missions/Regulatory/Public-Notices/Article/123/foo/'>Rio Grande permit</a>
    <a href='/about/'>About</a>
    <a href='https://publibrary.sec.usace.army.mil/api/download?id=abc&filename=x.pdf'>Attachment</a>
    """
    rows = discover_pr_scoped_index(
        html,
        source_id="pr-reg",
        source_page="https://www.saj.usace.army.mil/Missions/Regulatory/Public-Notices/Tag/3896/puerto-rico/",
        retrieved_utc="2026-09-06T00:00:00+00:00",
    )
    assert len(rows) == 3
    assert all(row.project_raw == "UNRESOLVED_PROJECT" for row in rows)
    assert all(row.discovery_method == "PR_SCOPED_INDEX_LINK" for row in rows)


def test_generic_index_keeps_only_href_pattern_and_stays_unresolved() -> None:
    html = """
    <a href='/About/Congressional-Fact-Sheets-2025/Rio-Grande/'>Rio Grande</a>
    <a href='/About/Leadership/'>Leadership</a>
    """
    rows = discover_generic_index(
        html,
        source_id="facts",
        source_page="https://www.saj.usace.army.mil/About/Congressional-Fact-Sheets-2025/",
        include_href_regex=r"/About/Congressional-Fact-Sheets-2025/",
        retrieved_utc="2026-09-06T00:00:00+00:00",
    )
    assert len(rows) == 1
    assert rows[0].project_raw == "UNRESOLVED_PROJECT"


def test_explicit_pr_page_scope_is_not_generic_proximity() -> None:
    assert page_has_explicit_pr_scope("Congressional District: Puerto Rico") is True
    assert page_has_explicit_pr_scope("Project near Caribbean waters") is False


def test_contentdm_page_url_and_pagination_closure() -> None:
    module = _load_operator_module()
    base = "https://usace.contentdm.oclc.org/digital/api/search/searchterm/Puerto%20Rico/field/all/maxRecords/2"
    assert "/page/3/maxRecords/2" in module.contentdm_page_url(base, 3)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/page/1/" in url:
            items = [
                {"collectionAlias": "x", "pointer": "1", "title": "One"},
                {"collectionAlias": "x", "pointer": "2", "title": "Two"},
            ]
        elif "/page/2/" in url:
            items = [{"collectionAlias": "x", "pointer": "3", "title": "Three"}]
        else:
            items = []
        return httpx.Response(200, json={"totalResults": 3, "items": items}, request=request)

    source = {"source_id": "contentdm", "url": base}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows, receipt = module.fetch_contentdm_all(client, source)
    assert len(rows) == 3
    assert receipt["pagination_state"] == "PASS"
    assert receipt["total_expected"] == 3
    assert len(receipt["pages"]) == 2
