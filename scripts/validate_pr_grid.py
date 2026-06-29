#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

COLUMNS = [
    "Cell_ID",
    "Row_Index",
    "Column_Index",
    "Pixel_X_Min",
    "Pixel_Y_Min",
    "Pixel_X_Max",
    "Pixel_Y_Max",
    "Centroid_X",
    "Centroid_Y",
    "Dark_Pixel_Count",
    "Total_Pixel_Count",
    "Land_Pixel_Ratio",
    "Classification",
]
SHA = "17733f3f18c8a644e31c1eb25fb27b73b4bf353c6de57d5203c4311e05d64483"
CLASSES = {"Water_or_Empty", "Gridline_Dominant", "Coastline_or_Land"}


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(path: Path, require_sha: bool) -> list[str]:
    errors = []
    if not path.exists():
        return [f"missing grid CSV: {path}"]
    seen, rows, cols = set(), set(), set()
    count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            errors.append(f"unexpected columns: {reader.fieldnames}")
        for n, row in enumerate(reader, start=2):
            count += 1
            cid = row.get("Cell_ID", "")
            if cid in seen:
                errors.append(f"duplicate Cell_ID at line {n}: {cid}")
            seen.add(cid)
            try:
                r = int(row["Row_Index"])
                c = int(row["Column_Index"])
                dark = int(row["Dark_Pixel_Count"])
                total = int(row["Total_Pixel_Count"])
                ratio = float(row["Land_Pixel_Ratio"])
            except Exception as exc:
                errors.append(f"invalid numeric field at line {n}: {exc}")
                continue
            rows.add(r)
            cols.add(c)
            if not 0 <= r <= 255:
                errors.append(f"Row_Index out of bounds at line {n}: {r}")
            if not 0 <= c <= 383:
                errors.append(f"Column_Index out of bounds at line {n}: {c}")
            if dark < 0 or total <= 0 or dark > total:
                errors.append(f"invalid pixel counts at line {n}")
            if not 0.0 <= ratio <= 1.0:
                errors.append(f"Land_Pixel_Ratio out of range at line {n}: {ratio}")
            if row.get("Classification", "") not in CLASSES:
                errors.append(f"unexpected Classification at line {n}")
    if count != 98304:
        errors.append(f"unexpected row count: {count}")
    if len(seen) != 98304:
        errors.append(f"unexpected unique Cell_ID count: {len(seen)}")
    if rows != set(range(256)):
        errors.append("Row_Index coverage is not complete 0..255")
    if cols != set(range(384)):
        errors.append("Column_Index coverage is not complete 0..383")
    if require_sha and file_sha(path) != SHA:
        errors.append("unexpected SHA-256")
    return errors


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--grid", default="registry/spatial/pr_grid_full_cell_index_saturated.csv")
    p.add_argument("--require-sha", action="store_true")
    a = p.parse_args()
    errors = validate(Path(a.grid), a.require_sha)
    if errors:
        print("[FAIL] PR baseline grid validation failed", file=sys.stderr)
        for e in errors:
            print(f" - {e}", file=sys.stderr)
        return 1
    print("[OK] PR baseline grid validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
