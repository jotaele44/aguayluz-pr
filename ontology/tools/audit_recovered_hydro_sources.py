#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(str(p) for p in parts if p is not None)
    return f"{prefix}_{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def member_name(zf: zipfile.ZipFile, basename: str) -> str:
    matches = [n for n in zf.namelist() if Path(n).name == basename and not n.startswith("__MACOSX/")]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {basename!r}, got {matches!r}")
    return matches[0]


def nonblank_csv_rows(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(archive: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    archive_bytes = archive.read_bytes()
    expected_archive = manifest["archive"]
    if len(archive_bytes) != expected_archive["size_bytes"] or sha256(archive_bytes) != expected_archive["sha256"]:
        raise RuntimeError("archive byte identity mismatch")

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        water_name = member_name(zf, "Waterworks_Integrated_v2.csv")
        canal_name = member_name(zf, "Canal_de_Riego_features_summary.csv")
        water_bytes = zf.read(water_name)
        canal_bytes = zf.read(canal_name)

    for basename, data in (("Waterworks_Integrated_v2.csv", water_bytes), ("Canal_de_Riego_features_summary.csv", canal_bytes)):
        expected = manifest["members"][basename]
        if len(data) != expected["size_bytes"] or sha256(data) != expected["sha256"]:
            raise RuntimeError(f"member byte identity mismatch: {basename}")

    water_text = water_bytes.decode("utf-8-sig")
    canal_text = canal_bytes.decode("utf-8-sig")
    water_rows = list(csv.DictReader(io.StringIO(water_text)))
    canal_rows = nonblank_csv_rows(canal_text)
    if len(water_rows) != 3202 or len(canal_rows) != 3187:
        raise RuntimeError("recovered source denominator changed")

    blank_rows = [n for n, row in enumerate(water_rows, 1) if not any(str(v or "").strip() for v in row.values())]
    if blank_rows != list(range(1, 11)):
        raise RuntimeError(f"unexpected blank waterworks rows: {blank_rows!r}")

    derived_rows = water_rows[10:3197]
    if len(derived_rows) != len(canal_rows):
        raise RuntimeError("canal/derived denominator mismatch")

    max_lat_delta = 0.0
    max_lon_delta = 0.0
    max_len_delta = 0.0
    mismatch_count = 0
    mapping_digest = hashlib.sha256()
    for raw, derived in zip(canal_rows, derived_rows, strict=True):
        oid = int(raw["OBJECTID"])
        expected_id = f"SW-CAN-{oid:05d}"
        lat_delta = abs(float(raw["centroid_lat"]) - float(derived["Latitude"]))
        lon_delta = abs(float(raw["centroid_lon"]) - float(derived["Longitude"]))
        len_delta = abs(float(raw["length_m"]) - float(derived["Segment_Length_m"]))
        max_lat_delta = max(max_lat_delta, lat_delta)
        max_lon_delta = max(max_lon_delta, lon_delta)
        max_len_delta = max(max_len_delta, len_delta)
        ok = derived["Asset_ID"] == expected_id and lat_delta <= 1e-12 and lon_delta == 0.0 and len_delta <= 1e-9
        if not ok:
            mismatch_count += 1
        mapping_digest.update(f"{oid}|{expected_id}|{raw['centroid_lon']}|{raw['centroid_lat']}|{raw['length_m']}\n".encode())

    usgs = water_rows[3197:3202]
    gages = [r for r in usgs if "discharge/gage height" in (r.get("Function") or "").lower()]
    water_quality = [r for r in usgs if "water-quality sample site" in (r.get("Function") or "").lower()]
    if len(gages) != 4 or len(water_quality) != 1:
        raise RuntimeError("USGS observation subtype counts changed")

    parser_artifact_id = stable_id("LOCAL", "Canal_de_Riego_features_summary.csv", 1)
    starting_source_rows = 8475
    projected_classified = 8245
    projected_excluded = 11
    projected_unresolved = 219
    projected_total = projected_classified + projected_excluded + projected_unresolved
    report = {
        "archive_sha256": sha256(archive_bytes),
        "waterworks_rows": len(water_rows),
        "waterworks_blank_residue": len(blank_rows),
        "waterworks_canal_derived_manifestations": len(derived_rows),
        "waterworks_surface_water_gages": len(gages),
        "waterworks_water_quality_sample_sites_unresolved": len(water_quality),
        "canal_source_features": len(canal_rows),
        "canal_legacy_import_rows": len(canal_rows) + 1,
        "canal_parser_artifacts": 1,
        "canal_parser_artifact_legacy_asset_id": parser_artifact_id,
        "cross_manifestation_substantive_mismatches": mismatch_count,
        "max_latitude_abs_delta_degrees": max_lat_delta,
        "max_longitude_abs_delta_degrees": max_lon_delta,
        "max_length_abs_delta_m": max_len_delta,
        "mapping_sha256": mapping_digest.hexdigest(),
        "starting_source_rows": starting_source_rows,
        "starting_classified": 1867,
        "starting_unresolved": 6608,
        "projected_classified": projected_classified,
        "projected_excluded": projected_excluded,
        "projected_unresolved": projected_unresolved,
        "arithmetic_pass": projected_total == starting_source_rows,
        "identity_effect": "none",
        "physical_asset_count_claimed": False,
        "pr_wide_exhaustion_claimed": False,
    }
    if mismatch_count or not report["arithmetic_pass"]:
        raise RuntimeError(json.dumps(report, sort_keys=True))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=Path("ontology/recovered_hydro_sources.v0.1.json"))
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    report = audit(args.archive, args.manifest)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
