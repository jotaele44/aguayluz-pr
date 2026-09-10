from __future__ import annotations

from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlsplit

from aguayluz.usace_corpus import canonicalize_usace_url, discovery_key

DIRECT_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".kmz", ".kml", ".csv", ".json", ".xml", ".txt",
}


@dataclass(frozen=True)
class FamilyLink:
    parent_url: str
    child_url_raw: str
    child_url_canonical: str
    anchor_text_raw: str
    kind: str
    depth: int
    state: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None
            self._text = []


def is_direct_manifestation(url: str) -> bool:
    return Path(urlsplit(url).path).suffix.casefold() in DIRECT_SUFFIXES


def looks_family_relevant(text: str, url: str) -> bool:
    key = discovery_key(f"{text} {url}")
    tokens = (
        "appendix", "attachment", "report", "assessment", "impact statement",
        "feasibility", "geotechnical", "hydrology", "hydraulic", "boring",
        "design", "cost", "economics", "real estate", "environmental",
        "chief s report", "fonsi", "public notice", "permit", "dredging",
        "navigation", "mitigation", "study", "plan", "project document",
    )
    return is_direct_manifestation(url) or any(token in key for token in tokens)


def discover_family_links(html: str, *, parent_url: str, depth: int) -> list[FamilyLink]:
    """Over-discover report-family links; classification is not logical-document identity."""
    parser = _LinkParser()
    parser.feed(html)
    out: list[FamilyLink] = []
    seen: set[tuple[str, str]] = set()
    for href, text in parser.links:
        child = canonicalize_usace_url(urljoin(parent_url, href))
        split = urlsplit(child)
        if split.scheme not in {"http", "https"} or not split.netloc:
            continue
        if not looks_family_relevant(text, child):
            continue
        key = (child, text)
        if key in seen:
            continue
        seen.add(key)
        direct = is_direct_manifestation(child)
        out.append(
            FamilyLink(
                parent_url=parent_url,
                child_url_raw=href,
                child_url_canonical=child,
                anchor_text_raw=text,
                kind="DIRECT_MANIFESTATION" if direct else "DETAIL_OR_FAMILY_PAGE",
                depth=depth,
                state="DISCOVERED_NOT_IDENTITY",
            )
        )
    return out


def next_family_pages(
    links: Iterable[FamilyLink],
    *,
    current_host: str,
    visited: set[str],
) -> list[str]:
    """Recurse only into same-host detail pages; external direct files remain retrievable leaves."""
    out: list[str] = []
    for link in links:
        if link.kind != "DETAIL_OR_FAMILY_PAGE":
            continue
        split = urlsplit(link.child_url_canonical)
        if split.netloc.casefold() != current_host.casefold():
            continue
        if link.child_url_canonical in visited:
            continue
        out.append(link.child_url_canonical)
    return out


def family_arithmetic(rows: Iterable[FamilyLink], dispositions: dict[str, str]) -> dict[str, int]:
    """Close discovered family links into RETRIEVED/EXCLUDED/UNAVAILABLE/UNRESOLVED."""
    allowed = {"RETRIEVED", "EXCLUDED", "UNAVAILABLE", "UNRESOLVED"}
    counts = {state: 0 for state in allowed}
    total = 0
    for row in rows:
        total += 1
        state = dispositions.get(row.child_url_canonical, "UNRESOLVED")
        if state not in allowed:
            raise ValueError(f"invalid family disposition {state!r}")
        counts[state] += 1
    if total != sum(counts.values()):
        raise AssertionError("family arithmetic does not close")
    return {"family_total": total, **{state.lower(): counts[state] for state in sorted(allowed)}}


def serialize_links(rows: Iterable[FamilyLink]) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]
