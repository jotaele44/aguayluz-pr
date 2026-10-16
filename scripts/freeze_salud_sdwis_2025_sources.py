#!/usr/bin/env python3
"""Freeze the authoritative 2025 Salud drinking-water family and EPA SDWA archive.

The source contract is byte-first:
1. freeze exact Salud 10746/10747/10748 PDF bytes;
2. freeze the complete official EPA SDWA ZIP manifestation;
3. enumerate its complete central-directory member denominator;
4. extract and independently hash the exact SDWA_VIOLATIONS_ENFORCEMENT.csv member;
5. classify every logical member row into the Puerto Rico/2025 bounded denominator.

No normalized hazard identity is inferred here.  Canonical revisioning is delegated to
scripts/ingest_salud_sdwis_water.py after these source manifestations are frozen.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SALUD = {
    "10746": {
        "role": "PUBLIC_NOTICE",
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10746",
    },
    "10747": {
        "role": "ANNUAL_VIOLATIONS_REPORT_2025",
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
    },
    "10748": {
        "role": "ANEJOS_APENDICES_2025",
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
    },
}
EPA_ZIP = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
TARGET_MEMBER = "SDWA_VIOLATIONS_ENFORCEMENT.csv"
TARGET_YEAR = 2025
PWSID_RE = re.compile(r"\bPR\d{7}\b", re.IGNORECASE)


def canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(url: str):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-SourceFreeze/2.0"},
    )
    return urllib.request.urlopen(req, timeout=900)


def download(url: str, target: Path) -> dict[str, Any]:
    """Download one authoritative manifestation while hashing the exact response bytes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    temp.unlink(missing_ok=True)
    digest = hashlib.sha256()
    observed = 0
    with request(url) as response, temp.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            observed += len(chunk)
        result = {
            "source_url": url,
            "final_url": response.geturl(),
            "status": getattr(response, "status", None),
            "content_type": response.headers.get_content_type(),
            "content_length_header": response.headers.get("Content-Length"),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
            "byte_length": observed,
            "byte_sha256": digest.hexdigest(),
        }
    if observed == 0:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"empty response for {url}")
    header_length = result["content_length_header"]
    if header_length is not None and int(header_length) != observed:
        temp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Content-Length mismatch for {url}: header={header_length} observed={observed}"
        )
    temp.replace(target)
    return result


def _pwsid_text_inventory(text: str) -> dict[str, Any]:
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    distinct: set[str] = set()
    occurrence_count = 0
    signals: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    total_lines = 0
    total_chars = 0

    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.rstrip() for line in page_text.splitlines()]
        nonempty = [line for line in lines if line.strip()]
        page_pwsids = sorted({match.upper() for match in PWSID_RE.findall(page_text)})
        distinct.update(page_pwsids)
        page_occurrences = len(PWSID_RE.findall(page_text))
        occurrence_count += page_occurrences
        total_lines += len(nonempty)
        total_chars += len(page_text)
        for line_number, line in enumerate(lines, start=1):
            hits = sorted({match.upper() for match in PWSID_RE.findall(line)})
            if hits and len(signals) < 1000:
                signals.append(
                    {
                        "page": page_number,
                        "line": line_number,
                        "pwsids": hits,
                        "text": line.strip(),
                    }
                )
        page_rows.append(
            {
                "page": page_number,
                "text_sha256": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                "char_count": len(page_text),
                "nonempty_line_count": len(nonempty),
                "pwsids": page_pwsids,
                "pwsid_occurrences": page_occurrences,
            }
        )

    return {
        "text_page_count": len(pages),
        "total_text_chars": total_chars,
        "total_nonempty_lines": total_lines,
        "distinct_pwsid_count": len(distinct),
        "distinct_pwsids": sorted(distinct),
        "pwsid_occurrences": occurrence_count,
        "pwsid_signal_lines": signals,
        "pages": page_rows,
    }


def pdf_meta(path: Path) -> dict[str, Any]:
    info = subprocess.run(
        ["pdfinfo", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    meta: dict[str, Any] = {}
    for line in info.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()

    text_path = path.with_suffix(".txt")
    subprocess.run(
        ["pdftotext", "-layout", str(path), str(text_path)],
        check=True,
    )
    text = text_path.read_text(encoding="utf-8", errors="replace")
    inventory = _pwsid_text_inventory(text)
    pdf_pages = int(meta.get("Pages", "0") or "0")
    if pdf_pages and inventory["text_page_count"] not in {pdf_pages, pdf_pages + 1}:
        raise RuntimeError(
            f"PDF/text page mismatch for {path}: "
            f"pdfinfo={pdf_pages} text={inventory['text_page_count']}"
        )
    return {
        "pdfinfo": meta,
        "page_count": pdf_pages,
        "text_sha256": sha256_file(text_path),
        "text_bytes": text_path.stat().st_size,
        "text_file": text_path.name,
        "text_inventory": inventory,
    }


def zip_inventory(
    archive_path: Path,
    *,
    target_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Enumerate 100% of ZIP members and extract exactly one target member."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        infos = sorted(archive.infolist(), key=lambda item: item.filename.casefold())
        inventory = [
            {
                "filename": info.filename,
                "file_size": info.file_size,
                "compress_size": info.compress_size,
                "crc32": f"{info.CRC:08x}",
                "compression_method": info.compress_type,
                "is_dir": info.is_dir(),
            }
            for info in infos
        ]
        matches = [
            info
            for info in infos
            if Path(info.filename).name.casefold() == TARGET_MEMBER.casefold()
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one {TARGET_MEMBER}; found {[item.filename for item in matches]}"
            )
        info = matches[0]
        digest = hashlib.sha256()
        observed = 0
        with archive.open(info) as source, target_path.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
                observed += len(chunk)

    if observed != info.file_size:
        raise RuntimeError(
            f"target-member byte mismatch: central={info.file_size} extracted={observed}"
        )
    if sha256_file(target_path) != digest.hexdigest():
        raise RuntimeError("target-member post-write SHA-256 mismatch")
    return inventory, {
        "member_name": info.filename,
        "member_file_size": info.file_size,
        "member_compress_size": info.compress_size,
        "member_crc32": f"{info.CRC:08x}",
        "member_sha256": digest.hexdigest(),
        "member_byte_length": observed,
        "member_file": target_path.name,
    }


def _parse_date(value: str):
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return "INVALID"


def classify_pr_row(row: dict[str, str], year: int) -> tuple[str, str]:
    pwsid = (row.get("PWSID") or "").strip()
    violation_id = (row.get("VIOLATION_ID") or "").strip()
    if not pwsid or not violation_id:
        return "UNRESOLVED", "MISSING_PWSID_OR_VIOLATION_ID"
    if not pwsid.upper().startswith("PR"):
        return "EXCLUDED", "NON_PUERTO_RICO_PWSID"

    begin = _parse_date(row.get("NON_COMPL_PER_BEGIN_DATE", ""))
    end = _parse_date(row.get("NON_COMPL_PER_END_DATE", ""))
    if begin == "INVALID":
        return "UNRESOLVED", "INVALID_BEGIN_DATE"
    if end == "INVALID":
        return "UNRESOLVED", "INVALID_END_DATE"
    if begin is None and end is None:
        return "UNRESOLVED", "NONCOMPLIANCE_PERIOD_MISSING"

    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    effective_begin = begin or datetime.min.replace(tzinfo=timezone.utc)
    effective_end = end or datetime.max.replace(tzinfo=timezone.utc)
    if effective_end < year_start or effective_begin > year_end:
        return "EXCLUDED", f"NO_{year}_OVERLAP"
    return "RETAINED", f"PR_{year}_OVERLAP"


def filter_pr_year(
    member_path: Path,
    *,
    year: int,
    output_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Classify every logical source row and materialize the retained PR/year subset."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = 0
    retained = 0
    excluded_non_pr = 0
    excluded_pr_no_overlap = 0
    unresolved = 0
    reasons: Counter[str] = Counter()
    unresolved_samples: list[dict[str, Any]] = []

    with (
        member_path.open("r", encoding="utf-8-sig", newline="") as handle,
        output_path.open("w", encoding="utf-8", newline="") as out,
    ):
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise RuntimeError("target member has no header")
        normalized_fields = {field.upper() for field in reader.fieldnames}
        required = {
            "SUBMISSIONYEARQUARTER",
            "PWSID",
            "VIOLATION_ID",
            "NON_COMPL_PER_BEGIN_DATE",
            "NON_COMPL_PER_END_DATE",
        }
        missing = sorted(required - normalized_fields)
        if missing:
            raise RuntimeError(f"target member missing required columns: {missing}")
        writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
        writer.writeheader()

        for source_line, row in enumerate(reader, start=2):
            source += 1
            disposition, reason = classify_pr_row(row, year)
            reasons[f"{disposition}:{reason}"] += 1
            if disposition == "RETAINED":
                retained += 1
                writer.writerow(row)
                continue
            if disposition == "EXCLUDED":
                if reason == "NON_PUERTO_RICO_PWSID":
                    excluded_non_pr += 1
                else:
                    excluded_pr_no_overlap += 1
                continue
            unresolved += 1
            if len(unresolved_samples) < 100:
                unresolved_samples.append(
                    {
                        "source_line": source_line,
                        "pwsid": row.get("PWSID"),
                        "violation_id": row.get("VIOLATION_ID"),
                        "reason": reason,
                    }
                )

    excluded = excluded_non_pr + excluded_pr_no_overlap
    accounted = retained + excluded + unresolved
    arithmetic = {
        "source": source,
        "retained": retained,
        "excluded": excluded,
        "excluded_non_pr": excluded_non_pr,
        "excluded_pr_no_year_overlap": excluded_pr_no_overlap,
        "unresolved": unresolved,
        "accounted": accounted,
        "delta": source - accounted,
        "state": "PASS" if source == accounted else "FAIL",
    }
    return {
        "source_arithmetic": arithmetic,
        "classification_reason_counts": dict(sorted(reasons.items())),
        "pr_year_csv": output_path.name,
        "pr_year_csv_sha256": sha256_file(output_path),
        "pr_year_csv_bytes": output_path.stat().st_size,
    }, unresolved_samples


def run(output_root: Path) -> dict[str, Any]:
    root = output_root
    raw = root / "raw"
    derived = root / "derived"
    raw.mkdir(parents=True, exist_ok=True)
    derived.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc).isoformat()

    salud_rows: list[dict[str, Any]] = []
    for source_id, spec in SALUD.items():
        print(f"FREEZE SALUD {source_id}", flush=True)
        path = raw / f"salud_{source_id}.pdf"
        http = download(spec["url"], path)
        if path.read_bytes()[:4] != b"%PDF":
            raise RuntimeError(f"{source_id} did not resolve to PDF bytes")
        metadata = pdf_meta(path)
        salud_rows.append(
            {
                "source_record_id": source_id,
                "role": spec["role"],
                "source_url": spec["url"],
                "retrieved_at_utc": retrieved,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "file": path.name,
                "http": http,
                **metadata,
            }
        )

    print("FREEZE EPA NATIONAL SDWA ZIP", flush=True)
    archive_path = raw / "SDWA_latest_downloads.zip"
    archive_http = download(EPA_ZIP, archive_path)
    archive_sha256 = sha256_file(archive_path)
    if archive_sha256 != archive_http["byte_sha256"]:
        raise RuntimeError("EPA archive download/post-write SHA-256 mismatch")

    member_path = raw / TARGET_MEMBER
    inventory, member = zip_inventory(
        archive_path,
        target_path=member_path,
    )
    if len(inventory) == 0:
        raise RuntimeError("EPA ZIP central-directory inventory is empty")

    pr_csv = derived / f"SDWA_VIOLATIONS_ENFORCEMENT_PR_{TARGET_YEAR}.csv"
    filter_receipt, unresolved_samples = filter_pr_year(
        member_path,
        year=TARGET_YEAR,
        output_path=pr_csv,
    )

    receipt = {
        "schema_version": "aguayluz.salud_sdwis_2025_source_freeze/v4",
        "retrieved_at_utc": retrieved,
        "salud": {
            "source": len(SALUD),
            "frozen": len(salud_rows),
            "delta": len(SALUD) - len(salud_rows),
            "state": "PASS" if len(salud_rows) == len(SALUD) else "FAIL",
            "artifacts": salud_rows,
        },
        "epa": {
            "source_url": EPA_ZIP,
            "zip_http": archive_http,
            "zip_file": archive_path.name,
            "zip_bytes": archive_path.stat().st_size,
            "zip_full_sha256": archive_sha256,
            "zip_full_sha256_status": "FROZEN",
            "central_directory_entries": len(inventory),
            "central_directory_inventory": inventory,
            "central_directory_inventory_sha256": canonical_json_sha256(inventory),
            "target_member": member,
            **filter_receipt,
            "unresolved_row_samples": unresolved_samples,
        },
        "source_universe_completeness_claimed": False,
        "notes": [
            "Salud 10746/10747/10748 are exact byte-frozen PDF manifestations.",
            "The complete EPA national SDWA ZIP is byte-frozen and SHA-256 bound.",
            "The complete ZIP central-directory member denominator is enumerated.",
            "The exact SDWA_VIOLATIONS_ENFORCEMENT.csv member is extracted and independently hashed.",
            "Every logical row in the target member is classified in source arithmetic.",
            "The PR/year subset is derived evidence and does not replace the national member bytes.",
            "No equality between Salud annual-report membership and the EPA PR-derived subset is asserted.",
        ],
    }
    receipt_path = root / "source_freeze_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = run(args.output_root)
    except Exception as exc:  # noqa: BLE001
        print(f"Salud/SDWIS source freeze failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "salud": {
                    "source": receipt["salud"]["source"],
                    "frozen": receipt["salud"]["frozen"],
                    "artifacts": [
                        {
                            "source_record_id": row["source_record_id"],
                            "sha256": row["sha256"],
                            "bytes": row["bytes"],
                            "pages": row["page_count"],
                            "distinct_pwsid_count": (
                                row["text_inventory"]["distinct_pwsid_count"]
                            ),
                            "pwsid_occurrences": row["text_inventory"]["pwsid_occurrences"],
                        }
                        for row in receipt["salud"]["artifacts"]
                    ],
                },
                "epa": {
                    "zip_full_sha256": receipt["epa"]["zip_full_sha256"],
                    "zip_bytes": receipt["epa"]["zip_bytes"],
                    "central_directory_entries": receipt["epa"]["central_directory_entries"],
                    "member": receipt["epa"]["target_member"],
                    "source_arithmetic": receipt["epa"]["source_arithmetic"],
                    "pr_year_csv_sha256": receipt["epa"]["pr_year_csv_sha256"],
                },
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
