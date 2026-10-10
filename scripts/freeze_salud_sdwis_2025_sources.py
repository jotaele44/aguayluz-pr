#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SALUD = {
    "10747": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
    "10748": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
}
EPA_ZIP = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
TARGET_YEAR = 2025


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, target: Path) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "AguaYLuz-SourceFreeze/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, target.open("wb") as out:
        shutil.copyfileobj(r, out)
        return {
            "final_url": r.geturl(),
            "status": getattr(r, "status", None),
            "content_type": r.headers.get_content_type(),
            "content_length_header": r.headers.get("Content-Length"),
            "last_modified": r.headers.get("Last-Modified"),
            "etag": r.headers.get("ETag"),
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
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    text_path = path.with_suffix(".txt")
    subprocess.run(["pdftotext", "-layout", str(path), str(text_path)], check=True)
    return {
        "pdfinfo": meta,
        "text_sha256": sha256_file(text_path),
        "text_bytes": text_path.stat().st_size,
        "text_file": text_path.name,
    }


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return "INVALID"


def _v(row: dict[str, str], key: str) -> str:
    for k, v in row.items():
        if (k or "").strip().upper() == key.upper():
            return (v or "").strip()
    return ""


def classify(row: dict[str, str], year: int) -> tuple[str, str]:
    pwsid = _v(row, "PWSID")
    violation_id = _v(row, "VIOLATION_ID")
    if not pwsid or not violation_id:
        return "UNRESOLVED", "MISSING_PWSID_OR_VIOLATION_ID"
    if not pwsid.upper().startswith("PR"):
        return "EXCLUDED", "NON_PUERTO_RICO_PWSID"

    b_raw = _v(row, "NON_COMPL_PER_BEGIN_DATE")
    e_raw = _v(row, "NON_COMPL_PER_END_DATE")
    b = _parse_date(b_raw)
    e = _parse_date(e_raw)
    if b == "INVALID":
        return "UNRESOLVED", "INVALID_BEGIN_DATE"
    if e == "INVALID":
        return "UNRESOLVED", "INVALID_END_DATE"
    if b is None and e is None:
        return "UNRESOLVED", "NONCOMPLIANCE_PERIOD_MISSING"

    ys = datetime(year, 1, 1, tzinfo=timezone.utc)
    ye = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    eb = b or datetime.min.replace(tzinfo=timezone.utc)
    ee = e or datetime.max.replace(tzinfo=timezone.utc)
    if ee < ys or eb > ye:
        return "EXCLUDED", "NO_2025_OVERLAP"
    return "RETAINED", "PR_2025_OVERLAP"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-root", type=Path, required=True)
    args = p.parse_args()

    root = args.output_root
    root.mkdir(parents=True, exist_ok=True)
    raw = root / "raw"
    raw.mkdir(exist_ok=True)

    retrieved = datetime.now(timezone.utc).isoformat()
    salud_rows = []
    for sid, url in SALUD.items():
        path = raw / f"salud_{sid}.pdf"
        headers = download(url, path)
        if path.read_bytes()[:4] != b"%PDF":
            raise RuntimeError(f"{sid} did not resolve to PDF bytes")
        meta = pdf_meta(path)
        salud_rows.append({
            "source_record_id": sid,
            "source_url": url,
            "retrieved_at_utc": retrieved,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "file": path.name,
            "http": headers,
            **meta,
        })

    epa_path = raw / "SDWA_latest_downloads.zip"
    epa_http = download(EPA_ZIP, epa_path)
    epa_sha = sha256_file(epa_path)

    with zipfile.ZipFile(epa_path) as zf:
        names = zf.namelist()
        member = next(
            (n for n in names if n.upper().endswith("SDWA_VIOLATIONS_ENFORCEMENT.CSV")),
            None,
        )
        if member is None:
            raise RuntimeError("SDWA_VIOLATIONS_ENFORCEMENT.csv not found in official EPA ZIP")
        member_bytes = zf.read(member)

    member_path = raw / "SDWA_VIOLATIONS_ENFORCEMENT.csv"
    member_path.write_bytes(member_bytes)

    reader = csv.DictReader(io.StringIO(member_bytes.decode("utf-8-sig")))
    fieldnames = [x.strip() for x in (reader.fieldnames or []) if x]
    rows = [dict(r) for r in reader]
    counts = {"RETAINED": 0, "EXCLUDED": 0, "UNRESOLVED": 0}
    retained_rows: list[dict[str, str]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=2):
        disp, reason = classify(row, TARGET_YEAR)
        counts[disp] += 1
        if disp == "RETAINED":
            retained_rows.append(row)
        elif disp == "UNRESOLVED":
            unresolved_rows.append({
                "line": i,
                "reason": reason,
                "pwsid": _v(row, "PWSID") or None,
                "violation_id": _v(row, "VIOLATION_ID") or None,
            })

    pr_csv = root / "SDWA_VIOLATIONS_ENFORCEMENT_PR_2025.csv"
    with pr_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(retained_rows)

    accounting = {
        "source": len(rows),
        "retained": counts["RETAINED"],
        "excluded": counts["EXCLUDED"],
        "unresolved": counts["UNRESOLVED"],
        "accounted": sum(counts.values()),
    }
    accounting["delta"] = accounting["source"] - accounting["accounted"]
    accounting["state"] = "PASS" if accounting["delta"] == 0 else "FAIL"

    receipt = {
        "schema_version": "aguayluz.salud_sdwis_2025_source_freeze/v1",
        "retrieved_at_utc": retrieved,
        "salud": {
            "source": len(SALUD),
            "frozen": len(salud_rows),
            "delta": len(SALUD) - len(salud_rows),
            "artifacts": salud_rows,
        },
        "epa": {
            "source_url": EPA_ZIP,
            "http": epa_http,
            "zip_frozen": True,
            "zip_sha256": epa_sha,
            "zip_bytes": epa_path.stat().st_size,
            "zip_member_count": len(names),
            "violations_member_found": True,
            "violations_member_name": member,
            "violations_member_sha256": hashlib.sha256(member_bytes).hexdigest(),
            "violations_member_bytes": len(member_bytes),
            "violations_source_rows": len(rows),
            "pr_2025_arithmetic": accounting,
            "pr_2025_csv": pr_csv.name,
            "pr_2025_csv_sha256": sha256_file(pr_csv),
            "unresolved_rows": unresolved_rows,
        },
        "source_universe_completeness_claimed": False,
        "notes": [
            "Salud PDF byte identity is frozen independently from extracted text.",
            "EPA national ZIP is the authoritative manifestation; the PR 2025 CSV is a derived bounded subset.",
            "PR 2025 inclusion requires PR PWSID and noncompliance-period overlap with calendar year 2025.",
            "This source freeze does not assert that Salud's annual-report row universe equals the EPA derived subset.",
        ],
    }
    (root / "source_freeze_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

