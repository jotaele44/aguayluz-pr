#!/usr/bin/env python3
"""Project mycelial observations into the federation streams.

This extension is intentionally separate from scripts/federation_export.py so the
core water/power producer remains stable until the Hub accepts ecological
observation entity semantics.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "mycelial"
OUT_DIR = ROOT / "exports" / "federation_mycelial"
PRODUCER = "aguayluz-pr"
CONTRACT_VERSION = "1.0.0"


def _fid(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()[:32]}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lineage(phase: str) -> dict[str, Any]:
    return {
        "producer_script": "scripts/federation_export_mycelial.py",
        "producer_phase": phase,
        "source_inputs": [
            "data/mycelial/verified_observations.jsonl",
            "data/mycelial/observation_sources.jsonl",
            "data/mycelial/source_licenses.jsonl",
        ],
        "extraction_method": "deterministic_mycelial_observation_projection",
    }


def build_streams(observations: list[dict[str, Any]], sources_input: list[dict[str, Any]], now: str) -> dict[str, list[dict[str, Any]]]:
    source_rows: dict[str, dict[str, Any]] = {}
    entities: dict[str, dict[str, Any]] = {}
    relationships: dict[str, dict[str, Any]] = {}
    alerts: dict[str, dict[str, Any]] = {}

    for source in sources_input:
        sid = _fid("src", source.get("source_id"), source.get("source_ref"))
        source_rows[sid] = {
            "source_id": sid,
            "source_type": "public_record",
            "source_name": source.get("source_name") or source.get("source_ref"),
            "source_ref": source.get("source_ref"),
            "confidence": 0.75,
            "lineage": _lineage("MYCELIAL_SOURCE"),
            "synthetic": False,
            "created_at": now,
            "extracted_at": now,
        }

    for obs in observations:
        if obs.get("review_status") == "rejected":
            continue
        sid = _fid("src", obs.get("source_id"), obs.get("source_ref"))
        if sid not in source_rows:
            source_rows[sid] = {
                "source_id": sid,
                "source_type": "public_record",
                "source_name": obs.get("source_ref") or "mycelial observation source",
                "source_ref": obs.get("source_ref"),
                "confidence": round(float(obs.get("confidence", 50)) / 100, 4),
                "lineage": _lineage("MYCELIAL_SOURCE_FALLBACK"),
                "synthetic": False,
                "created_at": now,
                "extracted_at": now,
            }
        ent_id = _fid("ent", "mycelial_observation", obs.get("observation_id"))
        entities[ent_id] = {
            "entity_id": ent_id,
            "source_id": sid,
            "name": obs.get("scientific_name") or obs.get("taxon_label_raw") or obs.get("observation_id"),
            "normalized_name": str(obs.get("scientific_name") or obs.get("taxon_label_raw") or "FUNGI").upper(),
            "entity_type": "ecological_observation",
            "jurisdiction": "PR",
            "confidence": round(float(obs.get("confidence", 50)) / 100, 4),
            "lineage": _lineage("MYCELIAL_OBSERVATION_ENTITY"),
            "synthetic": False,
            "created_at": now,
            "extracted_at": now,
            "attributes": {
                "aguayluz_observation_id": obs.get("observation_id"),
                "taxon_label_raw": obs.get("taxon_label_raw"),
                "scientific_name": obs.get("scientific_name"),
                "substrate": obs.get("substrate"),
                "habitat_context": obs.get("habitat_context"),
                "coordinate_precision_m": obs.get("coordinate_precision_m"),
                "license_id": obs.get("license_id"),
                "research_only": True,
                "access_guidance_present": False,
            },
        }
        if isinstance(obs.get("lat"), (int, float)) and isinstance(obs.get("lon"), (int, float)):
            entities[ent_id]["location"] = {
                "lat": round(float(obs["lat"]), 6),
                "lon": round(float(obs["lon"]), 6),
                "municipality": obs.get("municipality"),
            }
        if obs.get("municipality"):
            muni_id = _fid("ent", "municipality", str(obs["municipality"]).upper())
            entities.setdefault(muni_id, {
                "entity_id": muni_id,
                "source_id": sid,
                "name": obs["municipality"],
                "normalized_name": str(obs["municipality"]).upper(),
                "entity_type": "municipality",
                "jurisdiction": "PR",
                "confidence": 0.95,
                "lineage": _lineage("MYCELIAL_MUNICIPALITY_ENTITY"),
                "synthetic": False,
                "created_at": now,
                "extracted_at": now,
            })
            rel_id = _fid("rel", ent_id, "located_in", muni_id)
            relationships[rel_id] = {
                "relationship_id": rel_id,
                "source_id": sid,
                "source_entity_id": ent_id,
                "target_entity_id": muni_id,
                "relationship_type": "located_in",
                "evidence_source_id": sid,
                "confidence": round(float(obs.get("confidence", 50)) / 100, 4),
                "lineage": _lineage("MYCELIAL_LOCATION_RELATIONSHIP"),
                "synthetic": False,
                "created_at": now,
                "extracted_at": now,
            }
        if obs.get("review_status") == "blocked":
            alert_id = _fid("alrt", obs.get("observation_id"), "blocked")
            alerts[alert_id] = {
                "alert_id": alert_id,
                "source_id": sid,
                "module": PRODUCER,
                "alert_type": "mycelial_observation_review",
                "severity": "medium",
                "status": "open",
                "gap_status": "needs_review",
                "observed_at": now,
                "attributes": {"observation_id": obs.get("observation_id"), "review_status": "blocked"},
                "confidence": 0.5,
                "lineage": _lineage("MYCELIAL_REVIEW_ALERT"),
                "synthetic": False,
                "created_at": now,
                "extracted_at": now,
            }

    return {
        "sources": list(source_rows.values()),
        "entities": list(entities.values()),
        "relationships": list(relationships.values()),
        "alerts": list(alerts.values()),
    }


def write_package(streams: dict[str, list[dict[str, Any]]], out_dir: Path, now: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    schema_map = {
        "sources": "federation_source.schema.json",
        "entities": "federation_entity.schema.json",
        "relationships": "federation_relationship.schema.json",
        "alerts": "federation_alert.schema.json",
    }
    for stream, rows in streams.items():
        if not rows:
            continue
        path = out_dir / f"{stream}.jsonl"
        _write_jsonl(path, rows)
        files.append({
            "filename": path.name,
            "stream": stream,
            "record_count": len(rows),
            "sha256": _sha256(path),
            "schema_id": schema_map[stream],
        })
    manifest = {
        "package_id": _fid("pkg", *[f["sha256"] for f in files]),
        "producer": PRODUCER,
        "export_contract_version": CONTRACT_VERSION,
        "mode": "research_only",
        "created_at": now,
        "extracted_at": now,
        "federation": {"producer_repo": PRODUCER, "hub_parent": "thehub-pr"},
        "files": files,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def main() -> int:
    now = _now()
    streams = build_streams(
        _load_jsonl(DATA_DIR / "verified_observations.jsonl"),
        _load_jsonl(DATA_DIR / "observation_sources.jsonl"),
        now,
    )
    manifest = write_package(streams, OUT_DIR, now)
    print(f"wrote mycelial federation package: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
