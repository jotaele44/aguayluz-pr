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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request(url: str, *, headers: dict[str, str] | None = None, method: str | None = None):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-SourceFreeze/1.2", **(headers or {})},
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
        ["pdfinfo", str(path)], check=True, capture_output=True, text=True
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
    with request(url, method="HEAD") as r:
        length = r.headers.get("Content-Length")
        if length is None:
            raise RuntimeError("EPA archive HEAD response lacks Content-Length")
        return {
            "final_url": r.geturl(),
            "content_length": int(length),
            "etag": r.headers.get("ETag"),
            "last_modified": r.headers.get("Last-Modified"),
            "accept_ranges": r.headers.get("Accept-Ranges"),
        }


def get_range(url: str, start: int, end: int) -> bytes:
    expected = end - start + 1
    with request(url, headers={"Range": f"bytes={start}-{end}"}) as r:
        data = r.read()
        if getattr(r, "status", None) != 206 or len(data) != expected:
            raise RuntimeError(
                f"range mismatch {start}-{end}: status={getattr(r, 'status', None)} "
                f"expected={expected} got={len(data)}"
            )
        return data


def locate_member(url: str, wanted: str) -> dict[str, Any]:
    ident = archive_identity(url)
    total = ident["content_length"]
    tail_len = min(total, 131072)
    tail = get_range(url, total - tail_len, total - 1)
    pos = tail.rfind(EOCD)
    if pos < 0 or pos + 22 > len(tail):
        raise RuntimeError("ZIP EOCD not found")
    sig, disk_no, cd_disk, _entries_disk, entries_total, cd_size, cd_offset, _comment_len = (
        struct.unpack_from("<4s4H2LH", tail, pos)
    )
    if sig != EOCD or disk_no != 0 or cd_disk != 0:
        raise RuntimeError("unsupported split ZIP")
    if 0xFFFFFFFF in {cd_size, cd_offset} or entries_total == 0xFFFF:
        raise RuntimeError("ZIP64 archive requires separate handling")

    cd = get_range(url, cd_offset, cd_offset + cd_size - 1)
    cursor = 0
    seen = 0
    found: dict[str, Any] | None = None
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
        name = name_bytes.decode("utf-8" if flags & 0x800 else "cp437")
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
        raise RuntimeError(f"{wanted} not found after {seen} entries")

    local_offset = found["local_header_offset"]
    local = get_range(url, local_offset, local_offset + 29)
    local_fields = struct.unpack("<4s5H3L2H", local)
    if local_fields[0] != LOCAL:
        raise RuntimeError("local-header signature mismatch")
    if local_fields[3] != found["compression_method"]:
        raise RuntimeError("central/local compression mismatch")
    local_name_len, local_extra_len = local_fields[-2:]
    found["data_start"] = local_offset + 30 + local_name_len + local_extra_len
    found["archive"] = ident
    found["central_directory_entries_declared"] = entries_total
    found["central_directory_entries_scanned_until_match"] = seen
    return found


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


def classify_pr_row(row: dict[str, str], year: int) -> tuple[str, str]:
    pwsid = (row.get("PWSID") or "").strip()
    violation_id = (row.get("VIOLATION_ID") or "").strip()
    if not pwsid or not violation_id:
        return "UNRESOLVED", "MISSING_PWSID_OR_VIOLATION_ID"
    if not pwsid.upper().startswith("PR"):
        return "EXCLUDED", "NON_PUERTO_RICO_PWSID"
    b = _parse_date(row.get("NON_COMPL_PER_BEGIN_DATE", ""))
    e = _parse_date(row.get("NON_COMPL_PER_END_DATE", ""))
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


def stream_member_and_filter_pr(
    url: str, meta: dict[str, Any], root: Path
) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    start = meta["data_start"]
    end = start + meta["compressed_size"] - 1
    compressed_hash = hashlib.sha256()
    uncompressed_hash = hashlib.sha256()
    crc = 0
    decompressor = zlib.decompressobj(-15) if meta["compression_method"] == 8 else None
    if meta["compression_method"] not in {0, 8}:
        raise RuntimeError(f"unsupported compression method {meta['compression_method']}")

    header: list[str] | None = None
    pr_rows: list[dict[str, str]] = []
    unresolved_raw: list[str] = []
    source_rows = 0
    non_pr_rows = 0
    pr_excluded = 0
    pr_unresolved = 0
    retained = 0
    logical = bytearray()
    line_buf = bytearray()
    total_uncompressed = 0

    def consume_record(raw_record: bytes) -> None:
        nonlocal header, source_rows, non_pr_rows, pr_excluded, pr_unresolved, retained
        record = raw_record.rstrip(b"\r\n")
        if not record:
            return
        if header is None:
            header = next(csv.reader([record.decode("utf-8-sig")]))
            required = {
                "PWSID",
                "VIOLATION_ID",
                "NON_COMPL_PER_BEGIN_DATE",
                "NON_COMPL_PER_END_DATE",
            }
            if not required.issubset({x.upper() for x in header}):
                raise RuntimeError("target member missing required columns")
            return
        source_rows += 1
        parts = record.split(b",", 2)
        if len(parts) < 3:
            pr_unresolved += 1
            unresolved_raw.append(f"ROW_{source_rows}:MALFORMED_FIELD_PREFIX")
            return
        pwsid_raw = parts[1].strip().strip(b'"').upper()
        if not pwsid_raw.startswith(b"PR"):
            non_pr_rows += 1
            return
        values = next(csv.reader([record.decode("utf-8")]))
        if len(values) != len(header):
            pr_unresolved += 1
            unresolved_raw.append(f"ROW_{source_rows}:COLUMN_COUNT_{len(values)}")
            return
        row = dict(zip(header, values, strict=True))
        disposition, reason = classify_pr_row(row, TARGET_YEAR)
        if disposition == "RETAINED":
            retained += 1
            pr_rows.append(row)
        elif disposition == "EXCLUDED":
            pr_excluded += 1
        else:
            pr_unresolved += 1
            unresolved_raw.append(
                f"ROW_{source_rows}:{reason}:{row.get('PWSID')}:{row.get('VIOLATION_ID')}"
            )

    print(
        f"STREAM EPA MEMBER compressed={meta['compressed_size']} "
        f"uncompressed={meta['uncompressed_size']}",
        flush=True,
    )
    with request(url, headers={"Range": f"bytes={start}-{end}"}) as r:
        if getattr(r, "status", None) != 206:
            raise RuntimeError(f"member range returned HTTP {getattr(r, 'status', None)}")
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            compressed_hash.update(chunk)
            out = decompressor.decompress(chunk) if decompressor else chunk
            if out:
                uncompressed_hash.update(out)
                crc = binascii.crc32(out, crc)
                total_uncompressed += len(out)
                line_buf.extend(out)
                while True:
                    nl = line_buf.find(b"\n")
                    if nl < 0:
                        break
                    piece = bytes(line_buf[: nl + 1])
                    del line_buf[: nl + 1]
                    logical.extend(piece)
                    if logical.count(b'"') % 2 == 0:
                        consume_record(bytes(logical))
                        logical.clear()
        if decompressor:
            tail = decompressor.flush()
            if tail:
                uncompressed_hash.update(tail)
                crc = binascii.crc32(tail, crc)
                total_uncompressed += len(tail)
                line_buf.extend(tail)

    logical.extend(line_buf)
    if logical:
        if logical.count(b'"') % 2:
            raise RuntimeError("unterminated quoted CSV record at member EOF")
        consume_record(bytes(logical))

    if total_uncompressed != meta["uncompressed_size"]:
        raise RuntimeError(
            f"uncompressed size mismatch expected={meta['uncompressed_size']} "
            f"actual={total_uncompressed}"
        )
    if (crc & 0xFFFFFFFF) != meta["crc32"]:
        raise RuntimeError("uncompressed CRC32 mismatch")

    accounted = retained + pr_excluded + pr_unresolved + non_pr_rows
    accounting = {
        "source": source_rows,
        "retained": retained,
        "excluded": non_pr_rows + pr_excluded,
        "excluded_non_pr": non_pr_rows,
        "excluded_pr_no_2025_overlap": pr_excluded,
        "unresolved": pr_unresolved,
        "accounted": accounted,
        "delta": source_rows - accounted,
    }
    accounting["state"] = "PASS" if accounting["delta"] == 0 else "FAIL"
    stream_meta = {
        "compressed_sha256": compressed_hash.hexdigest(),
        "uncompressed_sha256": uncompressed_hash.hexdigest(),
        "uncompressed_crc32": crc & 0xFFFFFFFF,
        "uncompressed_bytes_observed": total_uncompressed,
        "pr_2025_arithmetic": accounting,
    }
    return stream_meta, pr_rows, unresolved_raw


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
        salud_rows.append({
            "source_record_id": sid,
            "source_url": url,
            "retrieved_at_utc": retrieved,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "file": path.name,
            "http": headers,
            **pdf_meta(path),
        })

    print("LOCATE EPA TARGET MEMBER", flush=True)
    member_meta = locate_member(EPA_ZIP, TARGET_MEMBER)
    stream_meta, pr_rows, unresolved = stream_member_and_filter_pr(
        EPA_ZIP, member_meta, root
    )

    pr_csv = root / "SDWA_VIOLATIONS_ENFORCEMENT_PR_2025.csv"
    if not pr_rows:
        raise RuntimeError("bounded PR 2025 result set is empty")
    fieldnames = list(pr_rows[0])
    with pr_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(pr_rows)

    receipt = {
        "schema_version": "aguayluz.salud_sdwis_2025_source_freeze/v3",
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
            "target_member": {
                k: v for k, v in member_meta.items() if k not in {"archive", "data_start"}
            },
            **stream_meta,
            "pr_2025_csv": pr_csv.name,
            "pr_2025_csv_sha256": sha256_file(pr_csv),
            "unresolved_rows": unresolved,
        },
        "source_universe_completeness_claimed": False,
        "notes": [
            "Salud 10747 and 10748 are complete byte-frozen PDF manifestations.",
            "EPA target-member compressed and uncompressed identities are hashed during a single validated range stream.",
            "Every logical row in SDWA_VIOLATIONS_ENFORCEMENT.csv is counted in source arithmetic; only PR-prefixed PWSID rows are fully CSV-parsed.",
            "The national ZIP full-byte SHA remains OPEN; target-member byte identity and CRC are independently closed.",
            "No equality between Salud annual-report membership and the EPA PR-derived subset is asserted.",
        ],
    }
    (root / "source_freeze_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "salud": {"source": len(SALUD), "frozen": len(salud_rows)},
                "epa_member": member_meta["member_name"],
                "member_compressed_sha256": stream_meta["compressed_sha256"],
                "member_uncompressed_sha256": stream_meta["uncompressed_sha256"],
                "pr_2025_arithmetic": stream_meta["pr_2025_arithmetic"],
                "zip_full_sha256_status": "OPEN_NOT_DOWNLOADED",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
