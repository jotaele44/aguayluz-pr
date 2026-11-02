#!/usr/bin/env python3
"""Governed LUMA Monthly Generation Performance Report source adapter.

This adapter treats the LUMA BPS index as the authoritative discovery denominator and
month/year URL synthesis as discovery-only fallback. It never proves source identity from
month/year, title, URL proximity, HTTP status, or source absence.

Modes
-----
backfill:
    Crawl the full authoritative index, build the expected month denominator from
    2023-01 through the latest indexed report, acquire every discovered manifestation,
    and use synthesized landing-page URLs only for index gaps.

incremental:
    Crawl the full index, compare discovery sets against the prior manifest, and recheck
    the latest N periods plus any historical period whose indexed URL set changed or whose
    previous acquisition state was not PASS.

replay:
    Perform a network-free adversarial replay over frozen bytes: PDF signatures, hashes,
    byte counts, page counts, rendered-page hashes, typed-unit classifications, row
    conservation, duplicate/multiple-manifestation state, and archive determinism inputs.

Evidence model
--------------
INDEX ENTRY       = authoritative manifestation discovery, not document bytes.
LANDING PAGE      = discovery metadata, not PDF bytes.
PDF URL           = discovery reference, not PDF bytes.
FROZEN PDF BYTES  = source manifestation; SHA-256 proves byte identity only.
PAGE CONTENT      = claim evidence only after typed metric/scope adjudication.

Automatic negative classification is bounded. HYDRO_ABSENT is never certification-eligible
unless every page has both parse and render evidence; even then the receipt records that
visual semantic review is still required before claiming universal absence.

RAW / NORMALIZED / CANONICAL are emitted separately. Canonical claims are intentionally
conservative: no plant/unit identity is promoted from name-only evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

SCHEMA_VERSION = "luma_monthly_generation_adapter/v1"
DEFAULT_INDEX_URLS = (
    "https://lumapr.com/monitoreo-de-bps/",
    "https://lumapr.com/bps-monitoring/?lang=en",
)
DEFAULT_START_PERIOD = "2023-01"
DEFAULT_INCREMENTAL_MONTHS = 3
DEFAULT_TIMEOUT = 90.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_S = 0.75
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "AguaYLuz-LUMA-Monthly-Adapter/1.0"
)
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8,es;q=0.7",
    "Cache-Control": "no-cache",
}
MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
MONTH_NUMBER = {m: i + 1 for i, m in enumerate(MONTHS)}
MONTH_NAME = {i + 1: m for i, m in enumerate(MONTHS)}
REPORT_TITLE_RE = re.compile(
    r"(?i)\b("
    + "|".join(MONTHS)
    + r")\s+(\d{4})\b.*?\bmonthly\s+generation\s+performance\s+report\b"
)
PERIOD_ANY_RE = re.compile(r"(?i)\b(" + "|".join(MONTHS) + r")[-\s_]+(\d{4})\b")
PDF_HREF_RE = re.compile(r"(?i)\.pdf(?:$|[?#])")
HYDRO_TERMS = (
    "hydro", "hydroelectric", "hydroco", "caonillas", "dos bocas", "garzas",
    "patillas", "rio blanco", "río blanco", "toro negro", "yauco",
)
GENERATION_TERMS = (
    "generation", "net generation", "total generation", "generación", "producción",
    "production",
)
OTHER_METRIC_TERMS = (
    "availability", "capacity factor", "forced outage", "maintenance outage",
    "planned outage", "heat rate", "fuel", "variable cost",
)
UNIT_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?P<unit>GWh|MWh|kWh|MW|kW|GW|%)(?![A-Za-z])",
    re.IGNORECASE,
)
NUMBER_UNIT_RE = re.compile(
    r"(?P<value>[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?)\s*"
    r"(?P<unit>GWh|MWh|kWh|MW|kW|GW|%)(?![A-Za-z])",
    re.IGNORECASE,
)
PDF_MAGIC = b"%PDF-"
RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})
STATUS_PASS = "PASS"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
STATUS_NOT_LISTED = "NOT_LISTED"
CLASSIFICATIONS = {
    "HYDRO_MWH_PRESENT",
    "HYDRO_MW_ONLY",
    "HYDRO_OTHER_METRIC",
    "HYDRO_ABSENT",
    "UNRESOLVED",
}


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Period:
    year: int
    month: int

    def __post_init__(self) -> None:
        if self.year < 1900 or self.year > 2200:
            raise ValueError(f"invalid year: {self.year}")
        if not 1 <= self.month <= 12:
            raise ValueError(f"invalid month: {self.month}")

    @classmethod
    def parse(cls, text: str) -> "Period":
        m = re.fullmatch(r"(\d{4})-(\d{2})", text.strip())
        if not m:
            raise ValueError(f"period must be YYYY-MM: {text!r}")
        return cls(int(m.group(1)), int(m.group(2)))

    @classmethod
    def from_month_name(cls, month_name: str, year: str | int) -> "Period":
        key = month_name.strip().lower()
        if key not in MONTH_NUMBER:
            raise ValueError(f"unknown month: {month_name!r}")
        return cls(int(year), MONTH_NUMBER[key])

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def month_name(self) -> str:
        return MONTH_NAME[self.month]

    def next(self) -> "Period":
        if self.month == 12:
            return Period(self.year + 1, 1)
        return Period(self.year, self.month + 1)


@dataclass
class DiscoveryEntry:
    period: str
    href: str
    title_raw: str
    index_url: str
    discovery_class: str = "AUTHORITATIVE_INDEX_ENTRY"


@dataclass
class FetchResult:
    requested_url: str
    final_url: str | None = None
    status: str = STATUS_UNRESOLVED
    http_status: int | None = None
    content_type: str | None = None
    last_modified: str | None = None
    etag: str | None = None
    retrieval_utc: str | None = None
    body: bytes | None = None
    error: str | None = None


@dataclass
class ManifestRow:
    schema_version: str
    period: str
    manifestation_key: str
    discovery_class: str
    index_url: str | None
    index_title_raw: str | None
    indexed_href: str | None
    synthesized_landing_url: str
    landing_url: str | None
    pdf_url: str | None
    publication_date: str | None
    retrieval_utc: str | None
    source_state: str
    http_status: int | None
    content_type: str | None
    last_modified: str | None
    etag: str | None
    raw_path: str | None
    byte_count: int | None
    sha256: str | None
    pdf_signature_valid: bool | None
    page_count: int | None
    parsed_page_count: int | None
    rendered_page_count: int | None
    page_complete_parse: bool | None
    page_complete_render: bool | None
    hydro_classification: str
    negative_page_complete_ready: bool
    negative_certification_eligible: bool
    prior_manifestation_relation: str
    notes: list[str] = field(default_factory=list)


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._href: str | None = None
        self._text: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.publication_dates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag.lower() == "meta":
            key = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            if key in {
                "article:published_time",
                "article:modified_time",
                "date",
                "datepublished",
                "publish-date",
            }:
                value = attrs_dict.get("content")
                if value:
                    self.publication_dates.append(value)
            return
        if tag.lower() == "time":
            value = attrs_dict.get("datetime")
            if value:
                self.publication_dates.append(value)
            return
        if tag.lower() != "a":
            return
        self._href = attrs_dict.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(canonical_json(row) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AdapterError(f"{path}:{i}: expected object")
        out.append(value)
    return out


def iter_periods(start: Period, end: Period) -> Iterator[Period]:
    cur = start
    while cur <= end:
        yield cur
        cur = cur.next()


def synthesized_landing_url(period: Period) -> str:
    return (
        "https://lumapr.com/so_document/"
        f"{period.month_name}-{period.year}-monthly-generation-performance-report/"
    )


def parse_index_entries(html: str, index_url: str) -> list[DiscoveryEntry]:
    parser = AnchorParser()
    parser.feed(html)
    rows: list[DiscoveryEntry] = []
    seen: set[tuple[str, str]] = set()
    for href, title in parser.anchors:
        absolute = urllib.parse.urljoin(index_url, href)
        haystack = " ".join((title, absolute))
        match = REPORT_TITLE_RE.search(haystack)
        if not match:
            # Some WordPress anchors carry only href slugs.
            slug_match = re.search(
                r"(?i)/(?:so_document/)?(" + "|".join(MONTHS) + r")-(\d{4})-"
                r"monthly-generation-performance-report(?:/|$)",
                urllib.parse.urlparse(absolute).path,
            )
            if not slug_match:
                continue
            period = Period.from_month_name(slug_match.group(1), slug_match.group(2))
        else:
            period = Period.from_month_name(match.group(1), match.group(2))
        key = (str(period), absolute)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            DiscoveryEntry(
                period=str(period),
                href=absolute,
                title_raw=title,
                index_url=index_url,
            )
        )
    return sorted(rows, key=lambda x: (x.period, x.href))


def index_period_map(entries: Sequence[DiscoveryEntry]) -> dict[str, list[DiscoveryEntry]]:
    out: dict[str, list[DiscoveryEntry]] = {}
    for row in entries:
        out.setdefault(row.period, []).append(row)
    for period in out:
        out[period] = sorted(out[period], key=lambda x: (x.href, x.title_raw))
    return out


def expected_periods_from_index(
    entries: Sequence[DiscoveryEntry],
    start: Period,
) -> list[Period]:
    if not entries:
        return []
    latest = max(Period.parse(e.period) for e in entries)
    if latest < start:
        return []
    return list(iter_periods(start, latest))


def request_bytes(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_s: float = DEFAULT_BACKOFF_S,
    sleep_fn: Any = time.sleep,
) -> FetchResult:
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
                body = response.read()
                return FetchResult(
                    requested_url=url,
                    final_url=response.geturl(),
                    status=STATUS_PASS,
                    http_status=getattr(response, "status", None),
                    content_type=response.headers.get("Content-Type"),
                    last_modified=response.headers.get("Last-Modified"),
                    etag=response.headers.get("ETag"),
                    retrieval_utc=utc_now(),
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code in RETRYABLE_HTTP and attempt < max_retries:
                sleep_fn(backoff_s * (attempt + 1))
                continue
            return FetchResult(
                requested_url=url,
                status=STATUS_SOURCE_UNAVAILABLE,
                http_status=exc.code,
                retrieval_utc=utc_now(),
                error=last_error,
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(getattr(exc, "reason", None) or exc)
            if attempt < max_retries:
                sleep_fn(backoff_s * (attempt + 1))
                continue
            return FetchResult(
                requested_url=url,
                status=STATUS_SOURCE_UNAVAILABLE,
                retrieval_utc=utc_now(),
                error=last_error,
            )
    return FetchResult(
        requested_url=url,
        status=STATUS_SOURCE_UNAVAILABLE,
        retrieval_utc=utc_now(),
        error=last_error or "unknown fetch failure",
    )


def looks_like_pdf(data: bytes, content_type: str | None = None) -> bool:
    if not data.startswith(PDF_MAGIC):
        return False
    if content_type and "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
        # A PDF signature is stronger than a mislabeled server content type, but preserve the mismatch.
        return True
    return True


def landing_publication_date(html: str) -> str | None:
    parser = AnchorParser()
    parser.feed(html)
    if not parser.publication_dates:
        return None
    return sorted(set(parser.publication_dates))[0]


def landing_pdf_links(html: str, landing_url: str) -> list[str]:
    parser = AnchorParser()
    parser.feed(html)
    links: set[str] = set()
    for href, _label in parser.anchors:
        absolute = urllib.parse.urljoin(landing_url, href)
        if PDF_HREF_RE.search(absolute):
            links.add(absolute)
    return sorted(links)


def classify_units(text: str) -> set[str]:
    return {m.group("unit").upper() for m in UNIT_TOKEN_RE.finditer(text)}


def classify_hydro_text(text: str) -> str:
    low = text.lower()
    hydro = any(term in low for term in HYDRO_TERMS)
    if not hydro:
        return "HYDRO_ABSENT"
    contexts = hydro_context_lines(text)
    joined = "\n".join(x["context"] for x in contexts) if contexts else text
    units = classify_units(joined)
    generation = any(term in joined.lower() for term in GENERATION_TERMS)
    if generation and ({"MWH", "GWH", "KWH"} & units):
        return "HYDRO_MWH_PRESENT"
    if "MW" in units or "GW" in units or "KW" in units:
        return "HYDRO_MW_ONLY"
    return "HYDRO_OTHER_METRIC"


def hydro_context_lines(text: str, radius: int = 2) -> list[dict[str, Any]]:
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        low = line.lower()
        terms = sorted({term for term in HYDRO_TERMS if term in low})
        if not terms:
            continue
        lo = max(0, i - radius)
        hi = min(len(lines), i + radius + 1)
        context = "\n".join(lines[lo:hi]).strip()
        out.append(
            {
                "line_number": i + 1,
                "hydro_terms": terms,
                "context": context,
                "units": sorted(classify_units(context)),
                "generation_context": any(term in context.lower() for term in GENERATION_TERMS),
            }
        )
    return out


def typed_observations(
    period: str,
    page_number: int,
    text: str,
    manifestation_sha256: str,
) -> list[dict[str, Any]]:
    lines = text.splitlines()
    observations: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        low = line.lower()
        if not any(term in low for term in HYDRO_TERMS):
            continue
        lo = max(0, i - 2)
        hi = min(len(lines), i + 3)
        context = "\n".join(lines[lo:hi]).strip()
        for match in NUMBER_UNIT_RE.finditer(context):
            raw_value = match.group("value")
            value = float(raw_value.replace(",", ""))
            unit = match.group("unit")
            unit_upper = unit.upper()
            measurement_class = {
                "MWH": "ENERGY",
                "GWH": "ENERGY",
                "KWH": "ENERGY",
                "MW": "POWER",
                "GW": "POWER",
                "KW": "POWER",
                "%": "PERCENTAGE",
            }[unit_upper]
            observations.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "period": period,
                    "page_number": page_number,
                    "manifestation_sha256": manifestation_sha256,
                    "raw_line": line,
                    "raw_context": context,
                    "raw_value": raw_value,
                    "normalized_value": value,
                    "raw_unit": unit,
                    "normalized_unit": unit_upper,
                    "measurement_class": measurement_class,
                    "hydro_terms": sorted({t for t in HYDRO_TERMS if t in context.lower()}),
                    "generation_context": any(t in context.lower() for t in GENERATION_TERMS),
                    "identity_state": "CANDIDATE_NOT_IDENTITY",
                    "canonical_promotion_eligible": False,
                }
            )
    return observations


def _pypdf_reader(path: Path) -> Any:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised by runtime gate
        raise AdapterError("pypdf is required for page-complete parsing") from exc
    return PdfReader(str(path))


def extract_pdf_pages(path: Path) -> list[str]:
    reader = _pypdf_reader(path)
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return pages


def render_pages(path: Path, render_root: Path, dpi: int = 120) -> list[Path]:
    if shutil.which("pdftoppm") is None:
        raise AdapterError("pdftoppm is required for page-complete render replay")
    reader = _pypdf_reader(path)
    page_count = len(reader.pages)
    render_root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for page_no in range(1, page_count + 1):
        prefix = render_root / f"page-{page_no:04d}"
        proc = subprocess.run(
            [
                "pdftoppm", "-png", "-r", str(dpi),
                "-f", str(page_no), "-l", str(page_no),
                "-singlefile", str(path), str(prefix),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        out = prefix.with_suffix(".png")
        if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(
                f"render failed for {path} page={page_no}: "
                f"exit={proc.returncode} stderr={proc.stderr[-400:]}"
            )
        outputs.append(out)
    return outputs


def relation_to_prior(
    period: str,
    pdf_url: str | None,
    sha256: str | None,
    prior_rows: Sequence[dict[str, Any]],
) -> str:
    relevant = [r for r in prior_rows if r.get("period") == period and r.get("sha256")]
    if not relevant or sha256 is None:
        return "NEW_OR_UNRESOLVED"
    if any(r.get("sha256") == sha256 for r in relevant):
        if pdf_url and any(r.get("pdf_url") != pdf_url and r.get("sha256") == sha256 for r in relevant):
            return "SOURCE_MANIFESTATION_CHANGE_PAYLOAD_IDENTICAL"
        return "BYTE_IDENTICAL"
    if pdf_url and any(r.get("pdf_url") == pdf_url for r in relevant):
        return "NEW_MANIFESTATION_SAME_URL_DIFFERENT_BYTES"
    return "DISTINCT_PAYLOAD"


def select_incremental_periods(
    expected: Sequence[Period],
    index_map: dict[str, list[DiscoveryEntry]],
    prior_rows: Sequence[dict[str, Any]],
    latest_n: int = DEFAULT_INCREMENTAL_MONTHS,
) -> list[Period]:
    selected: set[Period] = set(expected[-latest_n:]) if expected else set()
    prior_by_period: dict[str, list[dict[str, Any]]] = {}
    for row in prior_rows:
        prior_by_period.setdefault(str(row.get("period")), []).append(row)

    for period in expected:
        key = str(period)
        current_urls = sorted({e.href for e in index_map.get(key, [])})
        previous_urls = sorted(
            {
                str(r.get("indexed_href"))
                for r in prior_by_period.get(key, [])
                if r.get("indexed_href")
            }
        )
        if current_urls != previous_urls:
            selected.add(period)
        previous = prior_by_period.get(key, [])
        if not previous or any(r.get("source_state") != STATUS_PASS for r in previous):
            selected.add(period)
    return sorted(selected)


def _manifestation_key(period: str, pdf_url: str | None, sha: str | None) -> str:
    basis = "\n".join((period, pdf_url or "", sha or ""))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def acquire_manifestation(
    period: Period,
    entry: DiscoveryEntry | None,
    output_root: Path,
    timeout: float,
    prior_rows: Sequence[dict[str, Any]],
) -> list[ManifestRow]:
    synthesized = synthesized_landing_url(period)
    discovery_class = entry.discovery_class if entry else "SYNTHESIZED_DISCOVERY_ONLY"
    index_url = entry.index_url if entry else None
    title = entry.title_raw if entry else None
    indexed_href = entry.href if entry else None
    landing_candidate = indexed_href or synthesized

    landing = request_bytes(landing_candidate, timeout)
    notes: list[str] = []
    if landing.status != STATUS_PASS or landing.body is None:
        return [
            ManifestRow(
                schema_version=SCHEMA_VERSION,
                period=str(period),
                manifestation_key=_manifestation_key(str(period), None, None),
                discovery_class=discovery_class,
                index_url=index_url,
                index_title_raw=title,
                indexed_href=indexed_href,
                synthesized_landing_url=synthesized,
                landing_url=landing.final_url or landing_candidate,
                pdf_url=None,
                publication_date=None,
                retrieval_utc=landing.retrieval_utc,
                source_state=STATUS_SOURCE_UNAVAILABLE,
                http_status=landing.http_status,
                content_type=landing.content_type,
                last_modified=landing.last_modified,
                etag=landing.etag,
                raw_path=None,
                byte_count=None,
                sha256=None,
                pdf_signature_valid=None,
                page_count=None,
                parsed_page_count=None,
                rendered_page_count=None,
                page_complete_parse=None,
                page_complete_render=None,
                hydro_classification="UNRESOLVED",
                negative_page_complete_ready=False,
                negative_certification_eligible=False,
                prior_manifestation_relation="NEW_OR_UNRESOLVED",
                notes=[f"landing fetch failed: {landing.error or landing.status}"],
            )
        ]

    publication_date: str | None = None
    if looks_like_pdf(landing.body, landing.content_type):
        pdf_urls = [landing.final_url or landing_candidate]
        notes.append("indexed/synthesized href resolved directly to PDF bytes")
    else:
        html = landing.body.decode("utf-8", "replace")
        publication_date = landing_publication_date(html)
        pdf_urls = landing_pdf_links(html, landing.final_url or landing_candidate)
        if not pdf_urls:
            return [
                ManifestRow(
                    schema_version=SCHEMA_VERSION,
                    period=str(period),
                    manifestation_key=_manifestation_key(str(period), None, None),
                    discovery_class=discovery_class,
                    index_url=index_url,
                    index_title_raw=title,
                    indexed_href=indexed_href,
                    synthesized_landing_url=synthesized,
                    landing_url=landing.final_url or landing_candidate,
                    pdf_url=None,
                    publication_date=publication_date,
                    retrieval_utc=landing.retrieval_utc,
                    source_state=STATUS_UNRESOLVED,
                    http_status=landing.http_status,
                    content_type=landing.content_type,
                    last_modified=landing.last_modified,
                    etag=landing.etag,
                    raw_path=None,
                    byte_count=None,
                    sha256=None,
                    pdf_signature_valid=None,
                    page_count=None,
                    parsed_page_count=None,
                    rendered_page_count=None,
                    page_complete_parse=None,
                    page_complete_render=None,
                    hydro_classification="UNRESOLVED",
                    negative_certification_eligible=False,
                    prior_manifestation_relation="NEW_OR_UNRESOLVED",
                    notes=["landing page fetched but no PDF link resolved"],
                )
            ]

    rows: list[ManifestRow] = []
    for pdf_url in sorted(set(pdf_urls)):
        pdf_fetch = request_bytes(pdf_url, timeout)
        if pdf_fetch.status != STATUS_PASS or pdf_fetch.body is None:
            rows.append(
                ManifestRow(
                    schema_version=SCHEMA_VERSION,
                    period=str(period),
                    manifestation_key=_manifestation_key(str(period), pdf_url, None),
                    discovery_class=discovery_class,
                    index_url=index_url,
                    index_title_raw=title,
                    indexed_href=indexed_href,
                    synthesized_landing_url=synthesized,
                    landing_url=landing.final_url or landing_candidate,
                    pdf_url=pdf_url,
                    publication_date=None,
                    retrieval_utc=pdf_fetch.retrieval_utc,
                    source_state=STATUS_SOURCE_UNAVAILABLE,
                    http_status=pdf_fetch.http_status,
                    content_type=pdf_fetch.content_type,
                    last_modified=pdf_fetch.last_modified,
                    etag=pdf_fetch.etag,
                    raw_path=None,
                    byte_count=None,
                    sha256=None,
                    pdf_signature_valid=None,
                    page_count=None,
                    parsed_page_count=None,
                    rendered_page_count=None,
                    page_complete_parse=None,
                    page_complete_render=None,
                    hydro_classification="UNRESOLVED",
                    negative_certification_eligible=False,
                    prior_manifestation_relation="NEW_OR_UNRESOLVED",
                    notes=notes + [f"PDF fetch failed: {pdf_fetch.error or pdf_fetch.status}"],
                )
            )
            continue

        data = pdf_fetch.body
        digest = sha256_bytes(data)
        valid_pdf = looks_like_pdf(data, pdf_fetch.content_type)
        basename = Path(urllib.parse.urlparse(pdf_fetch.final_url or pdf_url).path).name or "report.pdf"
        raw_dir = output_root / "raw" / str(period)
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{digest}__{basename}"
        if raw_path.is_file():
            existing = raw_path.read_bytes()
            if existing != data:
                raise AdapterError(f"hash-addressed path collision: {raw_path}")
        else:
            raw_path.write_bytes(data)

        if not valid_pdf:
            rows.append(
                ManifestRow(
                    schema_version=SCHEMA_VERSION,
                    period=str(period),
                    manifestation_key=_manifestation_key(str(period), pdf_url, digest),
                    discovery_class=discovery_class,
                    index_url=index_url,
                    index_title_raw=title,
                    indexed_href=indexed_href,
                    synthesized_landing_url=synthesized,
                    landing_url=landing.final_url or landing_candidate,
                    pdf_url=pdf_fetch.final_url or pdf_url,
                    publication_date=publication_date,
                    retrieval_utc=pdf_fetch.retrieval_utc,
                    source_state="INVALID_PDF",
                    http_status=pdf_fetch.http_status,
                    content_type=pdf_fetch.content_type,
                    last_modified=pdf_fetch.last_modified,
                    etag=pdf_fetch.etag,
                    raw_path=str(raw_path.relative_to(output_root)),
                    byte_count=len(data),
                    sha256=digest,
                    pdf_signature_valid=False,
                    page_count=None,
                    parsed_page_count=None,
                    rendered_page_count=None,
                    page_complete_parse=False,
                    page_complete_render=False,
                    hydro_classification="UNRESOLVED",
                    negative_certification_eligible=False,
                    prior_manifestation_relation=relation_to_prior(
                        str(period), pdf_fetch.final_url or pdf_url, digest, prior_rows
                    ),
                    notes=notes + ["response did not begin with %PDF-"],
                )
            )
            continue

        page_count: int | None = None
        parsed_count = 0
        rendered_count = 0
        classification = "UNRESOLVED"
        parse_complete = False
        render_complete = False
        row_notes = list(notes)
        normalized_rows: list[dict[str, Any]] = []
        page_index_rows: list[dict[str, Any]] = []

        try:
            page_texts = extract_pdf_pages(raw_path)
            page_count = len(page_texts)
            parsed_count = len(page_texts)
            parse_complete = parsed_count == page_count
        except Exception as exc:
            page_texts = []
            row_notes.append(f"page parse failed: {type(exc).__name__}: {exc}")

        render_dir = output_root / "pages" / str(period) / digest
        try:
            rendered = render_pages(raw_path, render_dir)
            rendered_count = len(rendered)
            render_complete = page_count is not None and rendered_count == page_count
        except Exception as exc:
            rendered = []
            row_notes.append(f"page render failed: {type(exc).__name__}: {exc}")

        if page_texts:
            joined = "\n".join(page_texts)
            classification = classify_hydro_text(joined)
            for page_no, page_text in enumerate(page_texts, 1):
                render_path = (
                    rendered[page_no - 1] if page_no <= len(rendered) else None
                )
                page_index_rows.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "period": str(period),
                        "manifestation_sha256": digest,
                        "page_number": page_no,
                        "text_sha256": sha256_bytes(page_text.encode("utf-8")),
                        "text_char_count": len(page_text),
                        "hydro_terms": sorted(
                            {t for t in HYDRO_TERMS if t in page_text.lower()}
                        ),
                        "units": sorted(classify_units(page_text)),
                        "hydro_classification": classify_hydro_text(page_text),
                        "render_path": (
                            str(render_path.relative_to(output_root))
                            if render_path is not None else None
                        ),
                        "render_sha256": (
                            sha256_file(render_path) if render_path is not None else None
                        ),
                    }
                )
                normalized_rows.extend(
                    typed_observations(str(period), page_no, page_text, digest)
                )
        negative_page_complete_ready = (
            classification == "HYDRO_ABSENT"
            and bool(page_count)
            and parse_complete
            and render_complete
        )
        negative_eligible = False
        if classification == "HYDRO_ABSENT":
            row_notes.append(
                "bounded textual negative only; rendered pages require independent visual "
                "semantic review before any negative source-family certification"
            )

        page_index_path = output_root / "page_index.jsonl"
        existing_pages = read_jsonl(page_index_path)
        page_key = lambda r: (r.get("manifestation_sha256"), r.get("page_number"))
        merged_pages = {
            page_key(r): r for r in existing_pages
        }
        for r in page_index_rows:
            merged_pages[page_key(r)] = r
        write_jsonl(
            page_index_path,
            [merged_pages[k] for k in sorted(merged_pages, key=lambda x: (str(x[0]), int(x[1] or 0)))],
        )

        normalized_path = output_root / "normalized" / "observations.jsonl"
        existing_obs = read_jsonl(normalized_path)
        obs_key = lambda r: (
            r.get("manifestation_sha256"),
            r.get("page_number"),
            r.get("raw_context"),
            r.get("raw_value"),
            r.get("raw_unit"),
        )
        merged_obs = {obs_key(r): r for r in existing_obs}
        for r in normalized_rows:
            merged_obs[obs_key(r)] = r
        write_jsonl(
            normalized_path,
            [
                merged_obs[k]
                for k in sorted(
                    merged_obs,
                    key=lambda x: (str(x[0]), int(x[1] or 0), str(x[2]), str(x[3]), str(x[4])),
                )
            ],
        )

        rows.append(
            ManifestRow(
                schema_version=SCHEMA_VERSION,
                period=str(period),
                manifestation_key=_manifestation_key(
                    str(period), pdf_fetch.final_url or pdf_url, digest
                ),
                discovery_class=discovery_class,
                index_url=index_url,
                index_title_raw=title,
                indexed_href=indexed_href,
                synthesized_landing_url=synthesized,
                landing_url=landing.final_url or landing_candidate,
                pdf_url=pdf_fetch.final_url or pdf_url,
                publication_date=publication_date,
                retrieval_utc=pdf_fetch.retrieval_utc,
                source_state=STATUS_PASS,
                http_status=pdf_fetch.http_status,
                content_type=pdf_fetch.content_type,
                last_modified=pdf_fetch.last_modified,
                etag=pdf_fetch.etag,
                raw_path=str(raw_path.relative_to(output_root)),
                byte_count=len(data),
                sha256=digest,
                pdf_signature_valid=True,
                page_count=page_count,
                parsed_page_count=parsed_count,
                rendered_page_count=rendered_count,
                page_complete_parse=parse_complete,
                page_complete_render=render_complete,
                hydro_classification=classification,
                negative_page_complete_ready=negative_page_complete_ready,
                negative_certification_eligible=negative_eligible,
                prior_manifestation_relation=relation_to_prior(
                    str(period), pdf_fetch.final_url or pdf_url, digest, prior_rows
                ),
                notes=row_notes,
            )
        )
    return rows


def reconcile_manifest_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    # Whole-row selection by manifestation_key; latest retrieval replaces only the same
    # exact logical manifestation candidate, while distinct SHA/URL variants are retained.
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("manifestation_key") or "")
        if not key:
            raise AdapterError("manifest row missing manifestation_key")
        current = selected.get(key)
        if current is None:
            selected[key] = dict(row)
            continue
        cur_ts = str(current.get("retrieval_utc") or "")
        new_ts = str(row.get("retrieval_utc") or "")
        if new_ts >= cur_ts:
            selected[key] = dict(row)
    return [
        selected[k]
        for k in sorted(
            selected,
            key=lambda k: (
                str(selected[k].get("period")),
                str(selected[k].get("pdf_url") or ""),
                str(selected[k].get("sha256") or ""),
                k,
            ),
        )
    ]


def duplicate_period_state(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    periods: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        periods.setdefault(str(row.get("period")), []).append(row)
    result: dict[str, dict[str, Any]] = {}
    for period, group in sorted(periods.items()):
        shas = sorted({str(r.get("sha256")) for r in group if r.get("sha256")})
        urls = sorted({str(r.get("pdf_url")) for r in group if r.get("pdf_url")})
        if len(shas) > 1:
            state = "MULTIPLE_DISTINCT_PAYLOADS"
        elif len(urls) > 1 and len(shas) == 1:
            state = "SAME_PAYLOAD_MULTIPLE_MANIFESTATIONS"
        elif len(group) > 1:
            state = "MULTIPLE_DISCOVERY_ROWS"
        else:
            state = "SINGLE"
        result[period] = {
            "row_count": len(group),
            "distinct_sha_count": len(shas),
            "distinct_pdf_url_count": len(urls),
            "state": state,
        }
    return result


def manifest_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fields = [
        f.name for f in ManifestRow.__dataclass_fields__.values()  # type: ignore[attr-defined]
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            data = {k: row.get(k) for k in fields}
            data["notes"] = json.dumps(data.get("notes") or [], ensure_ascii=False)
            writer.writerow(data)


def build_canonical_candidates(
    normalized_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    # By design, name-only matches cannot establish canonical plant/unit identity.
    # Aggregate Hydro observations may still be preserved as non-identity candidates.
    out: list[dict[str, Any]] = []
    for row in normalized_rows:
        out.append(
            {
                "schema_version": SCHEMA_VERSION,
                "period": row.get("period"),
                "manifestation_sha256": row.get("manifestation_sha256"),
                "page_number": row.get("page_number"),
                "measurement_class": row.get("measurement_class"),
                "normalized_value": row.get("normalized_value"),
                "normalized_unit": row.get("normalized_unit"),
                "raw_context": row.get("raw_context"),
                "identity_state": "CANDIDATE_NOT_IDENTITY",
                "canonical_claim_state": "WITHHELD",
                "reason": (
                    "hydro/plant-name context without stable source-native ID is discovery "
                    "evidence only; no name-only canonical identity promotion"
                ),
            }
        )
    return out


def replay_snapshot(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.jsonl"
    rows = read_jsonl(manifest_path)
    page_rows = read_jsonl(root / "page_index.jsonl")
    normalized = read_jsonl(root / "normalized" / "observations.jsonl")
    canonical = read_jsonl(root / "canonical" / "claims.jsonl")

    failures: list[str] = []
    byte_pass = 0
    pdf_pass = 0
    page_count_pass = 0
    page_text_replay_pass = 0
    render_replay_pass = 0
    typed_unit_pass = 0

    pages_by_sha: dict[str, list[dict[str, Any]]] = {}
    for page in page_rows:
        pages_by_sha.setdefault(str(page.get("manifestation_sha256")), []).append(page)

    for row in rows:
        if row.get("source_state") != STATUS_PASS:
            continue
        rel = row.get("raw_path")
        digest = row.get("sha256")
        size = row.get("byte_count")
        if not rel or not digest:
            failures.append(f"{row.get('period')}: PASS row lacks raw_path/sha256")
            continue
        raw = root / str(rel)
        if not raw.is_file():
            failures.append(f"{row.get('period')}: missing raw file {rel}")
            continue
        actual_sha = sha256_file(raw)
        actual_size = raw.stat().st_size
        if actual_sha != digest or actual_size != size:
            failures.append(
                f"{row.get('period')}: raw mismatch sha={actual_sha} size={actual_size}"
            )
            continue
        byte_pass += 1
        if raw.read_bytes()[:5] != PDF_MAGIC:
            failures.append(f"{row.get('period')}: invalid PDF signature")
            continue
        pdf_pass += 1

        expected_pages = row.get("page_count")
        indexed_pages = sorted(
            pages_by_sha.get(str(digest), []),
            key=lambda x: int(x.get("page_number") or 0),
        )
        if isinstance(expected_pages, int) and expected_pages > 0:
            if len(indexed_pages) == expected_pages:
                page_count_pass += 1
            else:
                failures.append(
                    f"{row.get('period')}: page-index count={len(indexed_pages)} "
                    f"expected={expected_pages}"
                )
                continue
            try:
                replay_texts = extract_pdf_pages(raw)
            except Exception as exc:
                failures.append(
                    f"{row.get('period')}: replay text extraction failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if len(replay_texts) != expected_pages:
                failures.append(
                    f"{row.get('period')}: replay page count={len(replay_texts)} "
                    f"expected={expected_pages}"
                )
                continue
            text_ok = True
            render_ok = True
            for page_row, page_text in zip(indexed_pages, replay_texts, strict=True):
                actual_text_sha = sha256_bytes(page_text.encode("utf-8"))
                if actual_text_sha != page_row.get("text_sha256"):
                    text_ok = False
                    failures.append(
                        f"{row.get('period')}: page={page_row.get('page_number')} "
                        "text SHA mismatch"
                    )
                render_rel = page_row.get("render_path")
                render_sha = page_row.get("render_sha256")
                if not render_rel or not render_sha:
                    render_ok = False
                    failures.append(
                        f"{row.get('period')}: page={page_row.get('page_number')} "
                        "render receipt missing"
                    )
                    continue
                render_file = root / str(render_rel)
                if not render_file.is_file() or sha256_file(render_file) != render_sha:
                    render_ok = False
                    failures.append(
                        f"{row.get('period')}: page={page_row.get('page_number')} "
                        "render SHA mismatch/missing"
                    )
            if text_ok:
                page_text_replay_pass += 1
            if render_ok:
                render_replay_pass += 1

    for obs in normalized:
        unit = str(obs.get("normalized_unit") or "")
        klass = str(obs.get("measurement_class") or "")
        expected = {
            "MWH": "ENERGY", "GWH": "ENERGY", "KWH": "ENERGY",
            "MW": "POWER", "GW": "POWER", "KW": "POWER", "%": "PERCENTAGE",
        }.get(unit)
        if expected is None or expected != klass:
            failures.append(
                f"typed-unit mismatch unit={unit!r} class={klass!r}"
            )
        else:
            typed_unit_pass += 1

    if any(row.get("canonical_claim_state") != "WITHHELD" for row in canonical):
        failures.append("canonical claims contain unreviewed promoted identity")

    duplicates = duplicate_period_state(rows)
    gates = {
        "SHA_REPLAY": "PASS" if byte_pass == sum(r.get("source_state") == STATUS_PASS for r in rows) else "FAIL",
        "PDF_SIGNATURE": "PASS" if pdf_pass == byte_pass else "FAIL",
        "PAGE_COUNT_CLOSURE": (
            "PASS"
            if page_count_pass
            == sum(
                r.get("source_state") == STATUS_PASS
                and isinstance(r.get("page_count"), int)
                and int(r.get("page_count") or 0) > 0
                for r in rows
            )
            else "FAIL"
        ),
        "PAGE_TEXT_SHA_REPLAY": (
            "PASS" if page_text_replay_pass == page_count_pass else "FAIL"
        ),
        "RENDER_SHA_REPLAY": (
            "PASS" if render_replay_pass == page_count_pass else "FAIL"
        ),
        "NEGATIVE_AUTO_CERTIFICATION_DENY": (
            "PASS"
            if not any(bool(r.get("negative_certification_eligible")) for r in rows)
            else "FAIL"
        ),
        "TYPED_UNIT_VALIDATION": "PASS" if not any("typed-unit mismatch" in f for f in failures) else "FAIL",
        "NO_NAME_ONLY_CANONICAL_PROMOTION": "PASS" if not any("canonical claims" in f for f in failures) else "FAIL",
        "IDEMPOTENT_MANIFEST_KEYS": (
            "PASS"
            if len(rows) == len({str(r.get("manifestation_key")) for r in rows})
            else "FAIL"
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "replay_utc": utc_now(),
        "manifest_rows": len(rows),
        "pass_source_rows": sum(r.get("source_state") == STATUS_PASS for r in rows),
        "byte_replay_pass": byte_pass,
        "pdf_signature_pass": pdf_pass,
        "page_count_pass": page_count_pass,
        "page_text_replay_pass": page_text_replay_pass,
        "render_replay_pass": render_replay_pass,
        "typed_unit_rows_pass": typed_unit_pass,
        "duplicate_period_state": duplicates,
        "gates": gates,
        "failures": failures,
        "overall": "PASS" if not failures and all(v == "PASS" for v in gates.values()) else "FAIL",
    }


def deterministic_archive(root: Path, archive_path: Path) -> dict[str, Any]:
    include_roots = [
        root / "raw",
        root / "pages",
        root / "normalized",
        root / "canonical",
    ]
    include_files = [
        root / "manifest.jsonl",
        root / "manifest.csv",
        root / "contradictions.jsonl",
        root / "page_index.jsonl",
        root / "index_entries.jsonl",
        root / "denominator.json",
        root / "replay.json",
    ]
    members: list[Path] = []
    for base in include_roots:
        if base.is_dir():
            members.extend(p for p in base.rglob("*") if p.is_file())
    members.extend(p for p in include_files if p.is_file())
    members = sorted(set(members), key=lambda p: p.relative_to(root).as_posix())

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in members:
            rel = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(rel)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
    return {
        "path": str(archive_path),
        "byte_count": archive_path.stat().st_size,
        "sha256": sha256_file(archive_path),
        "member_count": len(members),
        "members": [
            {
                "path": p.relative_to(root).as_posix(),
                "uncompressed_size": p.stat().st_size,
                "sha256": sha256_file(p),
            }
            for p in members
        ],
    }


def index_denominator(
    entries: Sequence[DiscoveryEntry],
    expected: Sequence[Period],
) -> dict[str, Any]:
    mapping = index_period_map(entries)
    missing = [str(p) for p in expected if str(p) not in mapping]
    duplicate = {
        period: [e.href for e in rows]
        for period, rows in mapping.items()
        if len({e.href for e in rows}) > 1
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "start_period": str(expected[0]) if expected else None,
        "end_period": str(expected[-1]) if expected else None,
        "expected_count": len(expected),
        "indexed_expected_count": len(expected) - len(missing),
        "missing_periods": missing,
        "multiple_index_manifestations": duplicate,
        "gate": "PASS" if not missing else "FAIL_CLOSED",
    }


def acquire_index(index_urls: Sequence[str], timeout: float) -> tuple[list[DiscoveryEntry], list[dict[str, Any]]]:
    all_entries: list[DiscoveryEntry] = []
    receipts: list[dict[str, Any]] = []
    for url in index_urls:
        fetched = request_bytes(url, timeout)
        receipt = {
            "url": url,
            "status": fetched.status,
            "http_status": fetched.http_status,
            "final_url": fetched.final_url,
            "retrieval_utc": fetched.retrieval_utc,
            "content_type": fetched.content_type,
            "last_modified": fetched.last_modified,
            "etag": fetched.etag,
            "byte_count": len(fetched.body) if fetched.body is not None else None,
            "sha256": sha256_bytes(fetched.body) if fetched.body is not None else None,
            "error": fetched.error,
        }
        receipts.append(receipt)
        if fetched.status != STATUS_PASS or fetched.body is None:
            continue
        html = fetched.body.decode("utf-8", "replace")
        all_entries.extend(parse_index_entries(html, fetched.final_url or url))
    # Stable de-dup across language/index mirrors.
    unique: dict[tuple[str, str], DiscoveryEntry] = {}
    for e in all_entries:
        unique[(e.period, e.href)] = e
    return sorted(unique.values(), key=lambda e: (e.period, e.href)), receipts


def run_acquisition(args: argparse.Namespace) -> int:
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    prior_rows = read_jsonl(root / "manifest.jsonl")

    entries, index_receipts = acquire_index(args.index_url, args.timeout)
    write_jsonl(root / "index_entries.jsonl", [asdict(e) for e in entries])
    write_json(root / "index_receipts.json", index_receipts)

    start = Period.parse(args.start)
    expected = expected_periods_from_index(entries, start)
    if not expected:
        write_json(
            root / "denominator.json",
            {
                "schema_version": SCHEMA_VERSION,
                "gate": "FAIL_CLOSED",
                "reason": "authoritative index produced no usable monthly report denominator",
                "start_period": str(start),
                "index_receipts": index_receipts,
            },
        )
        print("FAIL_CLOSED: no authoritative index denominator", file=sys.stderr)
        return 2

    denom = index_denominator(entries, expected)
    write_json(root / "denominator.json", denom)
    mapping = index_period_map(entries)

    if args.mode == "backfill":
        selected = expected
    else:
        selected = select_incremental_periods(
            expected, mapping, prior_rows, latest_n=args.incremental_months
        )

    new_rows: list[dict[str, Any]] = []
    for period in selected:
        indexed = mapping.get(str(period), [])
        if indexed:
            # Preserve full candidate set; do not choose nearest/first as identity.
            for entry in indexed:
                for row in acquire_manifestation(
                    period, entry, root, args.timeout, prior_rows
                ):
                    new_rows.append(asdict(row))
        else:
            for row in acquire_manifestation(
                period, None, root, args.timeout, prior_rows
            ):
                new_rows.append(asdict(row))

    manifest_rows = reconcile_manifest_rows([*prior_rows, *new_rows])
    write_jsonl(root / "manifest.jsonl", manifest_rows)
    manifest_csv(root / "manifest.csv", manifest_rows)

    normalized = read_jsonl(root / "normalized" / "observations.jsonl")
    canonical = build_canonical_candidates(normalized)
    write_jsonl(root / "canonical" / "claims.jsonl", canonical)

    contradictions: list[dict[str, Any]] = []
    for period, state in duplicate_period_state(manifest_rows).items():
        if state["state"] == "MULTIPLE_DISTINCT_PAYLOADS":
            contradictions.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "period": period,
                    "contradiction_class": "BYTE",
                    "state": "OPEN",
                    "detail": state,
                    "adjudication": (
                        "same report period has multiple distinct frozen payloads; "
                        "preserve all manifestations until publication/correction lineage is bound"
                    ),
                }
            )
    write_jsonl(root / "contradictions.jsonl", contradictions)

    replay = replay_snapshot(root)
    write_json(root / "replay.json", replay)

    archive = deterministic_archive(root, root / "archive.zip")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "mode": args.mode,
        "created_utc": utc_now(),
        "index_denominator": denom,
        "selected_periods": [str(p) for p in selected],
        "manifest_row_count": len(manifest_rows),
        "pass_source_rows": sum(r.get("source_state") == STATUS_PASS for r in manifest_rows),
        "classification_counts": {
            cls: sum(r.get("hydro_classification") == cls for r in manifest_rows)
            for cls in sorted(CLASSIFICATIONS)
        },
        "negative_certification_eligible_count": sum(
            bool(r.get("negative_certification_eligible")) for r in manifest_rows
        ),
        "replay": replay,
        "archive": archive,
        "source_family_certification_state": (
            "PASS_BOUNDED"
            if denom.get("gate") == "PASS"
            and replay.get("overall") == "PASS"
            and all(
                r.get("source_state") == STATUS_PASS
                for r in manifest_rows
                if r.get("period") in {str(p) for p in expected}
            )
            else "WITHHELD"
        ),
    }
    write_json(root / "receipt.json", receipt)

    print(
        canonical_json(
            {
                "mode": args.mode,
                "denominator_gate": denom.get("gate"),
                "expected_periods": len(expected),
                "selected_periods": len(selected),
                "manifest_rows": len(manifest_rows),
                "pass_source_rows": receipt["pass_source_rows"],
                "replay": replay.get("overall"),
                "archive_sha256": archive["sha256"],
                "source_family_certification_state": receipt[
                    "source_family_certification_state"
                ],
            }
        )
    )
    return 0 if replay.get("overall") == "PASS" else 3


def run_replay(args: argparse.Namespace) -> int:
    root = Path(args.output).resolve()
    replay = replay_snapshot(root)
    write_json(root / "replay.json", replay)
    archive = deterministic_archive(root, root / "archive.zip")
    receipt_path = root / "receipt.json"
    receipt = {}
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.update(
        {
            "schema_version": SCHEMA_VERSION,
            "replay_refreshed_utc": utc_now(),
            "replay": replay,
            "archive": archive,
        }
    )
    write_json(receipt_path, receipt)
    print(canonical_json({"replay": replay["overall"], "archive_sha256": archive["sha256"]}))
    return 0 if replay["overall"] == "PASS" else 3


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    for name in ("backfill", "incremental"):
        p = sub.add_parser(name)
        p.add_argument("--output", default="data/luma_monthly_generation")
        p.add_argument("--start", default=DEFAULT_START_PERIOD)
        p.add_argument(
            "--index-url",
            action="append",
            default=None,
            help="authoritative BPS index URL; repeatable",
        )
        p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
        p.add_argument(
            "--incremental-months",
            type=int,
            default=DEFAULT_INCREMENTAL_MONTHS,
            help="latest N periods to recheck in incremental mode",
        )

    p = sub.add_parser("replay")
    p.add_argument("--output", default="data/luma_monthly_generation")
    return ap


def main() -> int:
    ap = parser()
    args = ap.parse_args()
    if args.mode in {"backfill", "incremental"}:
        if args.index_url is None:
            args.index_url = list(DEFAULT_INDEX_URLS)
        if args.incremental_months < 1:
            raise ValueError("--incremental-months must be >= 1")
        return run_acquisition(args)
    return run_replay(args)


if __name__ == "__main__":
    raise SystemExit(main())
