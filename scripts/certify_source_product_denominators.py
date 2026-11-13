#!/usr/bin/env python3
"""Freeze product-denominator evidence for LUMA Daily Availability and EIA EPM."""
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
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse

USER_AGENT = "AguaYLuz-SourceIntelligence/1.0"
LUMA_INDEX = "https://lumapr.com/monitoreo-de-bps/"
EIA_EPM_INDEX = "https://www.eia.gov/electricity/monthly/"
EIA_EPM_BACKISSUES = "https://www.eia.gov/electricity/monthly/backissues.php"
MAX_HTML_BYTES = 20 * 1024 * 1024
MAX_BINARY_BYTES = 300 * 1024 * 1024
LUMA_REPORT_RE = re.compile(
    r"(?P<date>\d{8})[-_ ]Daily[-_ ]Availability[-_ ]Report\.pdf(?:\?.*)?$",
    re.IGNORECASE,
)
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
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
            {"href": self._href, "text": " ".join("".join(self._text).split())}
        )
        self._href = None
        self._text = []


class IssueArchiveParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_year: int | None = None
        self.issues: list[dict[str, object]] = []
        self._heading = False
        self._heading_text: list[str] = []
        self._li = False
        self._li_text: list[str] = []
        self._li_links: list[dict[str, str]] = []
        self._href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "h3":
            self._heading = True
            self._heading_text = []
        elif lowered == "li" and self.current_year is not None:
            self._li = True
            self._li_text = []
            self._li_links = []
        elif lowered == "a" and self._li:
            href = dict(attrs).get("href")
            if href:
                self._href = html.unescape(href.strip())
                self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._heading:
            self._heading_text.append(data)
        if self._li:
            self._li_text.append(data)
        if self._href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "h3" and self._heading:
            text = " ".join("".join(self._heading_text).split())
            self.current_year = int(text) if re.fullmatch(r"\d{4}", text) else None
            self._heading = False
            self._heading_text = []
        elif lowered == "a" and self._href is not None:
            self._li_links.append(
                {
                    "href": self._href,
                    "text": " ".join("".join(self._anchor_text).split()),
                }
            )
            self._href = None
            self._anchor_text = []
        elif lowered == "li" and self._li:
            text = " ".join("".join(self._li_text).split())
            month = next((name for name in MONTH_NAMES if name in text), None)
            if self.current_year is not None and month is not None:
                self.issues.append(
                    {
                        "year": self.current_year,
                        "month": month,
                        "label": text,
                        "links": list(self._li_links),
                    }
                )
            self._li = False
            self._li_text = []
            self._li_links = []


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
    return [
        {"url": urljoin(base_url, row["href"]), "text": row["text"]}
        for row in parser.links
    ]


def parse_epm_backissues(payload: bytes, base_url: str) -> list[dict[str, object]]:
    parser = IssueArchiveParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    rows: list[dict[str, object]] = []
    for issue in parser.issues:
        links = [
            {"url": urljoin(base_url, row["href"]), "text": row["text"]}
            for row in issue["links"]
        ]
        zip_urls = sorted(
            {row["url"] for row in links if urlparse(row["url"]).path.lower().endswith(".zip")}
        )
        pdf_urls = sorted(
            {row["url"] for row in links if urlparse(row["url"]).path.lower().endswith(".pdf")}
        )
        label = str(issue["label"])
        if zip_urls and pdf_urls:
            state = "ZIP_AND_PDF"
        elif zip_urls:
            state = "ZIP_ONLY"
        elif pdf_urls:
            state = "PDF_ONLY"
        elif "n/a" in label.lower():
            state = "EXPLICIT_NA"
        else:
            state = "UNCLASSIFIED"
        rows.append(
            {
                "year": issue["year"],
                "month": issue["month"],
                "label": label,
                "state": state,
                "zip_urls": zip_urls,
                "pdf_urls": pdf_urls,
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
    duplicate_dates = sorted(day for day, count in date_counts.items() if count > 1)
    dates = sorted(date_counts)
    gaps = date_gaps(dates)

    gap_probes: list[dict[str, object]] = []
    for missing_day in gaps:
        parsed_day = date.fromisoformat(missing_day)
        candidate = (
            "https://lumapr.com/wp-content/uploads/"
            f"{parsed_day:%Y/%m}/{parsed_day:%Y%m%d}-Daily-Availability-Report.pdf"
        )
        try:
            candidate_payload, candidate_final, candidate_type = fetch(
                candidate,
                allowed_hosts={"lumapr.com", "www.lumapr.com"},
                max_bytes=MAX_BINARY_BYTES,
            )
            if candidate_payload.startswith(b"%PDF"):
                frozen_gap = freeze_bytes(
                    output,
                    f"luma-gap-{missing_day}.pdf",
                    candidate_payload,
                )
                gap_probes.append(
                    {
                        "date": missing_day,
                        "candidate_url": candidate,
                        "state": "DISCOVERED_UNINDEXED_MANIFESTATION",
                        "final_url": candidate_final,
                        "media_type": candidate_type,
                        **frozen_gap,
                    }
                )
            else:
                gap_probes.append(
                    {
                        "date": missing_day,
                        "candidate_url": candidate,
                        "state": "NON_PDF_RESPONSE",
                    }
                )
        except HTTPError as exc:
            gap_probes.append(
                {
                    "date": missing_day,
                    "candidate_url": candidate,
                    "state": f"HTTP_{exc.code}_DISCOVERY_NEGATIVE_NOT_ABSENCE",
                }
            )
        except (URLError, TimeoutError) as exc:
            gap_probes.append(
                {
                    "date": missing_day,
                    "candidate_url": candidate,
                    "state": "PROBE_BLOCKED",
                    "error": str(exc),
                }
            )

    latest = max(reports, key=lambda row: (row["date"], row["url"]))
    latest_payload, latest_final_url, latest_media_type = fetch(
        latest["url"],
        allowed_hosts={"lumapr.com", "www.lumapr.com"},
        max_bytes=MAX_BINARY_BYTES,
    )
    if not latest_payload.startswith(b"%PDF"):
        raise ValueError("latest LUMA Daily Availability payload is not PDF")
    latest_frozen = freeze_bytes(output, "luma-latest-daily-availability.pdf", latest_payload)

    unindexed = [
        row for row in gap_probes
        if row["state"] == "DISCOVERED_UNINDEXED_MANIFESTATION"
    ]
    manifestation_residue = [
        row for row in gap_probes
        if row["state"] != "DISCOVERED_UNINDEXED_MANIFESTATION"
    ]

    return {
        "source_family_id": "LUMA_DAILY_AVAILABILITY",
        "product_id": "LUMA_DAILY_AVAILABILITY_REPORTS",
        "scope": "Daily Availability Report product lineage published on the authoritative BPS index",
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
        "gap_probes": gap_probes,
        "unindexed_discovered_reports": unindexed,
        "missing_date_semantics": "DISCOVERY_ONLY_NOT_SOURCE_ABSENCE",
        "latest_payload": {
            "date": latest["date"],
            "indexed_url": latest["url"],
            "final_url": latest_final_url,
            "media_type": latest_media_type,
            **latest_frozen,
        },
        "bounded_index_snapshot_exhausted": True,
        "family_payload_product_denominator_exhausted": True,
        "product_denominator_basis": (
            "one authoritative Daily Availability Report product lineage and one canonical "
            "PDF payload route are explicitly governed"
        ),
        "manifestation_history_complete": False,
        "manifestation_history_residue": manifestation_residue,
        "historical_scope_before_first_indexed_date": "UNRESOLVED",
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
        {"uncompressed_size": size, "sha256": digest, "member_count": count}
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

    back_payload, back_final, back_type = fetch(
        EIA_EPM_BACKISSUES,
        allowed_hosts={"www.eia.gov", "eia.gov"},
        max_bytes=MAX_HTML_BYTES,
    )
    back_frozen = freeze_bytes(output, "eia-epm-backissues.html", back_payload)
    issues = parse_epm_backissues(back_payload, back_final)
    if not issues:
        raise ValueError("EIA EPM Previous Issues index exposed no monthly issues")

    unclassified = [row for row in issues if row["state"] == "UNCLASSIFIED"]
    if unclassified:
        raise ValueError(f"EIA EPM archive contains unclassified issue rows: {unclassified[:5]}")

    issue_keys = [(int(row["year"]), str(row["month"])) for row in issues]
    duplicate_issue_labels = sorted(
        [
            {"year": year, "month": month, "count": count}
            for (year, month), count in Counter(issue_keys).items()
            if count > 1
        ],
        key=lambda row: (row["year"], MONTH_NAMES.index(row["month"])),
    )
    archive_state_counts = dict(sorted(Counter(str(row["state"]) for row in issues).items()))

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
        "scope": "current EPM issue plus every monthly entry on the authoritative Previous Issues index",
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
        "previous_issues_url": EIA_EPM_BACKISSUES,
        "previous_issues_final_url": back_final,
        "previous_issues_media_type": back_type,
        "previous_issues_manifestation": back_frozen,
        "previous_issue_count": len(issues),
        "previous_issues": issues,
        "previous_issue_state_counts": archive_state_counts,
        "duplicate_issue_labels": duplicate_issue_labels,
        "bounded_current_release_exhausted": True,
        "bounded_previous_issues_index_exhausted": True,
        "family_payload_product_denominator_exhausted": True,
        "product_denominator_basis": (
            "current issue plus authoritative Previous Issues index classify every listed "
            "monthly issue representation as ZIP/PDF/explicit N/A"
        ),
        "manifestation_history_complete": True,
        "manifestation_history_residue": [],
        "historical_payload_bytes_frozen": False,
    }


def run(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    luma = certify_luma(output, retrieved_at)
    epm = certify_epm(output, retrieved_at)

    family_product_denominators_pass = all(
        bool(row["family_payload_product_denominator_exhausted"])
        for row in (luma, epm)
    )
    state = (
        "PASS_PRODUCT_DENOMINATORS_MANIFESTATION_RESIDUE_OPEN"
        if family_product_denominators_pass
        else "OPEN_PRODUCT_DENOMINATORS"
    )
    summary = {
        "schema_version": "aguayluz.source-product-denominator-certification/v2",
        "state": state,
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
            "product_denominator_separate_from_manifestation_completeness": True,
            "family_product_denominators_pass": family_product_denominators_pass,
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
