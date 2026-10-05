#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import csv
import hashlib
import io
import json
import shutil
import struct
import subprocess
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SALUD = {
    "10747": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
    "10748": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
}
EPA_ZIP = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
TARGET_MEMBER = "SDWA_VIOLATIONS_ENFORCEMENT.csv"
TARGET_YEAR = 2025
EOCD = b"PK\x05\x06"
CENTRAL = b"PK\x01\x02"
LOCAL = b"PK\x03\x04"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request(url: str, *, headers: dict[str, str] | None = None, method: str | None = None):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-SourceFreeze/1.1", **(headers or {})},
        method=method,
    )
    return urllib.request.urlopen(req, timeout=180)


def download(url: str, target: Path) -> dict[str, Any]:
    with request(url) as r, target.open("wb") as out:
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


def archive_identity(url: str) -> dict[str, Any]:
    try:
        with request(url, method="HEAD") as r:
            length = r.headers.get("Content-Length")
            if length is None:
                raise RuntimeError("HEAD response lacks Content-Length")
            return {
                "final_url": r.geturl(),
                "content_length": int(length),
                "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"),
                "accept_ranges": r.headers.get("Accept-Ranges"),
            }
    except Exception:
        with request(url, headers={"Range": "bytes=0-0"}) as r:
            cr = r.headers.get("Content-Range")
            if getattr(r, "status", None) != 206 or not cr or "/" not in cr:
                raise RuntimeError("EPA archive does not expose a bounded byte-range identity")
            return {
                "final_url": r.geturl(),
                "content_length": int(cr.rsplit("/", 1)[1]),
                "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"),
                "accept_ranges": r.headers.get("Accept-Ranges"),
            }


def get_range(url: str, start: int, end: int) -> bytes:
    expected = end - start + 1
    with request(url, headers={"Range": f"bytes={start}-{end}"}) as r:
        data = r.read()
        if getattr(r, "status", None) != 206:
            raise RuntimeError(f"range request returned HTTP {getattr(r, 'status', None)}")
        if len(data) != expected:
            raise RuntimeError(
                f"range length mismatch {start}-{end}: expected {expected}, got {len(data)}"
            )
        return data


def freeze_remote_zip_member(url: str, wanted: str, raw_root: Path) -> tuple[dict[str, Any], bytes]:
    ident = archive_identity(url)
    total = ident["content_length"]
    tail_len = min(total, 131072)
    tail_start = total - tail_len
    tail = get_range(url, tail_start, total - 1)
    pos = tail.rfind(EOCD)
    if pos < 0:
        raise RuntimeError("ZIP EOCD not found in bounded tail")
    if pos + 22 > len(tail):
        raise RuntimeError("truncated ZIP EOCD")
    (
        sig,
        disk_no,
        cd_disk,
        entries_disk,
        entries_total,
        cd_size,
        cd_offset,
        comment_len,
    ) = struct.unpack_from("<4s4H2LH", tail, pos)
    if sig != EOCD or disk_no != 0 or cd_disk != 0:
        raise RuntimeError("unsupported split/multidisk ZIP")
    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF or entries_total == 0xFFFF:
        raise RuntimeError("ZIP64 archive requires a dedicated parser")
    cd = get_range(url, cd_offset, cd_offset + cd_size - 1)

    cursor = 0
    found: dict[str, Any] | None = None
    seen = 0
    while cursor + 46 <= len(cd):
        if cd[cursor : cursor + 4] != CENTRAL:
            raise RuntimeError(f"central-directory signature mismatch at {cursor}")
        fields = struct.unpack_from("<4s6H3L5H2L", cd, cursor)
        (
            _sig,
            _made,
            _needed,
            flags,
            compression,
            _mtime,
            _mdate,
            crc32,
            compressed_size,
            uncompressed_size,
            name_len,
            extra_len,
            comment_len,
            _disk_start,
            _internal_attr,
            _external_attr,
            local_offset,
        ) = fields
        start = cursor + 46
        name_bytes = cd[start : start + name_len]
        encoding = "utf-8" if flags & 0x800 else "cp437"
        name = name_bytes.decode(encoding, errors="strict")
        seen += 1
        if name.upper().endswith(wanted.upper()):
            found = {
                "member_name": name,
                "flags": flags,
                "compression_method": compression,
                "crc32": crc32,
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "local_header_offset": local_offset,
            }
            break
        cursor = start + name_len + extra_len + comment_len
    if found is None:
        raise RuntimeError(f"{wanted} not found after scanning {seen} central entries")

    local_offset = found["local_header_offset"]
    local = get_range(url, local_offset, local_offset + 29)
    (
        local_sig,
        _needed,
        _flags,
        local_compression,
        _mtime,
        _mdate,
        _crc,
        _csize,
        _usize,
        local_name_len,
        local_extra_len,
    ) = struct.unpack("<4s5H3L2H", local)
    if local_sig != LOCAL:
        raise RuntimeError("local-header signature mismatch")
    if local_compression != found["compression_method"]:
        raise RuntimeError("central/local compression mismatch")
    data_start = local_offset + 30 + local_name_len + local_extra_len
    compressed = get_range(
        url,
        data_start,
        data_start + found["compressed_size"] - 1,
    )
    if found["compression_method"] == 0:
        member = compressed
    elif found["compression_method"] == 8:
        member = zlib.decompress(compressed, -15)
    else:
        raise RuntimeError(f"unsupported ZIP compression method {found['compression_method']}")
    if len(member) != found["uncompressed_size"]:
        raise RuntimeError("uncompressed member length mismatch")
    if (binascii.crc32(member) & 0xFFFFFFFF) != found["crc32"]:
        raise RuntimeError("member CRC32 mismatch")

    compressed_path = raw_root / "SDWA_VIOLATIONS_ENFORCEMENT.compressed.bin"
    compressed_path.write_bytes(compressed)
    found.update(
        {
            "archive": ident,
            "archive_full_sha256": None,
            "archive_full_sha256_status": "OPEN_NOT_DOWNLOADED",
            "central_directory_entries_declared": entries_total,
            "central_directory_entries_scanned_until_match": seen,
            "compressed_sha256": sha256_bytes(compressed),
            "compressed_file": compressed_path.name,
            "uncompressed_sha256": sha256_bytes(member),
        }
    )
    return found, member


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
    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc).isoformat()

    salud_rows = []
    for sid, url in SALUD.items():
        print(f"FREEZE SALUD {sid}", flush=True)
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

    print("FREEZE EPA TARGET MEMBER BY RANGE", flush=True)
    member_meta, member_bytes = freeze_remote_zip_member(EPA_ZIP, TARGET_MEMBER, raw)
    print(
        f"EPA MEMBER {member_meta['member_name']} compressed={member_meta['compressed_size']} "
        f"uncompressed={member_meta['uncompressed_size']}",
        flush=True,
    )

    reader = csv.DictReader(io.StringIO(member_bytes.decode("utf-8-sig")))
    fieldnames = [x.strip() for x in (reader.fieldnames or []) if x]
    required = {"PWSID", "VIOLATION_ID", "NON_COMPL_PER_BEGIN_DATE", "NON_COMPL_PER_END_DATE"}
    if not required.issubset({x.upper() for x in fieldnames}):
        raise RuntimeError(f"member missing required columns: {sorted(required)}")

    counts = {"RETAINED": 0, "EXCLUDED": 0, "UNRESOLVED": 0}
    retained_rows: list[dict[str, str]] = []
    unresolved_rows: list[dict[str, Any]] = []
    source_rows = 0
    for i, row in enumerate(reader, start=2):
        source_rows += 1
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
        "source": source_rows,
        "retained": counts["RETAINED"],
        "excluded": counts["EXCLUDED"],
        "unresolved": counts["UNRESOLVED"],
        "accounted": sum(counts.values()),
    }
    accounting["delta"] = accounting["source"] - accounting["accounted"]
    accounting["state"] = "PASS" if accounting["delta"] == 0 else "FAIL"

    receipt = {
        "schema_version": "aguayluz.salud_sdwis_2025_source_freeze/v2",
        "retrieved_at_utc": retrieved,
        "salud": {
            "source": len(SALUD),
            "frozen": len(salud_rows),
            "delta": len(SALUD) - len(salud_rows),
            "artifacts": salud_rows,
        },
        "epa": {
            "source_url": EPA_ZIP,
            "zip_identity": member_meta["archive"],
            "zip_full_sha256": None,
            "zip_full_sha256_status": "OPEN_NOT_DOWNLOADED",
            "target_member": {k: v for k, v in member_meta.items() if k != "archive"},
            "pr_2025_arithmetic": accounting,
            "pr_2025_csv": pr_csv.name,
            "pr_2025_csv_sha256": sha256_file(pr_csv),
            "unresolved_rows": unresolved_rows,
        },
        "source_universe_completeness_claimed": False,
        "notes": [
            "Salud PDF byte identities are frozen independently from extracted text.",
            "EPA target member was frozen from validated HTTP byte ranges of the official quarterly ZIP.",
            "EPA full-ZIP SHA-256 remains OPEN because the full 404 MB archive was not downloaded.",
            "PR 2025 inclusion requires PR PWSID and noncompliance-period overlap with calendar year 2025.",
            "This source freeze does not assert that Salud report membership equals the EPA derived subset.",
        ],
    }
    (root / "source_freeze_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "salud": {"source": len(SALUD), "frozen": len(salud_rows)},
        "epa_member": member_meta["member_name"],
        "pr_2025_arithmetic": accounting,
        "zip_full_sha256_status": "OPEN_NOT_DOWNLOADED",
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
