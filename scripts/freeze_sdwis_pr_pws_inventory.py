#!/usr/bin/env python3
"""Freeze the latest Puerto Rico public-water-system inventory from EPA SDWIS.

The national ZIP is mutable and versioned. This script range-streams only
SDWA_PUB_WATER_SYSTEMS.csv, preserves the exact member byte identities, then
selects the latest Puerto Rico SUBMISSIONYEARQUARTER by stable PWSID.

The PRDOH 463-system figure is a count control only. Count equality never proves
membership identity; the emitted PWSID set is the candidate identity universe.
"""
from __future__ import annotations

import argparse
import binascii
import csv
import hashlib
import json
import struct
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EPA_ZIP = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
TARGET_MEMBER = "SDWA_PUB_WATER_SYSTEMS.csv"
EOCD = b"PK\x05\x06"
CENTRAL = b"PK\x01\x02"
LOCAL = b"PK\x03\x04"


def request(url: str, *, headers: dict[str, str] | None = None, method: str | None = None):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-PWSInventoryFreeze/1.0", **(headers or {})},
        method=method,
    )
    return urllib.request.urlopen(req, timeout=180)


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
    fields = struct.unpack_from("<4s4H2LH", tail, pos)
    sig, disk_no, cd_disk, _entries_disk, entries_total, cd_size, cd_offset, _comment = fields
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
        f = struct.unpack_from("<4s6H3L5H2L", cd, cursor)
        (
            _sig, _made, _needed, flags, compression, _mtime, _mdate, crc32,
            compressed_size, uncompressed_size, name_len, extra_len, comment_len,
            _disk_start, _internal_attr, _external_attr, local_offset,
        ) = f
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
    lf = struct.unpack("<4s5H3L2H", local)
    if lf[0] != LOCAL:
        raise RuntimeError("local-header signature mismatch")
    if lf[3] != found["compression_method"]:
        raise RuntimeError("central/local compression mismatch")
    local_name_len, local_extra_len = lf[-2:]
    found["data_start"] = local_offset + 30 + local_name_len + local_extra_len
    found["archive"] = ident
    found["central_directory_entries_declared"] = entries_total
    return found


def _field(row: dict[str, str], key: str) -> str:
    for k, v in row.items():
        if str(k).strip().upper() == key:
            return str(v or "").strip()
    return ""


def quarter_inventory(rows: list[dict[str, str]], quarter: str) -> dict[str, Any]:
    selected = [r for r in rows if _field(r, "SUBMISSIONYEARQUARTER") == quarter]
    ids = [_field(r, "PWSID").upper() for r in selected]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{quarter} Puerto Rico inventory violates PWSID uniqueness")
    active = [r for r in selected if _field(r, "PWS_ACTIVITY_CODE").upper() == "A"]
    active_ids = sorted(_field(r, "PWSID").upper() for r in active)
    active_type_counts: dict[str, int] = {}
    activity_counts: dict[str, int] = {}
    for row in selected:
        activity = _field(row, "PWS_ACTIVITY_CODE").upper() or "EMPTY"
        activity_counts[activity] = activity_counts.get(activity, 0) + 1
    for row in active:
        ptype = _field(row, "PWS_TYPE_CODE").upper() or "EMPTY"
        active_type_counts[ptype] = active_type_counts.get(ptype, 0) + 1
    return {
        "quarter": quarter,
        "rows": len(selected),
        "active_count": len(active),
        "active_pwsids": active_ids,
        "activity_counts": dict(sorted(activity_counts.items())),
        "active_type_counts": dict(sorted(active_type_counts.items())),
    }


def select_latest_pr(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("no Puerto Rico PWS rows")
    quarters = sorted({_field(r, "SUBMISSIONYEARQUARTER") for r in rows if _field(r, "SUBMISSIONYEARQUARTER")})
    if not quarters:
        raise ValueError("Puerto Rico PWS rows have no SUBMISSIONYEARQUARTER")
    latest = quarters[-1]
    latest_rows = [r for r in rows if _field(r, "SUBMISSIONYEARQUARTER") == latest]
    ids = [_field(r, "PWSID").upper() for r in latest_rows]
    if any(not x.startswith("PR") or len(x) != 9 for x in ids):
        raise ValueError("latest Puerto Rico inventory contains malformed PWSID")
    if len(ids) != len(set(ids)):
        raise ValueError("latest Puerto Rico inventory violates PWSID uniqueness")

    active_rows = [r for r in latest_rows if _field(r, "PWS_ACTIVITY_CODE").upper() == "A"]
    inactive_rows = [r for r in latest_rows if _field(r, "PWS_ACTIVITY_CODE").upper() != "A"]
    active_ids = sorted(_field(r, "PWSID").upper() for r in active_rows)
    activity_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for r in latest_rows:
        activity = _field(r, "PWS_ACTIVITY_CODE").upper() or "EMPTY"
        ptype = _field(r, "PWS_TYPE_CODE").upper() or "EMPTY"
        activity_counts[activity] = activity_counts.get(activity, 0) + 1
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
    return {
        "latest_quarter": latest,
        "latest_rows": latest_rows,
        "latest_row_count": len(latest_rows),
        "active_rows": active_rows,
        "active_count": len(active_rows),
        "active_pwsids": active_ids,
        "inactive_count": len(inactive_rows),
        "activity_counts": dict(sorted(activity_counts.items())),
        "type_counts": dict(sorted(type_counts.items())),
        "all_pr_quarters": quarters,
    }


def stream_member(url: str, meta: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    start = meta["data_start"]
    end = start + meta["compressed_size"] - 1
    compressed_hash = hashlib.sha256()
    uncompressed_hash = hashlib.sha256()
    decompressor = zlib.decompressobj(-15) if meta["compression_method"] == 8 else None
    if meta["compression_method"] not in {0, 8}:
        raise RuntimeError(f"unsupported compression method {meta['compression_method']}")

    crc = 0
    total_uncompressed = 0
    source_rows = 0
    non_pr_rows = 0
    pr_rows: list[dict[str, str]] = []
    header: list[str] | None = None
    line_buf = bytearray()
    logical = bytearray()

    def consume(record_bytes: bytes) -> None:
        nonlocal header, source_rows, non_pr_rows
        record = record_bytes.rstrip(b"\r\n")
        if not record:
            return
        if header is None:
            header = next(csv.reader([record.decode("utf-8-sig")]))
            required = {"SUBMISSIONYEARQUARTER", "PWSID", "PWS_ACTIVITY_CODE", "PWS_TYPE_CODE"}
            actual = {x.strip().upper() for x in header}
            if not required.issubset(actual):
                raise RuntimeError(f"PWS member missing required columns: {sorted(required-actual)}")
            return
        source_rows += 1
        values = next(csv.reader([record.decode("utf-8")]))
        if len(values) != len(header):
            raise RuntimeError(
                f"source row {source_rows+1} column mismatch: {len(values)} != {len(header)}"
            )
        row = dict(zip(header, values, strict=True))
        pwsid = _field(row, "PWSID").upper()
        if pwsid.startswith("PR"):
            pr_rows.append(row)
        else:
            non_pr_rows += 1

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
                        consume(bytes(logical))
                        logical.clear()
        if decompressor:
            tail = decompressor.flush()
            if tail:
                uncompressed_hash.update(tail)
                crc = binascii.crc32(tail, crc)
                total_uncompressed += len(tail)
                line_buf.extend(tail)
    if line_buf:
        logical.extend(line_buf)
    if logical:
        consume(bytes(logical))
    if total_uncompressed != meta["uncompressed_size"]:
        raise RuntimeError(
            f"uncompressed byte mismatch: {total_uncompressed} != {meta['uncompressed_size']}"
        )
    if (crc & 0xFFFFFFFF) != meta["crc32"]:
        raise RuntimeError("uncompressed CRC32 mismatch")
    if source_rows != non_pr_rows + len(pr_rows):
        raise RuntimeError("source row conservation failed")
    return {
        "compressed_sha256": compressed_hash.hexdigest(),
        "uncompressed_sha256": uncompressed_hash.hexdigest(),
        "uncompressed_bytes_observed": total_uncompressed,
        "source_rows": source_rows,
        "non_pr_rows": non_pr_rows,
        "pr_rows_all_quarters": len(pr_rows),
        "row_conservation_delta": source_rows - non_pr_rows - len(pr_rows),
    }, pr_rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--prdoh-control-count", type=int, default=463)
    args = p.parse_args()
    root = args.output_root
    root.mkdir(parents=True, exist_ok=True)

    before = archive_identity(EPA_ZIP)
    meta = locate_member(EPA_ZIP, TARGET_MEMBER)
    stream, pr_rows = stream_member(EPA_ZIP, meta)
    after = archive_identity(EPA_ZIP)
    for key in ("final_url", "content_length", "etag", "last_modified"):
        if after.get(key) != before.get(key):
            raise RuntimeError(
                f"archive identity drift during PWS member stream for {key}: "
                f"{before.get(key)!r} != {after.get(key)!r}"
            )
    selected = select_latest_pr(pr_rows)
    quarter_counts = {
        q: quarter_inventory(pr_rows, q)
        for q in selected["all_pr_quarters"]
    }
    report_quarter = quarter_inventory(pr_rows, "2025Q3")

    latest_csv = root / "SDWA_PUB_WATER_SYSTEMS_PR_LATEST.csv"
    fieldnames = list(selected["latest_rows"][0].keys())
    with latest_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(selected["latest_rows"])

    active_csv = root / "SDWA_PUB_WATER_SYSTEMS_PR_ACTIVE.csv"
    with active_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(selected["active_rows"])

    current_control = {
        "source": "Puerto Rico Department of Health 2025 annual violations report",
        "prdoh_as_of": "2025-09",
        "control_count": args.prdoh_control_count,
        "epa_quarter": selected["latest_quarter"],
        "epa_active_count": selected["active_count"],
        "count_delta": selected["active_count"] - args.prdoh_control_count,
        "state": "CROSS_PERIOD_CONTROL_NOT_ADJUDICATIVE",
    }
    report_period_control = {
        "source": "Puerto Rico Department of Health 2025 annual violations report",
        "prdoh_as_of": "2025-09",
        "control_count": args.prdoh_control_count,
        "epa_quarter": "2025Q3",
        "epa_active_count": report_quarter["active_count"],
        "count_delta": report_quarter["active_count"] - args.prdoh_control_count,
        "state": (
            "COUNT_EQUAL_NOT_IDENTITY"
            if report_quarter["active_count"] == args.prdoh_control_count
            else "COUNT_CONTRADICTION"
        ),
    }
    receipt = {
        "schema_version": "aguayluz.water_health.sdwis_pr_pws_inventory/v1",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": EPA_ZIP,
        "archive_identity": before,
        "archive_identity_after": after,
        "target_member": {k:v for k,v in meta.items() if k not in {"archive","data_start"}},
        "stream": stream,
        "latest_quarter": selected["latest_quarter"],
        "latest_row_count": selected["latest_row_count"],
        "active_count": selected["active_count"],
        "inactive_count": selected["inactive_count"],
        "activity_counts": selected["activity_counts"],
        "type_counts": selected["type_counts"],
        "active_pwsids": selected["active_pwsids"],
        "active_pwsid_count": len(selected["active_pwsids"]),
        "quarter_inventory": quarter_counts,
        "report_period_2025q3": report_quarter,
        "latest_csv": latest_csv.name,
        "latest_csv_sha256": hashlib.sha256(latest_csv.read_bytes()).hexdigest(),
        "active_csv": active_csv.name,
        "active_csv_sha256": hashlib.sha256(active_csv.read_bytes()).hexdigest(),
        "prdoh_463_current_cross_period_control": current_control,
        "prdoh_463_report_period_control": report_period_control,
        "identity_claim": "EPA_ACTIVE_PWSID_SET_CANDIDATE_UNIVERSE",
        "guardrails": [
            "Count equality does not prove PRDOH↔EPA membership identity.",
            "PWSID is the stable SDWIS system identifier.",
            "The mutable quarterly EPA source is frozen with member and archive manifestation metadata.",
            "Inactive and non-active rows are preserved in the latest-quarter source output.",
        ],
    }
    path = root / "sdwis_pr_pws_inventory_receipt.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({
        "latest_quarter": receipt["latest_quarter"],
        "latest_row_count": receipt["latest_row_count"],
        "active_count": receipt["active_count"],
        "inactive_count": receipt["inactive_count"],
        "activity_counts": receipt["activity_counts"],
        "type_counts": receipt["type_counts"],
        "report_period_2025q3": receipt["report_period_2025q3"],
        "prdoh_463_current_cross_period_control": current_control,
        "prdoh_463_report_period_control": report_period_control,
        "active_csv_sha256": receipt["active_csv_sha256"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
