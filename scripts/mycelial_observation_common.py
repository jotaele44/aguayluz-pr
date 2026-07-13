#!/usr/bin/env python3
"""Shared helpers for AguaYLuz mycelial observation materialization."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aguayluz.mycelial_models import (  # noqa: E402
    GridCellAggregation,
    ObservationSource,
    RawObservation,
    SourceLicense,
    VerificationStatus,
)

DATA_DIR = ROOT / "data" / "mycelial"
GEO_DIR = ROOT / "data" / "geo"
OUTPUTS_DIR = ROOT / "outputs"
RAW = DATA_DIR / "raw_observations.jsonl"
NORMALIZED = DATA_DIR / "normalized_observations.jsonl"
VERIFIED = DATA_DIR / "verified_observations.jsonl"
SOURCES = DATA_DIR / "observation_sources.jsonl"
LICENSES = DATA_DIR / "source_licenses.jsonl"
VERIFICATIONS = DATA_DIR / "verification_statuses.jsonl"
DEDUPES = DATA_DIR / "dedupe_clusters.jsonl"
GRID = DATA_DIR / "grid_cell_aggregations.jsonl"
OBS_GEOJSON = GEO_DIR / "mycelial_observations.geojson"
GRID_GEOJSON = GEO_DIR / "mycelial_grid.geojson"
SUMMARY = OUTPUTS_DIR / "mycelial_observation_report.json"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(str(part) for part in parts if part is not None)
    return f"{prefix}_{hashlib.sha256(payload.encode()).hexdigest()[:32]}"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def validate_sources() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    licenses = load_jsonl(LICENSES)
    sources = load_jsonl(SOURCES)
    for row in licenses:
        SourceLicense(**row)
    for row in sources:
        ObservationSource(**row)
    return licenses, sources


def normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    source_ref = str(row.get("source_ref") or row.get("source_url") or "local://unknown")
    source_id = row.get("source_id") or stable_id("obs_src", source_ref)
    taxon_label = str(
        row.get("taxon_label_raw") or row.get("scientific_name") or row.get("taxon") or "Fungi"
    )
    lat = float(row["lat"])
    lon = float(row["lon"])
    record = {
        "observation_id": row.get("observation_id")
        or stable_id("myc_obs", source_id, source_ref, taxon_label, lat, lon, row.get("observed_at")),
        "source_id": source_id,
        "observed_at": row.get("observed_at"),
        "reported_at": row.get("reported_at"),
        "taxon_label_raw": taxon_label,
        "taxon_rank": row.get("taxon_rank") or "unknown",
        "scientific_name": row.get("scientific_name"),
        "common_name": row.get("common_name"),
        "substrate": row.get("substrate") or "unknown",
        "habitat_context": row.get("habitat_context") or "unknown",
        "municipality": row.get("municipality"),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "coordinate_precision_m": float(row.get("coordinate_precision_m") or 0),
        "location_source": row.get("location_source") or "unknown",
        "photo_refs": row.get("photo_refs") or [],
        "voucher_ref": row.get("voucher_ref"),
        "observer_type": row.get("observer_type") or "unknown",
        "source_ref": source_ref,
        "source_hash": row.get("source_hash"),
        "evidence_tier": row.get("evidence_tier") or "T3",
        "license_id": row.get("license_id") or stable_id("license", source_ref),
        "access_guidance_present": bool(row.get("access_guidance_present", False)),
        "review_status": row.get("review_status") or "needs_review",
        "confidence": int(row.get("confidence") or 50),
    }
    RawObservation(**record)
    return record


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_record(row) for row in rows]


def dedupe_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    buckets: dict[tuple[str, float, float, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("scientific_name") or row.get("taxon_label_raw")).lower(),
            round(float(row["lat"]), 3),
            round(float(row["lon"]), 3),
            row.get("observed_at"),
        )
        buckets[key].append(row)
    clusters = []
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        canonical = sorted(members, key=lambda item: (-int(item.get("confidence", 0)), item["observation_id"]))[0]
        clusters.append({
            "cluster_id": stable_id("myc_dup", *key),
            "canonical_observation_id": canonical["observation_id"],
            "member_observation_ids": sorted(item["observation_id"] for item in members),
            "match_key": {"taxon": key[0], "lat_bin": key[1], "lon_bin": key[2], "observed_at": key[3]},
        })
    return rows, clusters


def verify_rows(
    rows: list[dict[str, Any]], clusters: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    duplicate_members = set()
    for cluster in clusters or []:
        canonical = cluster["canonical_observation_id"]
        duplicate_members.update(
            observation for observation in cluster["member_observation_ids"] if observation != canonical
        )
    statuses = []
    for row in rows:
        flags: list[str] = []
        status, delta = "location_verified", 10
        if row["observation_id"] in duplicate_members:
            flags.append("duplicate_candidate")
            status, delta = "duplicate", -10
        if row.get("access_guidance_present"):
            flags.append("access_guidance_detected")
            status, delta = "blocked", -100
            row["review_status"] = "blocked"
        elif row.get("review_status") == "rejected":
            status, delta = "rejected", -50
        elif row.get("scientific_name"):
            status, delta = "taxon_verified", 15
        row["confidence"] = max(0, min(100, int(row.get("confidence", 0)) + delta))
        RawObservation(**row)
        verification = {
            "verification_id": stable_id("ver", row["observation_id"], status),
            "observation_id": row["observation_id"],
            "status": status,
            "verification_method": "metadata_consistency",
            "reviewer": None,
            "verified_at": now_utc(),
            "confidence_delta": delta,
            "flags": flags,
            "notes": None,
        }
        VerificationStatus(**verification)
        statuses.append(verification)
    return rows, statuses


def _cell_key(row: dict[str, Any], resolution: float = 0.05) -> tuple[float, float]:
    return (
        round(round(float(row["lat"]) / resolution) * resolution, 4),
        round(round(float(row["lon"]) / resolution) * resolution, 4),
    )


def _dominant(values: list[str | None]) -> str | None:
    usable = [value for value in values if value and value != "unknown"]
    return Counter(usable).most_common(1)[0][0] if usable else None


def aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("review_status") not in {"rejected", "blocked"}:
            cells[_cell_key(row)].append(row)
    aggregates = []
    for (lat, lon), members in sorted(cells.items()):
        observed = sorted(item.get("observed_at") for item in members if item.get("observed_at"))
        confidences = [int(item.get("confidence", 0)) for item in members]
        row = {
            "grid_id": stable_id("myc_grid", lat, lon),
            "grid_scheme": "degree_bin",
            "grid_resolution": "0.05_degree",
            "geometry": None,
            "centroid_lat": lat,
            "centroid_lon": lon,
            "municipalities": sorted({item["municipality"] for item in members if item.get("municipality")}),
            "observation_count": len(members),
            "verified_count": sum(1 for item in members if item.get("review_status") == "accepted"),
            "taxa_count": len({item.get("scientific_name") or item.get("taxon_label_raw") for item in members}),
            "dominant_habitat_context": _dominant([item.get("habitat_context") for item in members]),
            "dominant_substrate": _dominant([item.get("substrate") for item in members]),
            "first_observed_at": observed[0] if observed else None,
            "last_observed_at": observed[-1] if observed else None,
            "mean_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0,
            "source_count": len({item["source_id"] for item in members}),
            "attribution_refs": sorted({item["source_id"] for item in members}),
            "precision_mode": "aggregate_public",
            "review_status": "accepted"
            if all(item.get("review_status") == "accepted" for item in members)
            else "needs_review",
        }
        GridCellAggregation(**row)
        aggregates.append(row)
    return aggregates


def observations_geojson(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
                "properties": row,
            }
            for row in rows
            if row.get("review_status") not in {"rejected", "blocked"}
        ],
    }


def grid_geojson(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": row.get("geometry")
                or {"type": "Point", "coordinates": [row["centroid_lon"], row["centroid_lat"]]},
                "properties": {key: value for key, value in row.items() if key != "geometry"},
            }
            for row in rows
        ],
    }


def source_license_gaps(
    rows: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    licenses: list[dict[str, Any]],
) -> list[str]:
    """Return deterministic unresolved source/license references for exported observations."""
    source_by_id = {str(source.get("source_id")): source for source in sources}
    license_by_id = {str(license_row.get("license_id")): license_row for license_row in licenses}
    gaps: set[str] = set()
    for row in rows:
        source_id = str(row.get("source_id") or "")
        license_id = str(row.get("license_id") or "")
        source = source_by_id.get(source_id)
        if not source:
            gaps.add(f"missing_source:{source_id or 'unknown'}")
        elif source.get("license_id") != license_id:
            gaps.add(f"source_license_mismatch:{source_id}:{license_id or 'unknown'}")
        if not license_id or license_id not in license_by_id:
            gaps.add(f"missing_license:{license_id or 'unknown'}")
    return sorted(gaps)


def build_summary(
    rows: list[dict[str, Any]],
    aggregates: list[dict[str, Any]],
    sources: list[dict[str, Any]] | None = None,
    licenses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources = load_jsonl(SOURCES) if sources is None else sources
    licenses = load_jsonl(LICENSES) if licenses is None else licenses
    return {
        "module_id": "aguayluz-pr",
        "generated_at": now_utc(),
        "research_only": True,
        "records_total": len(rows),
        "records_exported_precise": sum(
            1 for row in rows if row.get("review_status") not in {"rejected", "blocked"}
        ),
        "grid_cells_total": len(aggregates),
        "municipalities_covered": sorted({row["municipality"] for row in rows if row.get("municipality")}),
        "source_ids": sorted({row["source_id"] for row in rows}),
        "remaining_source_license_gaps": source_license_gaps(rows, sources, licenses),
        "safety_notes": [
            "Precise coordinates are retained for research/operator workflows.",
            "Access-use guidance is blocked by schema and verification gates.",
            "Every observation must retain source and license attribution.",
        ],
    }


def write_exports(rows: list[dict[str, Any]], aggregates: list[dict[str, Any]]) -> None:
    write_json(OBS_GEOJSON, observations_geojson(rows))
    write_json(GRID_GEOJSON, grid_geojson(aggregates))
    write_json(SUMMARY, build_summary(rows, aggregates))


def parser(description: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--input", type=Path, default=None)
    result.add_argument("--output", type=Path, default=None)
    return result
