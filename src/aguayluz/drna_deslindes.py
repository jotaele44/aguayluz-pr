"""Authoritative DRNA ZMT deslinde acquisition and state-transition detection.

Social/news/search material is discovery only. Administrative approval is emitted only
when a DRNA-approved detail manifestation contains both a stable permit identifier and
an explicit certified date. Parcel/ZMT/servidumbre geometry identity is outside this
module and must be adjudicated independently.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urljoin, urlparse

import httpx

APPROVED_LISTING_URL = "https://www.drna.pr.gov/deslindes-zmt-aprobados/"
APPROVED_PATH_FRAGMENT = "/deslindes-zmt/deslindes-zmt-aprobados/"
APPROVED_LISTING_PATH = "/deslindes-zmt-aprobados/"
_ALLOWED_HOSTS = {"drna.pr.gov", "www.drna.pr.gov"}
_PERMIT_RE = re.compile(r"\b[AO]-AG-CER02-[A-Z]{2}-\d{5}-\d{8}\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b")
_SPANISH_DATE_RE = re.compile(
    r"\b(\d{1,2})[-\s]+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)[-\s]+(\d{4})\b",
    re.IGNORECASE,
)
_PAGE_RE = re.compile(r"/deslindes-zmt-aprobados/page/(\d+)/?$")
_MONTHS = {
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
    """Raised when an alleged authoritative acquisition cannot satisfy hard gates."""


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


def _authoritative_listing_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        return False
    return parsed.path == APPROVED_LISTING_PATH or bool(_PAGE_RE.fullmatch(parsed.path))


def _text_from_html(raw_html: str) -> str:
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


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    numeric = _DATE_RE.search(value)
    if numeric:
        day, month, year = map(int, numeric.groups())
    else:
        spanish = _SPANISH_DATE_RE.search(value)
        if not spanish:
            return None
        day = int(spanish.group(1))
        month = _MONTHS[spanish.group(2).casefold()]
        year = int(spanish.group(3))
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _store_cas(raw_bytes: bytes, cas_dir: Path | None) -> str:
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if cas_dir is not None:
        path = cas_dir / digest[:2] / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw_bytes)
        elif path.read_bytes() != raw_bytes:
            raise DeslindeParseError("CAS hash collision or corrupted existing payload")
    return digest


def parse_approved_notice(
    raw_bytes: bytes,
    source_url: str,
    retrieved_at: datetime | None = None,
    cas_dir: Path | None = None,
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
        raise DeslindeParseError("approved notice lacks an explicit valid certified date")

    publication_raw = _field(
        text,
        ("fecha de publicación del aviso", "fecha de publicacion del aviso"),
    )
    digest = _store_cas(raw_bytes, cas_dir)

    manifestation = SourceManifestation(
        source_url=source_url,
        retrieved_at=retrieved.isoformat().replace("+00:00", "Z"),
        sha256=digest,
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


def _links(document: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(document)
    return parser.links


def discover_detail_urls(listing_html: str, listing_url: str = APPROVED_LISTING_URL) -> list[str]:
    """Discover approved-detail URLs. Discovery alone is not approval evidence."""
    urls = {
        urljoin(listing_url, href)
        for href in _links(listing_html)
        if _authoritative_detail_url(urljoin(listing_url, href))
    }
    return sorted(urls)


def discover_listing_pages(listing_html: str, listing_url: str = APPROVED_LISTING_URL) -> list[str]:
    """Discover authoritative numbered listing pages without assuming they resolve."""
    pages = {
        urljoin(listing_url, href)
        for href in _links(listing_html)
        if _authoritative_listing_url(urljoin(listing_url, href))
    }
    pages.add(APPROVED_LISTING_URL)
    return sorted(pages, key=lambda value: (0 if value == APPROVED_LISTING_URL else int(_PAGE_RE.search(urlparse(value).path).group(1))))


def _validate_unique_permits(records: Sequence[DeslindeRecord]) -> None:
    seen: dict[str, str] = {}
    for record in records:
        prior_url = seen.get(record.permit_number)
        if prior_url is not None and prior_url != record.source.source_url:
            raise DeslindeParseError(
                f"duplicate permit {record.permit_number} published at distinct detail URLs: "
                f"{prior_url} | {record.source.source_url}"
            )
        seen[record.permit_number] = record.source.source_url


def fetch_current_records(
    client: httpx.Client | None = None,
    listing_url: str = APPROVED_LISTING_URL,
    timeout_seconds: float = 20.0,
    cas_dir: Path | None = None,
) -> list[DeslindeRecord]:
    """Fetch all currently reachable listing pages and authoritative detail notices.

    Pagination is a certification gate. A numbered listing URL redirecting outside the
    approved-listing family causes a fail-closed error rather than silent truncation.
    """
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        first = http.get(listing_url)
        first.raise_for_status()
        if not _authoritative_listing_url(str(first.url)):
            raise DeslindeParseError("base approved-listing request redirected outside listing family")
        _store_cas(first.content, cas_dir)

        listing_pages = discover_listing_pages(first.text, str(first.url))
        detail_urls: set[str] = set(discover_detail_urls(first.text, str(first.url)))

        for page_url in listing_pages:
            if page_url == APPROVED_LISTING_URL:
                continue
            response = http.get(page_url)
            response.raise_for_status()
            resolved = str(response.url)
            if not _authoritative_listing_url(resolved):
                raise DeslindeParseError(
                    f"pagination source redirected outside approved-listing family: "
                    f"{page_url} -> {resolved}"
                )
            _store_cas(response.content, cas_dir)
            detail_urls.update(discover_detail_urls(response.text, resolved))

        records: list[DeslindeRecord] = []
        for url in sorted(detail_urls):
            response = http.get(url)
            response.raise_for_status()
            resolved = str(response.url)
            if not _authoritative_detail_url(resolved):
                raise DeslindeParseError(
                    f"approved-detail request redirected outside authoritative detail family: "
                    f"{url} -> {resolved}"
                )
            records.append(parse_approved_notice(response.content, resolved, cas_dir=cas_dir))

        _validate_unique_permits(records)
        return sorted(records, key=lambda record: record.permit_number)
    finally:
        if owns_client:
            http.close()


def diff_records(previous: Iterable[DeslindeRecord], current: Iterable[DeslindeRecord]) -> list[DeslindeEvent]:
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
    """Persist a deterministic logical snapshot; source hashes remain in each record."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(record) for record in sorted(records, key=lambda item: item.permit_number)]
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return destination


def load_snapshot(path: Path) -> list[DeslindeRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records: list[DeslindeRecord] = []
    for raw_item in payload:
        item = dict(raw_item)
        source = SourceManifestation(**item.pop("source"))
        records.append(DeslindeRecord(source=source, **item))
    _validate_unique_permits(records)
    return records
