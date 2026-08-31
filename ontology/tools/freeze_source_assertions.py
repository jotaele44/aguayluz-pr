#!/usr/bin/env python3
"""Freeze CSV source rows as non-identity infrastructure source assertions.

The caller must provide the actual header row number. The tool never assumes row 1
is a header, never canonicalizes raw field strings, and records the exact source
byte hash so regenerated assertions cannot be mistaken for byte identity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_source(data: bytes, requested_encoding: str | None) -> tuple[str, str]:
    candidates = [requested_encoding] if requested_encoding else ["utf-8-sig", "utf-8", "cp1252"]
    errors: list[str] = []
    for encoding in candidates:
        if encoding is None:
            continue
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}:{exc.start}")
    raise UnicodeDecodeError("unknown", data, 0, 1, f"unable to decode source with candidates {errors}")


def detect_delimiter(text: str) -> str:
    sample = text[:65536]
    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    return dialect.delimiter


def assertion_id(source_sha256: str, source_row_number: int, raw_fields: dict[str, Any]) -> str:
    payload = json.dumps(
        [source_sha256, source_row_number, raw_fields],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "AYL_SRC_" + hashlib.sha256(payload).hexdigest()[:20]


def parse_rows(
    *,
    text: str,
    source_file: str,
    source_sha256: str,
    source_size_bytes: int,
    encoding: str,
    delimiter: str,
    header_row_number: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if header_row_number < 1:
        raise ValueError("header_row_number must be >= 1")

    rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
    if header_row_number > len(rows):
        raise ValueError("header row is beyond end of file")

    headers = rows[header_row_number - 1]
    if not headers or not any(h != "" for h in headers):
        raise ValueError("declared header row is empty")
    if len(headers) != len(set(headers)):
        raise ValueError("duplicate raw header names require source-specific adjudication")

    assertions: list[dict[str, Any]] = []
    width_mismatches: list[int] = []
    blank_rows = 0
    for row_index, values in enumerate(rows[header_row_number:], start=header_row_number + 1):
        if not values or not any(value != "" for value in values):
            blank_rows += 1
            continue
        if len(values) != len(headers):
            width_mismatches.append(row_index)
            continue
        raw_fields = dict(zip(headers, values, strict=True))
        assertions.append(
            {
                "assertion_id": assertion_id(source_sha256, row_index, raw_fields),
                "source_file": source_file,
                "source_sha256": source_sha256,
                "source_size_bytes": source_size_bytes,
                "encoding": encoding,
                "delimiter": delimiter,
                "header_row_number": header_row_number,
                "raw_headers": headers,
                "source_row_number": row_index,
                "raw_fields": raw_fields,
                "linked_legacy_asset_id": None,
                "linked_canonical_object_id": None,
                "classification_decision_id": None,
                "identity_effect": "none",
                "notes": None,
            }
        )

    manifest = {
        "manifest_schema": "aguayluz.infrastructure-source-freeze/v0.1",
        "source_file": source_file,
        "source_sha256": source_sha256,
        "source_size_bytes": source_size_bytes,
        "encoding": encoding,
        "delimiter": delimiter,
        "header_row_number": header_row_number,
        "raw_headers": headers,
        "physical_rows_total": len(rows),
        "data_rows_retained": len(assertions),
        "blank_rows_excluded": blank_rows,
        "width_mismatch_rows": width_mismatches,
        "arithmetic": {
            "rows_after_header": max(0, len(rows) - header_row_number),
            "retained_plus_blank_plus_width_mismatch": len(assertions) + blank_rows + len(width_mismatches),
        },
        "identity_claimed": False,
        "certification_state": "PASS" if not width_mismatches else "OPEN",
    }
    manifest["arithmetic"]["pass"] = (
        manifest["arithmetic"]["rows_after_header"]
        == manifest["arithmetic"]["retained_plus_blank_plus_width_mismatch"]
    )
    if not manifest["arithmetic"]["pass"]:
        raise AssertionError("source-row arithmetic failed to close")
    return assertions, manifest


def freeze_source(
    src: Path,
    *,
    header_row_number: int,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = src.read_bytes()
    source_hash = sha256_bytes(data)
    text, used_encoding = decode_source(data, encoding)
    used_delimiter = delimiter or detect_delimiter(text)
    return parse_rows(
        text=text,
        source_file=src.name,
        source_sha256=source_hash,
        source_size_bytes=len(data),
        encoding=used_encoding,
        delimiter=used_delimiter,
        header_row_number=header_row_number,
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--header-row", type=int, required=True)
    parser.add_argument("--encoding", default=None)
    parser.add_argument("--delimiter", default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    assertions, manifest = freeze_source(
        args.src,
        header_row_number=args.header_row,
        encoding=args.encoding,
        delimiter=args.delimiter,
    )
    write_jsonl(args.out, assertions)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"source={args.src.name} retained={len(assertions)} "
        f"width_mismatches={len(manifest['width_mismatch_rows'])} "
        f"state={manifest['certification_state']}"
    )
    return 0 if manifest["certification_state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
