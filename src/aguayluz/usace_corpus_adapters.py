from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from aguayluz.usace_corpus import DiscoveryCandidate, canonicalize_usace_url, discovery_key, utc_now


@dataclass(frozen=True)
class Anchor:
    text_raw: str
    href_raw: str


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[Anchor] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            self.anchors.append(
                Anchor(
                    text_raw=" ".join("".join(self._parts).split()),
                    href_raw=self._href,
                )
            )
            self._href = None
            self._parts = []


def _is_http_candidate(url: str) -> bool:
    split = urlsplit(url)
    return split.scheme in {"http", "https"} and bool(split.netloc)


def _looks_like_content_manifestation(url: str, text: str) -> bool:
    key = discovery_key(f"{url} {text}")
    path = urlsplit(url).path.casefold()
    if path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".kmz", ".kml")):
        return True
    return any(
        token in key
        for token in (
            "public notice",
            "environmental assessment",
            "environmental impact statement",
            "feasibility",
            "report",
            "appendix",
            "chief s report",
            "fonsi",
            "smmp",
            "dredging",
            "flood",
            "mitigation",
            "navigation",
            "document",
            "resource",
            "download",
        )
    )


def discover_pr_scoped_index(
    html: str,
    *,
    source_id: str,
    source_page: str,
    retrieved_utc: str | None = None,
    require_document_like: bool = False,
) -> list[DiscoveryCandidate]:
    """Discover links from a source page whose source scope is already Puerto Rico.

    This adapter intentionally over-discovers. Project and waterbody identity stay unresolved
    until downstream evidence binds them.
    """
    parser = AnchorParser()
    parser.feed(html)
    now = retrieved_utc or utc_now()
    out: list[DiscoveryCandidate] = []
    seen: set[tuple[str, str]] = set()
    for anchor in parser.anchors:
        absolute = canonicalize_usace_url(anchor.href_raw, base_url=source_page)
        if not _is_http_candidate(absolute):
            continue
        if require_document_like and not _looks_like_content_manifestation(absolute, anchor.text_raw):
            continue
        key = (absolute, anchor.text_raw)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            DiscoveryCandidate(
                source_id=source_id,
                source_page=source_page,
                project_raw="UNRESOLVED_PROJECT",
                document_raw=anchor.text_raw or "UNLABELED_LINK",
                url_raw=anchor.href_raw,
                url_canonical=absolute,
                discovered_utc=now,
                discovery_method="PR_SCOPED_INDEX_LINK",
            )
        )
    return out


def discover_generic_index(
    html: str,
    *,
    source_id: str,
    source_page: str,
    include_href_regex: str,
    retrieved_utc: str | None = None,
) -> list[DiscoveryCandidate]:
    """Broad first-pass discovery for mixed-geography USACE indexes.

    All matches remain unresolved candidates. Filtering a mixed index is not identity proof.
    """
    parser = AnchorParser()
    parser.feed(html)
    pattern = re.compile(include_href_regex, flags=re.I)
    now = retrieved_utc or utc_now()
    out: list[DiscoveryCandidate] = []
    seen: set[str] = set()
    for anchor in parser.anchors:
        absolute = canonicalize_usace_url(anchor.href_raw, base_url=source_page)
        if not _is_http_candidate(absolute) or not pattern.search(absolute):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(
            DiscoveryCandidate(
                source_id=source_id,
                source_page=source_page,
                project_raw="UNRESOLVED_PROJECT",
                document_raw=anchor.text_raw or "UNLABELED_LINK",
                url_raw=anchor.href_raw,
                url_canonical=absolute,
                discovered_utc=now,
                discovery_method="GENERIC_MIXED_INDEX_LINK",
            )
        )
    return out


def page_has_explicit_pr_scope(text: str) -> bool:
    key = discovery_key(text)
    evidence = (
        "puerto rico" in key
        or "commonwealth of puerto rico" in key
        or "congressional district puerto rico" in key
    )
    return evidence
