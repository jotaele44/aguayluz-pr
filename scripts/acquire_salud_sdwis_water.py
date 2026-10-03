#!/usr/bin/env python3
"""Acquire and freeze the authoritative Salud 2025 + EPA SDWIS water sources.

Network access is intentionally isolated to this acquisition layer. The downstream
ingestion contract consumes local immutable bytes only.

The EPA national ZIP is a transport container. The exact
SDWA_VIOLATIONS_ENFORCEMENT.csv member is extracted byte-for-byte, hashed, retained,
and then scoped to Puerto Rico by the ingestion layer without pretending a derived
PR-only file is the authoritative manifestation.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from scripts.ingest_salud_sdwis_water import run as ingest_run

SALUD = {
    "10746": "https://www.salud.pr.gov/CMS/DOWNLOAD/10746",
    "10747": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
    "10748": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
}
EPA_ZIP_URL = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
EPA_MEMBER_BASENAME = "SDWA_VIOLATIONS_ENFORCEMENT.csv"
USER_AGENT = "AguaYLuz-PR-source-freeze/1.0 (+https://github.com/jotaele44/aguayluz-pr)"


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    digest = sha256()
    byte_length = 0
    with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as output:
        status = int(getattr(response, "status", 200))
        if status < 200 or status >= 300:
            raise ValueError(f"unexpected HTTP status {status} for {url}")
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            output.write(chunk)
            digest.update(chunk)
            byte_length += len(chunk)
        headers = {key.lower(): value for key, value in response.headers.items()}
        final_url = response.geturl()
    partial.replace(destination)
    return {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "headers": headers,
        "byte_length": byte_length,
        "sha256": digest.hexdigest(),
        "file": destination.name,
    }


def _validate_pdf(path: Path) -> None:
    with path.open("rb") as handle:
        magic = handle.read(5)
    if magic != b"%PDF-":
        raise ValueError(f"{path} is not a PDF: magic={magic!r}")


def _validate_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"{path} is not a valid ZIP archive")
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
    if bad is not None:
        raise ValueError(f"ZIP CRC failure in member {bad}")


def locate_member(archive: zipfile.ZipFile, basename: str = EPA_MEMBER_BASENAME) -> str:
    matches = [
        name
        for name in archive.namelist()
        if Path(name).name.casefold() == basename.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {basename} member, found {matches}")
    return matches[0]


def extract_member(zip_path: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        member = locate_member(archive)
        info = archive.getinfo(member)
        with archive.open(member) as source, output_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
    return {
        "member_name": member,
        "member_crc32": f"{info.CRC:08x}",
        "member_uncompressed_size": info.file_size,
        "member_compressed_size": info.compress_size,
        "member_sha256": sha256_file(output_path),
        "file": output_path.name,
    }


def run(
    *,
    output_root: Path,
    year: int = 2025,
    discard_epa_archive_after_extract: bool = False,
) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    raw_root = output_root / "raw"
    salud_root = raw_root / "salud"
    epa_root = raw_root / "epa"
    output_root.mkdir(parents=True, exist_ok=True)

    salud_receipts: list[dict[str, Any]] = []
    salud_paths: dict[str, Path] = {}
    for source_id, url in SALUD.items():
        path = salud_root / f"{source_id}.pdf"
        receipt = _download(url, path)
        _validate_pdf(path)
        receipt["source_record_id"] = source_id
        receipt["content_magic"] = "%PDF-"
        salud_receipts.append(receipt)
        salud_paths[source_id] = path

    epa_zip = epa_root / "SDWA_latest_downloads.zip"
    epa_download = _download(EPA_ZIP_URL, epa_zip)
    _validate_zip(epa_zip)
    epa_download["archive_valid"] = True

    epa_member = epa_root / EPA_MEMBER_BASENAME
    member_receipt = extract_member(epa_zip, epa_member)
    if discard_epa_archive_after_extract:
        epa_zip.unlink()
        epa_download["retained_after_member_extraction"] = False
    else:
        epa_download["retained_after_member_extraction"] = True

    ingest_output = output_root / "ingest"
    ingestion = ingest_run(
        year=year,
        output_root=ingest_output,
        salud_public_notice=salud_paths["10746"],
        salud_report=salud_paths["10747"],
        salud_annex=salud_paths["10748"],
        sdwis_violations=epa_member,
        sdwis_source_url=f"{EPA_ZIP_URL}#{member_receipt['member_name']}",
        sdwis_scope_pws_prefix="PR",
    )

    receipt = {
        "schema_version": "aguayluz.salud_sdwis_acquisition/v1",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "target_calendar_year": year,
        "salud": salud_receipts,
        "epa_archive": epa_download,
        "epa_member": member_receipt,
        "ingestion_receipt": str(
            (ingest_output / "salud_sdwis_water_receipt.json").relative_to(output_root)
        ),
        "sdwis_source_arithmetic": ingestion["sdwis_source_arithmetic"],
        "salud_artifact_arithmetic": ingestion["salud_artifact_arithmetic"],
        "certification_state": ingestion["certification_state"],
        "source_universe_completeness_claimed": False,
        "guardrails": [
            "Downloaded source bytes are frozen before parsing.",
            "EPA national ZIP and SDWA_VIOLATIONS_ENFORCEMENT member identities remain distinct.",
            "Puerto Rico scoping is a deterministic read of the full frozen EPA member, not a replacement source file.",
            "Salud annual-report bytes remain separate historical manifestations from federal SDWIS snapshots.",
        ],
    }
    (output_root / "acquisition_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--discard-epa-archive-after-extract", action="store_true")
    args = parser.parse_args()
    try:
        receipt = run(
            output_root=args.output_root,
            year=args.year,
            discard_epa_archive_after_extract=args.discard_epa_archive_after_extract,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Salud/SDWIS acquisition failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
