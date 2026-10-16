#!/usr/bin/env python3
"""Acquire and freeze the authoritative Salud 2025 + EPA SDWA source bytes.

Large source files remain CI artifacts, not repository blobs.  The receipt binds exact
URLs, final redirected URLs, HTTP metadata, byte lengths, SHA-256 values, PDF page/text
inventories, the complete EPA ZIP member inventory, and the exact
SDWA_VIOLATIONS_ENFORCEMENT.csv member bytes used by the reconciliation step.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

SALUD_SOURCES = {
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
EPA_ARCHIVE_URL = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
SDWIS_MEMBER_BASENAME = "SDWA_VIOLATIONS_ENFORCEMENT.csv"
PWSID_RE = re.compile(r"\bPR\d{7}\b", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(client: httpx.Client, url: str, target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    if temp.exists():
        temp.unlink()

    digest = sha256()
    byte_length = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with temp.open("wb") as handle:
            for chunk in response.iter_bytes(1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
                byte_length += len(chunk)
        metadata = {
            "source_url": url,
            "final_url": str(response.url),
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "content_length_header": response.headers.get("content-length"),
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "byte_length": byte_length,
            "byte_sha256": digest.hexdigest(),
        }
    if byte_length == 0:
        temp.unlink(missing_ok=True)
        raise ValueError(f"empty source response for {url}")
    temp.replace(target)
    return metadata


def _extract_pdf_inventory(path: Path, pages_path: Path) -> dict[str, Any]:
    if path.read_bytes()[:4] != b"%PDF":
        raise ValueError(f"{path} is not a PDF manifestation")

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - live acquisition dependency
        raise RuntimeError("pypdf is required for authoritative PDF inventory") from exc

    reader = PdfReader(str(path), strict=False)
    pages_path.parent.mkdir(parents=True, exist_ok=True)
    distinct_pwsids: set[str] = set()
    pwsid_occurrences = 0
    nonempty_pages = 0
    total_chars = 0
    total_lines = 0
    signal_lines: list[dict[str, Any]] = []

    with pages_path.open("w", encoding="utf-8") as handle:
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = text.replace("\x00", "")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            pwsids = sorted({token.upper() for token in PWSID_RE.findall(text)})
            pwsid_occurrences += sum(len(PWSID_RE.findall(line)) for line in lines)
            distinct_pwsids.update(pwsids)
            if text.strip():
                nonempty_pages += 1
            total_chars += len(text)
            total_lines += len(lines)
            for line_number, line in enumerate(lines, start=1):
                hits = sorted({token.upper() for token in PWSID_RE.findall(line)})
                if hits and len(signal_lines) < 500:
                    signal_lines.append(
                        {
                            "page": page_number,
                            "line": line_number,
                            "pwsids": hits,
                            "text": line,
                        }
                    )
            row = {
                "page": page_number,
                "char_count": len(text),
                "line_count": len(lines),
                "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "pwsids": pwsids,
                "text": text,
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "page_count": len(reader.pages),
        "nonempty_text_pages": nonempty_pages,
        "total_text_chars": total_chars,
        "total_text_lines": total_lines,
        "distinct_pwsid_count": len(distinct_pwsids),
        "distinct_pwsids": sorted(distinct_pwsids),
        "pwsid_occurrences": pwsid_occurrences,
        "pwsid_signal_lines": signal_lines,
        "pages_jsonl": pages_path.name,
    }


def _archive_inventory(
    archive_path: Path,
    *,
    extracted_member_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    extracted_member_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        infos = sorted(archive.infolist(), key=lambda info: info.filename.casefold())
        inventory = [
            {
                "filename": info.filename,
                "file_size": info.file_size,
                "compress_size": info.compress_size,
                "crc32": f"{info.CRC:08x}",
                "is_dir": info.is_dir(),
            }
            for info in infos
        ]
        matches = [
            info
            for info in infos
            if Path(info.filename).name.casefold() == SDWIS_MEMBER_BASENAME.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected exactly one {SDWIS_MEMBER_BASENAME}, found "
                f"{[info.filename for info in matches]}"
            )
        info = matches[0]
        digest = sha256()
        byte_length = 0
        with archive.open(info, "r") as source, extracted_member_path.open("wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
                digest.update(chunk)
                byte_length += len(chunk)

    if byte_length != info.file_size:
        raise ValueError(
            f"member byte arithmetic mismatch: extracted={byte_length} zip={info.file_size}"
        )
    return inventory, {
        "archive_member": info.filename,
        "member_file_size": info.file_size,
        "member_compress_size": info.compress_size,
        "member_crc32": f"{info.CRC:08x}",
        "member_byte_length": byte_length,
        "member_sha256": digest.hexdigest(),
        "extracted_path": extracted_member_path.name,
    }


def run(output_root: Path) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    raw_root = output_root / "raw"
    pages_root = output_root / "pdf_pages"
    extracted_root = output_root / "extracted"
    output_root.mkdir(parents=True, exist_ok=True)

    timeout = httpx.Timeout(connect=30.0, read=900.0, write=900.0, pool=30.0)
    headers = {
        "User-Agent": "AguaYLuz-PR evidence acquisition/1.0",
        "Accept": "*/*",
    }
    salud_rows: list[dict[str, Any]] = []
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers=headers,
    ) as client:
        for source_id, spec in SALUD_SOURCES.items():
            target = raw_root / f"salud_{source_id}.pdf"
            metadata = _download(client, spec["url"], target)
            pdf_inventory = _extract_pdf_inventory(
                target,
                pages_root / f"salud_{source_id}.pages.jsonl",
            )
            salud_rows.append(
                {
                    "source_record_id": source_id,
                    "role": spec["role"],
                    **metadata,
                    "pdf_inventory": pdf_inventory,
                }
            )

        archive_path = raw_root / "SDWA_latest_downloads.zip"
        archive_metadata = _download(client, EPA_ARCHIVE_URL, archive_path)

    member_path = extracted_root / SDWIS_MEMBER_BASENAME
    zip_inventory, member_metadata = _archive_inventory(
        archive_path,
        extracted_member_path=member_path,
    )
    archive_metadata["zip_member_count"] = len(zip_inventory)
    archive_metadata["zip_members"] = zip_inventory
    archive_metadata["selected_member"] = member_metadata

    acquired = len(salud_rows) + 1
    receipt = {
        "schema_version": "aguayluz.salud_sdwis_source_acquisition/v1",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "salud_sources": salud_rows,
        "epa_sdwa_archive": archive_metadata,
        "source_arithmetic": {
            "declared_sources": len(SALUD_SOURCES) + 1,
            "acquired_sources": acquired,
            "unresolved_sources": len(SALUD_SOURCES) + 1 - acquired,
            "delta": len(SALUD_SOURCES) + 1 - acquired,
            "state": "PASS" if acquired == len(SALUD_SOURCES) + 1 else "FAIL",
        },
        "source_universe_completeness_claimed": False,
        "guardrails": [
            "Exact source bytes are frozen before normalization.",
            "PDF extraction is evidence indexing; extracted text never replaces source bytes.",
            "The EPA ZIP and selected CSV member retain independent hashes.",
            "Archive member enumeration is complete for the acquired ZIP manifestation.",
            "No source-row identity is inferred from system names.",
        ],
    }
    receipt_path = output_root / "source_acquisition_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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
        print(f"authoritative source acquisition failed: {exc}", file=sys.stderr)
        return 1

    summary = {
        "retrieved_at_utc": receipt["retrieved_at_utc"],
        "source_arithmetic": receipt["source_arithmetic"],
        "salud_sources": [
            {
                "source_record_id": row["source_record_id"],
                "byte_length": row["byte_length"],
                "byte_sha256": row["byte_sha256"],
                "page_count": row["pdf_inventory"]["page_count"],
                "distinct_pwsid_count": row["pdf_inventory"]["distinct_pwsid_count"],
                "pwsid_occurrences": row["pdf_inventory"]["pwsid_occurrences"],
            }
            for row in receipt["salud_sources"]
        ],
        "epa_sdwa_archive": {
            "byte_length": receipt["epa_sdwa_archive"]["byte_length"],
            "byte_sha256": receipt["epa_sdwa_archive"]["byte_sha256"],
            "zip_member_count": receipt["epa_sdwa_archive"]["zip_member_count"],
            "selected_member": receipt["epa_sdwa_archive"]["selected_member"],
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
