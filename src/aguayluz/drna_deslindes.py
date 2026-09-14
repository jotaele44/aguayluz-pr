"""Authoritative DRNA ZMT deslinde acquisition and state-transition detection.

This module treats social/news/search material as discovery only. Administrative
approval is emitted only when a DRNA-approved listing manifestation contains both a
stable permit identifier and an explicit certified date. Geometry identity is outside
this module and must be adjudicated independently.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urljoin, urlparse

import httpx

APPROVED_LISTING_URL = "https://www.drna.pr.gov/deslindes-zmt-aprobados/"
APPROVED_PATH_FRAGMENT = "/deslindes-zmt/deslindes-zmt-aprobados/"
_ALLOWED_HOSTS = {"drna.pr.gov", "www.drna.pr.gov"}
_PERMIT_RE = re.compile(r"\b[AO]-AG-CER02-[A-Z]{2}-\d{5}-\d{8}\b", re.IGNORECASE)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b")
_WORD_DATE_RE = re.compile(r"\b(\d{1,2})[-/\s]+([A-Za-z\u00c0-\u017f]+)[-/\s]+(\d{4})\b")
_SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


class DeslindeParseError(ValueError):
    """Raised when an alleged approved notice cannot satisfy authoritative gates."""


@dataclass(frozen=True, slots=True)
class SourceManifestation:
    source_url: str
    retrieved_at: str
    sha256: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class DeslindeRecord:
    permit_number: str
    status: str
    certified_date: str
    publication_date: str | None
    proponent_raw: str | None
    owner_raw: str | None
    address_raw: str | None
    purpose_raw: str | None
    source: SourceManifestation


@dataclass(frozen=True, slots=True)
class DeslindeEvent:
    event_type: str
    permit_number: str
    previous: DeslindeRecord | None
    current: DeslindeRecord | None
    rationale: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def _authoritative_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_HOSTS
        and APPROVED_PATH_FRAGMENT in parsed.path
    )


def _text_from_html(raw_html: str) -> str:
    # Preserve source bytes separately; this normalization is parsing-only.
    without_tags = re.sub(r"<[^>]+>", "\n", raw_html)
    decoded = html.unescape(without_tags)
    lines = [re.sub(r"\s+", " ", line).strip() for line in decoded.splitlines()]
    return "\n".join(line for line in lines if line)


def _field(text: str, labels: Sequence[str]) -> str | None:
    lines = text.splitlines()
    normalized_labels = tuple(label.casefold() for label in labels)
    for index, line in enumerate(lines):
        folded = line.casefold()
        if not any(folded.startswith(label) for label in normalized_labels):
            continue
        if ":" in line:
            value = line.split(":", 1)[1].strip()
            if value:
                return value
        if index + 1 < len(lines):
            candidate = lines[index + 1].strip()
            if candidate:
                return candidate
    return None


def _fold_ascii(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _format_valid_date(day: int, month: int, year: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None

    numeric = _NUMERIC_DATE_RE.search(value)
    if numeric:
        day, month, year = map(int, numeric.groups())
        return _format_valid_date(day, month, year)

    word = _WORD_DATE_RE.search(value)
    if not word:
        return None
    day_raw, month_raw, year_raw = word.groups()
    month = _SPANISH_MONTHS.get(_fold_ascii(month_raw))
    if month is None:
        return None
    return _format_valid_date(int(day_raw), month, int(year_raw))


def parse_approved_notice(
    raw_bytes: bytes,
    source_url: str,
    retrieved_at: datetime | None = None,
) -> DeslindeRecord:
    """Parse one DRNA approved-deslinde notice under fail-closed authority rules."""
    if not _authoritative_detail_url(source_url):
        raise DeslindeParseError(
            "source URL is not an authoritative DRNA approved-deslinde detail path"
        )

    retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw_html = raw_bytes.decode("utf-8", errors="replace")
    text = _text_from_html(raw_html)

    permit_match = _PERMIT_RE.search(text)
    if not permit_match:
        raise DeslindeParseError("approved notice lacks stable DRNA permit identifier")
    permit_number = permit_match.group(0).upper()

    certified_raw = _field(
        text,
        (
            "fecha deslinde certificado",
            "deslinde certificado",
            "fecha de deslinde certificado",
        ),
    )
    certified_date = _iso_date(certified_raw)
    if certified_date is None:
        raise DeslindeParseError("approved notice lacks an explicit parseable certified date")

    publication_raw = _field(
        text,
        ("fecha de publicación del aviso", "fecha de publicacion del aviso"),
    )

    manifestation = SourceManifestation(
        source_url=source_url,
        retrieved_at=retrieved.isoformat().replace("+00:00", "Z"),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        byte_count=len(raw_bytes),
    )
    return DeslindeRecord(
        permit_number=permit_number,
        status="APPROVED",
        certified_date=certified_date,
        publication_date=_iso_date(publication_raw),
        proponent_raw=_field(text, ("promovente",)),
        owner_raw=_field(text, ("propietario",)),
        address_raw=_field(text, ("dirección", "direccion")),
        purpose_raw=_field(text, ("propósito", "proposito")),
        source=manifestation,
    )


def discover_detail_urls(
    listing_html: str,
    listing_url: str = APPROVED_LISTING_URL,
) -> list[str]:
    """Discover DRNA approved-detail URLs. Discovery is not itself approval evidence."""
    parser = _LinkParser()
    parser.feed(listing_html)
    urls = {
        urljoin(listing_url, href)
        for href in parser.links
        if _authoritative_detail_url(urljoin(listing_url, href))
    }
    return sorted(urls)


def fetch_current_records(
    client: httpx.Client | None = None,
    listing_url: str = APPROVED_LISTING_URL,
    timeout_seconds: float = 20.0,
) -> list[DeslindeRecord]:
    """Fetch the current bounded DRNA listing and authoritative detail notices."""
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        listing_response = http.get(listing_url)
        listing_response.raise_for_status()
        urls = discover_detail_urls(listing_response.text, listing_url)
        records: list[DeslindeRecord] = []
        for url in urls:
            response = http.get(url)
            response.raise_for_status()
            records.append(parse_approved_notice(response.content, str(response.url)))
        return sorted(records, key=lambda record: record.permit_number)
    finally:
        if owns_client:
            http.close()


def diff_records(
    previous: Iterable[DeslindeRecord],
    current: Iterable[DeslindeRecord],
) -> list[DeslindeEvent]:
    """Diff snapshots without converting source absence into a legal-status inference."""
    previous_by_id = {record.permit_number: record for record in previous}
    current_by_id = {record.permit_number: record for record in current}
    events: list[DeslindeEvent] = []

    for permit_number in sorted(current_by_id.keys() - previous_by_id.keys()):
        events.append(
            DeslindeEvent(
                event_type="DESLINDE_APPROVED",
                permit_number=permit_number,
                previous=None,
                current=current_by_id[permit_number],
                rationale=(
                    "new stable permit identifier appeared in authoritative DRNA approved "
                    "listing with explicit certified date"
                ),
            )
        )

    for permit_number in sorted(current_by_id.keys() & previous_by_id.keys()):
        before = previous_by_id[permit_number]
        after = current_by_id[permit_number]
        comparable_before = (
            before.certified_date,
            before.publication_date,
            before.proponent_raw,
            before.owner_raw,
            before.address_raw,
            before.purpose_raw,
        )
        comparable_after = (
            after.certified_date,
            after.publication_date,
            after.proponent_raw,
            after.owner_raw,
            after.address_raw,
            after.purpose_raw,
        )
        if comparable_before != comparable_after:
            events.append(
                DeslindeEvent(
                    event_type="SOURCE_MANIFESTATION_CHANGED",
                    permit_number=permit_number,
                    previous=before,
                    current=after,
                    rationale=(
                        "same stable permit identifier has changed authoritative published "
                        "fields; legal effect requires adjudication"
                    ),
                )
            )

    for permit_number in sorted(previous_by_id.keys() - current_by_id.keys()):
        events.append(
            DeslindeEvent(
                event_type="SOURCE_ABSENCE",
                permit_number=permit_number,
                previous=previous_by_id[permit_number],
                current=None,
                rationale=(
                    "previously observed permit is absent from current discovery result; "
                    "no revocation/denial inference permitted"
                ),
            )
        )

    return events


def freeze_snapshot(records: Sequence[DeslindeRecord], destination: Path) -> Path:
    """Persist a deterministic logical snapshot; raw-source hashes remain in each record."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(record) for record in sorted(records, key=lambda item: item.permit_number)]
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def load_snapshot(path: Path) -> list[DeslindeRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records: list[DeslindeRecord] = []
    for item in payload:
        source = SourceManifestation(**item.pop("source"))
        records.append(DeslindeRecord(source=source, **item))
    return records
