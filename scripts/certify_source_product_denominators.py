#!/usr/bin/env python3
"""Freeze bounded product-denominator evidence for LUMA Daily Availability and EIA EPM."""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

USER_AGENT = "AguaYLuz-SourceIntelligence/1.0"
LUMA_INDEX = "https://lumapr.com/monitoreo-de-bps/"
EIA_EPM_INDEX = "https://www.eia.gov/electricity/monthly/"
MAX_HTML_BYTES = 20 * 1024 * 1024
MAX_BINARY_BYTES = 300 * 1024 * 1024
LUMA_REPORT_RE = re.compile(
    r"(?P<date>\d{8})[-_ ]Daily[-_ ]Availability[-_ ]Report\.pdf(?:\?.*)?$",
    re.IGNORECASE,
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            self._href = html.unescape(href.strip())
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append(
            {
                "href": self._href,
                "text": " ".join("".join(self._text).split()),
            }
        )
        self._href = None
        self._text = []


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch(
    url: str,
    *,
    allowed_hosts: set[str],
    max_bytes: int,
) -> tuple[bytes, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        final_url = response.geturl()
        parsed = urlparse(final_url)
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            raise ValueError(f"unexpected redirect target: {final_url}")
        payload = response.read(max_bytes + 1)
        if not payload or len(payload) > max_bytes:
            raise ValueError(f"payload empty or oversized: {final_url}")
        media_type = response.headers.get_content_type()
    return payload, final_url, media_type


def parse_links(payload: bytes, base_url: str) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    rows: list[dict[str, str]] = []
    for link in parser.links:
        rows.append(
            {
                "url": urljoin(base_url, link["href"]),
                "text": link["text"],
            }
        )
    return rows


def iso_date(token: str) -> str:
    return datetime.strptime(token, "%Y%m%d").date().isoformat()


def date_gaps(values: list[str]) -> list[str]:
    if not values:
        return []
    parsed = sorted({date.fromisoformat(value) for value in values})
    cursor = parsed[0]
    end = parsed[-1]
    present = set(parsed)
    gaps: list[str] = []
    while cursor <= end:
        if cursor not in present:
            gaps.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return gaps


def freeze_bytes(output: Path, name: str, payload: bytes) -> dict[str, object]:
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    path = raw / name
    path.write_bytes(payload)
    return {
        "path": path.relative_to(output).as_posix(),
        "byte_count": len(payload),
        "sha256": sha256_bytes(payload),
    }


def certify_luma(output: Path, retrieved_at: str) -> dict[str, object]:
    payload, final_url, media_type = fetch(
        LUMA_INDEX,
        allowed_hosts={"lumapr.com", "www.lumapr.com"},
        max_bytes=MAX_HTML_BYTES,
    )
    frozen = freeze_bytes(output, "luma-bps-index.html", payload)
    links = parse_links(payload, final_url)

    reports: list[dict[str, str]] = []
    for link in links:
        parsed = urlparse(link["url"])
        match = LUMA_REPORT_RE.search(parsed.path.split("/")[-1])
        if match:
            reports.append(
                {
                    "date": iso_date(match.group("date")),
                    "url": link["url"],
                    "link_text": link["text"],
                }
            )
    reports = sorted(
        {json.dumps(row, sort_keys=True): row for row in reports}.values(),
        key=lambda row: (row["date"], row["url"]),
    )
    if not reports:
        raise ValueError("LUMA BPS index exposed no Daily Availability Report PDF hrefs")

    date_counts = Counter(row["date"] for row in reports)
    duplicate_dates = sorted(
        day for day, count in date_counts.items() if count > 1
    )
    dates = sorted(date_counts)
    gaps = date_gaps(dates)

    latest = max(reports, key=lambda row: (row["date"], row["url"]))
    latest_payload, latest_final_url, latest_media_type = fetch(
        latest["url"],
        allowed_hosts={"lumapr.com", "www.lumapr.com"},
        max_bytes=MAX_BINARY_BYTES,
    )
    if not latest_payload.startswith(b"%PDF"):
        raise ValueError("latest LUMA Daily Availability payload is not PDF")
    latest_frozen = freeze_bytes(output, "luma-latest-daily-availability.pdf", latest_payload)

    return {
        "source_family_id": "LUMA_DAILY_AVAILABILITY",
        "product_id": "LUMA_DAILY_AVAILABILITY_REPORTS",
        "scope": "all Daily Availability Report PDF hrefs present in frozen BPS index snapshot",
        "retrieved_at_utc": retrieved_at,
        "index_url": LUMA_INDEX,
        "index_final_url": final_url,
        "index_media_type": media_type,
        "index_manifestation": frozen,
        "report_count": len(reports),
        "first_indexed_date": dates[0],
        "last_indexed_date": dates[-1],
        "reports": reports,
        "duplicate_report_dates": duplicate_dates,
        "missing_calendar_dates_within_index_span": gaps,
        "missing_date_semantics": "UNRESOLVED_NOT_SOURCE_ABSENCE",
        "latest_payload": {
            "date": latest["date"],
            "indexed_url": latest["url"],
            "final_url": latest_final_url,
            "media_type": latest_media_type,
            **latest_frozen,
        },
        "bounded_index_snapshot_exhausted": True,
        "family_payload_product_denominator_exhausted": False,
        "family_exhaustion_blockers": [
            "index snapshot alone does not prove reports absent on missing calendar dates were never published",
            "historical manifestations outside the frozen index snapshot remain unproven",
        ],
    }


def zip_member_manifest(payload: bytes) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    members: list[dict[str, object]] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            members.append(
                {
                    "path": info.filename,
                    "uncompressed_size": info.file_size,
                    "sha256": sha256_bytes(data),
                }
            )
    members.sort(key=lambda row: str(row["path"]))
    payload_counts = Counter(
        (int(row["uncompressed_size"]), str(row["sha256"])) for row in members
    )
    duplicates = [
        {
            "uncompressed_size": size,
            "sha256": digest,
            "member_count": count,
        }
        for (size, digest), count in sorted(payload_counts.items())
        if count > 1
    ]
    return members, duplicates


def certify_epm(output: Path, retrieved_at: str) -> dict[str, object]:
    payload, final_url, media_type = fetch(
        EIA_EPM_INDEX,
        allowed_hosts={"www.eia.gov", "eia.gov"},
        max_bytes=MAX_HTML_BYTES,
    )
    frozen = freeze_bytes(output, "eia-epm-index.html", payload)
    links = parse_links(payload, final_url)
    zip_links = [
        link
        for link in links
        if urlparse(link["url"]).path.lower().endswith(".zip")
        and (
            "all tables" in link["text"].lower()
            or "/electricity/monthly/current_month/" in link["url"]
        )
    ]
    unique_zip_urls = sorted({link["url"] for link in zip_links})
    if len(unique_zip_urls) != 1:
        raise ValueError(
            f"EIA EPM expected one canonical current all-tables ZIP, got {unique_zip_urls}"
        )
    zip_url = unique_zip_urls[0]
    zip_payload, zip_final_url, zip_media_type = fetch(
        zip_url,
        allowed_hosts={"www.eia.gov", "eia.gov"},
        max_bytes=MAX_BINARY_BYTES,
    )
    if not zipfile.is_zipfile(io.BytesIO(zip_payload)):
        raise ValueError("EIA EPM canonical payload is not ZIP")
    zip_frozen = freeze_bytes(output, "eia-epm-current-all-tables.zip", zip_payload)
    members, duplicate_payloads = zip_member_manifest(zip_payload)
    if not members:
        raise ValueError("EIA EPM canonical ZIP has no file members")

    xls_links = sorted(
        {
            link["url"]
            for link in links
            if urlparse(link["url"]).path.lower().endswith((".xls", ".xlsx"))
        }
    )

    return {
        "source_family_id": "EIA_EPM",
        "product_id": "EIA_EPM_MONTHLY_PACKAGE",
        "scope": "current EIA Electric Power Monthly publication surface",
        "retrieved_at_utc": retrieved_at,
        "index_url": EIA_EPM_INDEX,
        "index_final_url": final_url,
        "index_media_type": media_type,
        "index_manifestation": frozen,
        "canonical_zip_url": zip_url,
        "canonical_zip_final_url": zip_final_url,
        "canonical_zip_media_type": zip_media_type,
        "canonical_zip_manifestation": zip_frozen,
        "archive_members": members,
        "archive_member_count": len(members),
        "duplicate_payload_members": duplicate_payloads,
        "targeted_xls_route_count": len(xls_links),
        "targeted_xls_routes": xls_links,
        "bounded_current_release_exhausted": True,
        "family_payload_product_denominator_exhausted": False,
        "family_exhaustion_blockers": [
            "current publication surface does not by itself enumerate all historical monthly EPM releases",
        ],
    }


def run(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    luma = certify_luma(output, retrieved_at)
    epm = certify_epm(output, retrieved_at)

    summary = {
        "schema_version": "aguayluz.source-product-denominator-certification/v1",
        "state": "PASS_BOUNDED_SURFACES_FAMILY_EXHAUSTION_OPEN",
        "retrieved_at_utc": retrieved_at,
        "families": {
            "LUMA_DAILY_AVAILABILITY": luma,
            "EIA_EPM": epm,
        },
        "invariants": {
            "authoritative_index_bytes_frozen": True,
            "canonical_payload_route_verified": True,
            "duplicate_payloads_classified": True,
            "missing_dates_not_interpreted_as_source_absence": True,
            "family_denominator_auto_promotion": False,
        },
    }
    encoded = (
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    (output / "certification.json").write_bytes(encoded)
    (output / "certification.sha256").write_text(
        f"{sha256_bytes(encoded)}  certification.json\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/source-product-denominators"),
    )
    args = parser.parse_args()
    summary = run(args.output)
    print(json.dumps(summary["invariants"], sort_keys=True))
    print(f"source product denominator certification: {summary['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
