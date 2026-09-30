#!/usr/bin/env python3
"""Freeze and ingest Puerto Rico DRNA beach-monitoring notifications.

The authoritative discovery surface is DRNA's Notificaciones Ambientales archive.
The crawler exhausts its pagination, freezes archive and notice bytes, classifies the
discovered Monitoria de Playas post denominator, and normalizes only the requested
publication year into the canonical hazard plane.

A BAV exceedance and an advisory are not treated as synonyms: a source page may carry
a separate primary-contact advisory even when a sample is below the BAV.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from aguayluz import DATA_DIR
from aguayluz.hazard_adapters.drna_beach import (
    ADVISORY_ALL_CLEAR,
    ADVISORY_BAV_EXCEEDANCE,
    ADVISORY_OTHER_WATER_QUALITY,
    BAV_ENTEROCOCCI_CFU_PER_100ML,
    normalize,
)
from aguayluz.hazard_plane import HazardRecord, Manifestation, current_records, source_arithmetic

CATEGORY_URL = (
    "https://www.drna.pr.gov/cat/programas-y-proyectos/"
    "monitoria-de-playas/notificaciones-ambientales/"
)
POST_RE = re.compile(r"/notificacion-monitoria-de-playas-\d+/?$", re.IGNORECASE)
PAGE_RE = re.compile(
    r"/cat/programas-y-proyectos/monitoria-de-playas/"
    r"notificaciones-ambientales/page/\d+/?$",
    re.IGNORECASE,
)
STATION_RE = re.compile(r"^RW-\d+[A-Z]?$", re.IGNORECASE)
USER_AGENT = "aguayluz-pr/0.1 DRNA-beach-freeze (github.com/jotaele44/aguayluz-pr)"
MONTHS = {
    "enero": 1,
    "ene": 1,
    "febrero": 2,
    "feb": 2,
    "marzo": 3,
    "mar": 3,
    "abril": 4,
    "abr": 4,
    "mayo": 5,
    "may": 5,
    "junio": 6,
    "jun": 6,
    "julio": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "septiembre": 9,
    "setiembre": 9,
    "sep": 9,
    "octubre": 10,
    "oct": 10,
    "noviembre": 11,
    "nov": 11,
    "diciembre": 12,
    "dic": 12,
}


@dataclass(frozen=True)
class FrozenPage:
    url: str
    raw: bytes
    headers: dict[str, str]
    kind: str


@dataclass(frozen=True)
class OutputPaths:
    raw_root: Path
    records: Path
    manifestations: Path
    ledger: Path
    receipt: Path


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.text_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.table_rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag.lower() == "meta":
            key = values.get("property") or values.get("name")
            content = values.get("content")
            if key and content:
                self.meta[key.lower()] = content
        if tag.lower() == "tr":
            self._row = []
        if tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.text_parts.append(text)
            if self._cell is not None:
                self._cell.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(_space(" ".join(self._cell)))
            self._cell = None
        if tag.lower() == "tr" and self._row is not None:
            if any(self._row):
                self.table_rows.append(self._row)
            self._row = None
            self._cell = None


def _space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _canonical_url(base: str, href: str) -> str | None:
    absolute = urljoin(base, href)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"drna.pr.gov", "www.drna.pr.gov"}:
        return None
    clean = parsed._replace(fragment="", query="")
    return urlunparse(clean)


def _parse_html(raw: bytes) -> PageParser:
    parser = PageParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def _schema_signature(parser: PageParser) -> str:
    payload = {
        "meta_keys": sorted(parser.meta),
        "table_column_counts": sorted({len(row) for row in parser.table_rows}),
        "has_article_published_time": "article:published_time" in parser.meta,
        "has_og_title": "og:title" in parser.meta,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _published_date(parser: PageParser) -> date | None:
    raw = parser.meta.get("article:published_time")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    text = _ascii(_space(" ".join(parser.text_parts))).casefold()
    match = re.search(
        r"\b(\d{1,2})\s+"
        r"(enero|ene|febrero|feb|marzo|mar|abril|abr|mayo|may|junio|jun|"
        r"julio|jul|agosto|ago|septiembre|setiembre|sep|octubre|oct|"
        r"noviembre|nov|diciembre|dic)\s+(\d{4})\b",
        text,
    )
    if not match:
        return None
    return date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))


def _sampling_dates(text: str) -> tuple[date | None, date | None]:
    normalized = _ascii(_space(text)).casefold()
    match = re.search(
        r"resultados?\s+de\s+los\s+muestreos?.{0,80}?\bdel\s+"
        r"(\d{1,2})(?:\s*(?:y|,)\s*(\d{1,2}))?\s+de\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})",
        normalized,
    )
    if not match:
        return None, None
    first = int(match.group(1))
    second = int(match.group(2) or first)
    month = MONTHS[match.group(3)]
    year = int(match.group(4))
    return date(year, month, first), date(year, month, second)


def _station_rows(parser: PageParser) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for row in parser.table_rows:
        if len(row) < 3:
            continue
        station = _space(row[0]).upper()
        if not STATION_RE.fullmatch(station):
            continue
        rows.append((station, _space(row[1]), _space(row[2])))
    return rows


def _special_advisories(text: str) -> list[tuple[str, str]]:
    compact = _space(text)
    pattern = re.compile(
        r"No\s+se\s+recomienda\s+el\s+uso\s+de\s+la\s+"
        r"(.+?)\s+para\s+contacto\s+primario,?\s+debido\s+a\s+"
        r"(.+?)(?=De\s+requerir|Muchas\s+gracias|Monitoria\s+de\s+Playas|$)",
        re.IGNORECASE,
    )
    return [(_space(match.group(1)), _space(match.group(2))) for match in pattern.finditer(compact)]


def _post_id(url: str) -> str:
    return Path(urlparse(url).path.rstrip("/")).name


def parse_notice(raw: bytes, url: str) -> tuple[date | None, list[dict[str, Any]], str | None]:
    parser = _parse_html(raw)
    published = _published_date(parser)
    full_text = _space(" ".join(parser.text_parts))
    normalized = _ascii(full_text).casefold()
    sample_start, sample_end = _sampling_dates(full_text)
    post_id = _post_id(url)
    rows: list[dict[str, Any]] = []

    station_rows = _station_rows(parser)
    has_bav_advisory = (
        "no son aptas para banistas" in normalized
        and "beach action value" in normalized
        and "enterococos" in normalized
    )
    if station_rows and not has_bav_advisory:
        return published, [], "STATION_TABLE_WITHOUT_RECOGNIZED_BAV_ADVISORY"

    for station_id, beach_name, municipality in station_rows:
        rows.append(
            {
                "post_id": post_id,
                "post_url": url,
                "source_record_id": f"{post_id}:{station_id}",
                "station_id": station_id,
                "beach_name": beach_name,
                "municipality_raw": municipality,
                "indicator": "Enterococci",
                "bav_value": BAV_ENTEROCOCCI_CFU_PER_100ML,
                "bav_unit": "colonies/100 mL",
                "sample_date_start": sample_start.isoformat() if sample_start else None,
                "sample_date_end": sample_end.isoformat() if sample_end else None,
                "published_at": published.isoformat() if published else None,
                "advisory_state": ADVISORY_BAV_EXCEEDANCE,
                "advisory_reason_raw": "Beach Action Value exceedance for Enterococci",
                "title_raw": f"{beach_name} not suitable for bathers",
                "description_raw": None,
                "source_excerpt": full_text[:600],
            }
        )

    for beach_name, reason in _special_advisories(full_text):
        rows.append(
            {
                "post_id": post_id,
                "post_url": url,
                "source_record_id": f"{post_id}:NOTE:{sha256(beach_name.encode('utf-8')).hexdigest()[:12]}",
                "station_id": None,
                "beach_name": beach_name,
                "municipality_raw": None,
                "indicator": None,
                "bav_value": None,
                "bav_unit": None,
                "sample_date_start": sample_start.isoformat() if sample_start else None,
                "sample_date_end": sample_end.isoformat() if sample_end else None,
                "published_at": published.isoformat() if published else None,
                "advisory_state": ADVISORY_OTHER_WATER_QUALITY,
                "advisory_reason_raw": reason,
                "title_raw": f"{beach_name}: primary contact not recommended",
                "description_raw": reason,
                "source_excerpt": full_text[:600],
            }
        )

    if "se encuentran aptas para banistas" in normalized:
        rows.append(
            {
                "post_id": post_id,
                "post_url": url,
                "source_record_id": f"{post_id}:ALL_MONITORED",
                "station_id": None,
                "beach_name": None,
                "municipality_raw": None,
                "indicator": "Enterococci",
                "bav_value": BAV_ENTEROCOCCI_CFU_PER_100ML,
                "bav_unit": "colonies/100 mL",
                "sample_date_start": sample_start.isoformat() if sample_start else None,
                "sample_date_end": sample_end.isoformat() if sample_end else None,
                "published_at": published.isoformat() if published else None,
                "advisory_state": ADVISORY_ALL_CLEAR,
                "advisory_reason_raw": "All beaches in the DRNA Beach Program suitable for bathers",
                "title_raw": "All monitored DRNA beaches suitable for bathers",
                "description_raw": None,
                "source_excerpt": full_text[:600],
            }
        )

    if not rows:
        return published, [], "NO_RECOGNIZED_BEACH_ADVISORY_SEMANTICS"
    if sample_start is None:
        return published, rows, "SAMPLING_DATE_UNRESOLVED"
    return published, rows, None


def _output_paths(output_root: Path | None) -> OutputPaths:
    if output_root is None:
        return OutputPaths(
            raw_root=DATA_DIR / "hazard_source_snapshots" / "drna_beach_monitoring",
            records=DATA_DIR / "hazard_records.jsonl",
            manifestations=DATA_DIR / "hazard_manifestations.jsonl",
            ledger=DATA_DIR / "hazard_source_accounting.jsonl",
            receipt=DATA_DIR / "drna_beach_source_receipt.json",
        )
    return OutputPaths(
        raw_root=output_root / "raw",
        records=output_root / "hazard_records.jsonl",
        manifestations=output_root / "hazard_manifestations.jsonl",
        ledger=output_root / "hazard_source_accounting.jsonl",
        receipt=output_root / "receipt.json",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _append_unique_jsonl(path: Path, rows: list[dict[str, Any]], key: str) -> int:
    existing = _read_jsonl(path)
    by_key = {str(row[key]): row for row in existing if row.get(key) is not None}
    before = len(by_key)
    for row in rows:
        row_key = str(row[key])
        prior = by_key.get(row_key)
        if prior is not None and prior != row:
            raise ValueError(f"identity collision for {key}={row_key}")
        by_key[row_key] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(by_key.values(), key=lambda row: str(row[key]))
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ordered),
        encoding="utf-8",
    )
    return len(by_key) - before


def _existing_current_by_event(path: Path) -> dict[str, HazardRecord]:
    records = [HazardRecord.model_validate(row) for row in _read_jsonl(path)]
    result: dict[str, HazardRecord] = {}
    for row in current_records(records):
        prior = result.get(row.canonical_event_id)
        if prior is not None and prior.record_id != row.record_id:
            raise ValueError(f"multiple current revisions for {row.canonical_event_id}")
        result[row.canonical_event_id] = row
    return result


def _fetch(client: httpx.Client, url: str) -> FrozenPage:
    response = client.get(url)
    response.raise_for_status()
    if not response.content:
        raise ValueError(f"empty DRNA response: {url}")
    return FrozenPage(
        url=str(response.url),
        raw=response.content,
        headers={key.lower(): value for key, value in response.headers.items()},
        kind="page",
    )


def crawl_archive(client: httpx.Client, max_pages: int) -> tuple[list[FrozenPage], list[str]]:
    queue: deque[str] = deque([CATEGORY_URL])
    seen: set[str] = set()
    archive_pages: list[FrozenPage] = []
    candidates: set[str] = set()

    while queue:
        if len(seen) >= max_pages:
            raise ValueError(f"archive pagination did not exhaust within max_pages={max_pages}")
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        page = _fetch(client, url)
        archive_pages.append(FrozenPage(page.url, page.raw, page.headers, "archive"))
        parser = _parse_html(page.raw)
        for href in parser.hrefs:
            canonical = _canonical_url(page.url, href)
            if canonical is None:
                continue
            path = urlparse(canonical).path
            if POST_RE.search(path):
                candidates.add(canonical)
            elif PAGE_RE.search(path) and canonical not in seen:
                queue.append(canonical)

    return archive_pages, sorted(candidates)


def _manifestation(page: FrozenPage, retrieved_at: datetime, ordinal: int) -> Manifestation:
    page_sha = sha256(page.raw).hexdigest()
    parser = _parse_html(page.raw)
    if page.kind == "notice":
        source_record_id = _post_id(page.url)
    else:
        source_record_id = f"archive-{ordinal:04d}"
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    return Manifestation(
        manifestation_id=f"DRNA_BEACH:{stamp}:{page.kind.upper()}:{ordinal:04d}:{page_sha[:20]}",
        source_authority="Puerto Rico DRNA",
        source_system="DRNA Beach Monitoring public notifications",
        source_record_id=source_record_id,
        source_url=page.url,
        retrieval_query=None,
        retrieved_at_utc=retrieved_at,
        byte_sha256=page_sha,
        schema_signature=_schema_signature(parser),
        record_count=len(_station_rows(parser)) if page.kind == "notice" else None,
        http_etag=page.headers.get("etag"),
        http_last_modified=page.headers.get("last-modified"),
    )


def _freeze_raw(paths: OutputPaths, page: FrozenPage, manifestation: Manifestation) -> None:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", manifestation.source_record_id)
    target = paths.raw_root / f"{manifestation.manifestation_id}_{safe}.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != page.raw:
        raise ValueError(f"raw snapshot collision at {target}")
    target.write_bytes(page.raw)


def run(
    *,
    year: int,
    output_root: Path | None,
    max_pages: int,
    require_zero_unresolved: bool,
) -> dict[str, Any]:
    paths = _output_paths(output_root)
    retrieved_at = datetime.now(timezone.utc)
    existing_current = _existing_current_by_event(paths.records)
    manifestations: list[Manifestation] = []
    new_records: list[HazardRecord] = []
    classifications: list[dict[str, Any]] = []

    with httpx.Client(
        timeout=45,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        archive_pages, candidate_urls = crawl_archive(client, max_pages=max_pages)
        ordinal = 0
        for page in archive_pages:
            ordinal += 1
            manifestation = _manifestation(page, retrieved_at, ordinal)
            manifestations.append(manifestation)
            _freeze_raw(paths, page, manifestation)

        for url in candidate_urls:
            ordinal += 1
            try:
                fetched = _fetch(client, url)
            except (httpx.HTTPError, ValueError) as exc:
                classifications.append(
                    {
                        "url": url,
                        "disposition": "UNRESOLVED",
                        "reason": f"FETCH_FAILED:{type(exc).__name__}",
                    }
                )
                continue

            page = FrozenPage(fetched.url, fetched.raw, fetched.headers, "notice")
            manifestation = _manifestation(page, retrieved_at, ordinal)
            manifestations.append(manifestation)
            _freeze_raw(paths, page, manifestation)

            published, parsed_rows, parse_issue = parse_notice(page.raw, page.url)
            if published is None:
                classifications.append(
                    {
                        "url": page.url,
                        "manifestation_id": manifestation.manifestation_id,
                        "disposition": "UNRESOLVED",
                        "reason": "PUBLICATION_DATE_UNRESOLVED",
                    }
                )
                continue
            if published.year != year:
                classifications.append(
                    {
                        "url": page.url,
                        "manifestation_id": manifestation.manifestation_id,
                        "published_date": published.isoformat(),
                        "disposition": "EXCLUDED",
                        "reason": f"OUTSIDE_TARGET_YEAR_{year}",
                    }
                )
                continue
            if parse_issue is not None:
                classifications.append(
                    {
                        "url": page.url,
                        "manifestation_id": manifestation.manifestation_id,
                        "published_date": published.isoformat(),
                        "disposition": "UNRESOLVED",
                        "reason": parse_issue,
                        "parsed_record_count": len(parsed_rows),
                    }
                )
                continue

            classifications.append(
                {
                    "url": page.url,
                    "manifestation_id": manifestation.manifestation_id,
                    "published_date": published.isoformat(),
                    "disposition": "RETAINED",
                    "record_count": len(parsed_rows),
                }
            )
            for source_row in parsed_rows:
                candidate = normalize(source_row, manifestation.manifestation_id)
                previous = existing_current.get(candidate.canonical_event_id)
                if previous is not None:
                    if previous.record_id == candidate.record_id:
                        continue
                    candidate = normalize(
                        source_row,
                        manifestation.manifestation_id,
                        supersedes_record_id=previous.record_id,
                    )
                new_records.append(candidate)
                existing_current[candidate.canonical_event_id] = candidate

    retained = sum(row["disposition"] == "RETAINED" for row in classifications)
    excluded = sum(row["disposition"] == "EXCLUDED" for row in classifications)
    unresolved = sum(row["disposition"] == "UNRESOLVED" for row in classifications)
    accounting = source_arithmetic(len(classifications), retained, excluded, unresolved)
    receipt = {
        "schema_version": "aguayluz.drna_beach_source_freeze/v1",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "target_year": year,
        "archive_url": CATEGORY_URL,
        "archive_pages_frozen": len(archive_pages),
        "discovered_notice_urls": len(candidate_urls),
        "manifestations_frozen": len(manifestations),
        "new_record_revisions": len(new_records),
        "source_arithmetic": accounting,
        "certification_state": (
            "PASS"
            if accounting["state"] == "PASS" and unresolved == 0
            else "OPEN"
        ),
        "classifications": classifications,
    }
    if accounting["state"] != "PASS":
        raise ValueError(f"source arithmetic failed: {accounting}")

    _append_unique_jsonl(
        paths.manifestations,
        [row.model_dump(mode="json") for row in manifestations],
        "manifestation_id",
    )
    _append_unique_jsonl(
        paths.records,
        [row.model_dump(mode="json") for row in new_records],
        "record_id",
    )
    paths.ledger.parent.mkdir(parents=True, exist_ok=True)
    with paths.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    paths.receipt.parent.mkdir(parents=True, exist_ok=True)
    paths.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if require_zero_unresolved and unresolved:
        raise ValueError(f"DRNA source denominator has {unresolved} unresolved notice(s)")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--require-zero-unresolved", action="store_true")
    args = parser.parse_args()
    try:
        receipt = run(
            year=args.year,
            output_root=args.output_root,
            max_pages=args.max_pages,
            require_zero_unresolved=args.require_zero_unresolved,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"DRNA beach ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
