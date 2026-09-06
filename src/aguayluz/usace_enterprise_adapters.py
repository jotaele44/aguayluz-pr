from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from aguayluz.usace_corpus import DiscoveryCandidate, canonicalize_usace_url, utc_now


@dataclass(frozen=True)
class PaginationReceipt:
    state: str
    pages_fetched: int
    unique_candidate_count: int
    total_expected: int | None
    duplicate_candidate_count: int
    page_receipts: tuple[dict[str, Any], ...]


def _nested(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        cur: Any = payload
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok:
            return cur
    return None


def discover_dspace7_page(
    payload: dict[str, Any],
    *,
    source_id: str,
    source_page: str,
    retrieved_utc: str | None = None,
) -> list[DiscoveryCandidate]:
    """Parse one DSpace 7 discovery page without treating repository UUID as project identity."""
    objects = _nested(
        payload,
        ("_embedded", "searchResult", "_embedded", "objects"),
        ("_embedded", "objects"),
    )
    if objects is None:
        objects = []
    if not isinstance(objects, list):
        raise ValueError("DSpace objects must be a list")
    now = retrieved_utc or utc_now()
    out: list[DiscoveryCandidate] = []
    for wrapper in objects:
        if not isinstance(wrapper, dict):
            continue
        embedded = wrapper.get("_embedded")
        item = embedded.get("indexableObject") if isinstance(embedded, dict) else None
        if not isinstance(item, dict):
            item = wrapper.get("indexableObject") if isinstance(wrapper.get("indexableObject"), dict) else wrapper
        uuid = str(item.get("uuid") or "").strip()
        name = str(item.get("name") or item.get("title") or "UNLABELED_ITEM").strip()
        if not uuid:
            links = item.get("_links") if isinstance(item.get("_links"), dict) else {}
            self_href = (links.get("self") or {}).get("href") if isinstance(links.get("self"), dict) else None
            if self_href:
                uuid = str(self_href).rstrip("/").split("/")[-1]
        if not uuid:
            continue
        origin = urlsplit(source_page)
        item_url = f"{origin.scheme}://{origin.netloc}/items/{uuid}"
        out.append(
            DiscoveryCandidate(
                source_id=source_id,
                source_page=source_page,
                project_raw="UNRESOLVED_PROJECT",
                document_raw=name,
                url_raw=item_url,
                url_canonical=canonicalize_usace_url(item_url),
                discovered_utc=now,
                discovery_method="DSPACE7_DISCOVERY_API",
            )
        )
    return out


def dspace_page_meta(payload: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    page = _nested(payload, ("_embedded", "searchResult", "page"), ("page",))
    if not isinstance(page, dict):
        return None, None, None

    def as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return as_int(page.get("number")), as_int(page.get("totalPages")), as_int(page.get("totalElements"))


def fetch_dspace7_all(
    client: httpx.Client,
    source: dict[str, Any],
) -> tuple[list[DiscoveryCandidate], PaginationReceipt]:
    """Paginate DSpace 7 discovery deterministically and retain duplicate counts."""
    base = str(source.get("api_url") or source["url"]).rstrip("/")
    query = str(source.get("query") or "Puerto Rico")
    size = int(source.get("page_size") or 100)
    if not 1 <= size <= 1000:
        raise ValueError("DSpace page_size outside 1..1000")
    candidates: list[DiscoveryCandidate] = []
    seen: set[str] = set()
    dupes = 0
    page_receipts: list[dict[str, Any]] = []
    page_no = 0
    total_pages: int | None = None
    total_elements: int | None = None
    while True:
        url = f"{base}/server/api/discover/search/objects?query={quote(query)}&size={size}&page={page_no}"
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
        found = discover_dspace7_page(payload, source_id=source["source_id"], source_page=url)
        new_count = 0
        for row in found:
            if row.url_canonical in seen:
                dupes += 1
                continue
            seen.add(row.url_canonical)
            candidates.append(row)
            new_count += 1
        number, pages, elements = dspace_page_meta(payload)
        if number is not None and number != page_no:
            raise RuntimeError(f"DSpace page mismatch requested={page_no} returned={number}")
        if pages is not None:
            total_pages = pages
        if elements is not None:
            total_elements = elements
        page_receipts.append(
            {
                "page": page_no,
                "url": url,
                "http_status": response.status_code,
                "raw_candidate_count": len(found),
                "new_candidate_count": new_count,
            }
        )
        if total_pages is not None:
            if page_no + 1 >= total_pages:
                break
        elif not found or len(found) < size:
            break
        page_no += 1
        if page_no >= 10000:
            raise RuntimeError("DSpace pagination exceeded safety bound")
    state = "PASS"
    if total_elements is not None and len(candidates) > total_elements:
        state = "UNRESOLVED_COUNT_OVERFLOW"
    elif total_pages is not None and len(page_receipts) != total_pages:
        state = "UNRESOLVED_PAGE_COUNT"
    return candidates, PaginationReceipt(
        state,
        len(page_receipts),
        len(candidates),
        total_elements,
        dupes,
        tuple(page_receipts),
    )


def discover_pal_resource_links(
    html: str,
    *,
    source_id: str,
    source_page: str,
    retrieved_utc: str | None = None,
) -> list[DiscoveryCandidate]:
    """Resolve PAL resource/download links from retrieved HTML; this is not exhaustive PAL search."""
    pattern = re.compile(r'href=["\']([^"\']*(?:/resource(?:\?|/)|/api/download\?)[^"\']+)["\']', re.I)
    now = retrieved_utc or utc_now()
    out: list[DiscoveryCandidate] = []
    seen: set[str] = set()
    for raw in pattern.findall(html):
        raw = unescape(raw)
        url = canonicalize_usace_url(raw, base_url=source_page)
        if url in seen:
            continue
        seen.add(url)
        out.append(
            DiscoveryCandidate(
                source_id,
                source_page,
                "UNRESOLVED_PROJECT",
                "PAL_RESOURCE_OR_DOWNLOAD",
                raw,
                url,
                now,
                "PAL_PUBLIC_RESOURCE_LINK",
            )
        )
    return out


def pal_search_capability_receipt(source: dict[str, Any]) -> dict[str, Any]:
    """Encode the bounded PAL state: API is documented, exhaustive search request schema is not yet bound."""
    bound = bool(source.get("search_request_schema_bound", False))
    return {
        "source_id": source["source_id"],
        "api_documented": True,
        "public_search_limit_simple": 250,
        "public_search_limit_advanced": 200,
        "resource_url_pattern_known": True,
        "download_url_pattern_known": True,
        "search_request_schema_bound": bound,
        "state": "PASS_SEARCH_SCHEMA" if bound else "BLOCKED_SEARCH_REQUEST_SCHEMA",
    }
