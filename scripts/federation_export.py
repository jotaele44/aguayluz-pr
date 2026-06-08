#!/usr/bin/env python3
"""Project AguaYLuz utility assets + service events into PRII canonical streams.

Maps the AguaYLuz infrastructure model onto the Hub's canonical contract:
  * each utility asset      -> one `entities` row (entity_type=utility_asset)
  * each operator           -> one `entities` row (entity_type=utility_operator)
  * each municipality        -> one `entities` row (entity_type=municipality)
  * each distinct source     -> one `sources` row
  * each service event       -> one `entities` row (entity_type=service_event)
  * asset -[operated_by]-> operator
  * asset -[located_in]-> municipality
  * asset -[affected_by]-> service_event (per linked_asset_ids)

Reads `--assets` / `--events` JSONL and writes
`exports/federation/{sources,entities,relationships}.jsonl` + a Hub-conformant
`manifest.json`. Deterministic `src_/ent_/rel_` ids (sha256). Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCER = "aguayluz-pr"
CONTRACT_VERSION = "1.0.0"
PRODUCER_SCRIPT = "scripts/federation_export.py"
STREAM_SCHEMA = {
    "sources": "federation_source.schema.json",
    "entities": "federation_entity.schema.json",
    "relationships": "federation_relationship.schema.json",
}


def _fid(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()[:32]}"


def _norm(name: str) -> str:
    return " ".join(str(name).strip().upper().split())


def _geo_key(name: str) -> str:
    """unaccent + upper -> match canonical municipios regardless of diacritics."""
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def _load_geo(path: Path) -> dict[str, dict]:
    """Index data/geo/pr_municipios.json centroids by their unaccent/upper key."""
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {_geo_key(m["name"]): m for m in doc.get("municipios", [])}


def _conf(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.5
    return round(c / 100.0, 4) if c > 1 else c


def _lineage(phase: str, inputs: list[str]) -> dict[str, Any]:
    return {
        "producer_script": PRODUCER_SCRIPT,
        "producer_phase": phase,
        "source_inputs": inputs,
        "extraction_method": "deterministic_asset_projection",
    }


def build_streams(assets: list[dict[str, Any]], events: list[dict[str, Any]], now: str, geo: dict[str, dict] | None = None) -> dict[str, list[dict[str, Any]]]:
    inputs = ["data/utility_assets.jsonl", "data/service_events.jsonl", "data/aee_incidents.jsonl"]
    geo = geo or {}
    sources: dict[str, dict[str, Any]] = {}
    entities: dict[str, dict[str, Any]] = {}
    relationships: dict[str, dict[str, Any]] = {}

    def source_for(ref: str, ref_hash: Any, conf: float) -> str:
        key = ref_hash or ref
        sid = _fid("src", key)
        if sid not in sources:
            sources[sid] = {
                "source_id": sid,
                "source_type": "public_record",
                "source_name": ref or "unknown",
                "source_ref": str(key),
                "confidence": conf,
                "lineage": _lineage("SOURCE_REGISTRY", inputs),
                "synthetic": False,
                "created_at": now,
                "extracted_at": now,
            }
        return sid

    for a in assets:
        conf = _conf(a.get("confidence"))
        sid = source_for(a.get("source_ref", ""), a.get("source_hash"), conf)
        aid = _fid("ent", "asset", a.get("asset_id"))
        entities[aid] = {
            "entity_id": aid, "source_id": sid,
            "name": a.get("asset_name") or a.get("asset_id"),
            "normalized_name": _norm(a.get("asset_name") or a.get("asset_id")),
            "entity_type": "utility_asset", "jurisdiction": "PR",
            "external_ids": {k: str(a[k]) for k in ("comid", "reachcode", "vpuid") if a.get(k)} or {},
            "confidence": conf, "lineage": _lineage("ASSET_ENTITY", inputs),
            "synthetic": False, "created_at": now, "extracted_at": now,
        }
        if not entities[aid]["external_ids"]:
            del entities[aid]["external_ids"]

        # Z2: carry real WGS84 coords onto the canonical entity for cross-producer
        # spatial joins (spiderweb correlate_spatial, PRIIS scoring).
        lat, lon = a.get("lat"), a.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            loc: dict[str, Any] = {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}
            if a.get("municipality"):
                loc["municipality"] = a["municipality"]
            entities[aid]["location"] = loc

        if a.get("operator"):
            op_id = _fid("ent", "operator", _norm(a["operator"]))
            entities.setdefault(op_id, _entity(op_id, sid, a["operator"], "utility_operator", 0.9, inputs, now))
            relationships.update(_rel_kv(aid, "operated_by", op_id, sid, conf, now))
        if a.get("municipality"):
            m_id = _fid("ent", "municipality", _norm(a["municipality"]))
            entities.setdefault(m_id, _entity(m_id, sid, a["municipality"], "municipality", 0.95, inputs, now))
            relationships.update(_rel_kv(aid, "located_in", m_id, sid, conf, now))

    for e in events:
        conf = _conf(e.get("confidence"))
        sid = source_for(e.get("source_ref", ""), e.get("source_hash"), conf)
        ev_id = _fid("ent", "event", e.get("event_id"))
        label = f"{e.get('event_type', 'event')} @ {e.get('affected_area', '')}".strip()
        entities[ev_id] = _entity(ev_id, sid, label, "service_event", conf, inputs, now)

        # Per-municipality outage attribution: link the event to its municipio node
        # (merges with asset-derived municipality entities via _norm) and carry the
        # municipio centroid onto the event for spatial joins.
        muni = e.get("municipality")
        if muni:
            m_id = _fid("ent", "municipality", _norm(muni))
            entities.setdefault(m_id, _entity(m_id, sid, muni, "municipality", 0.95, inputs, now))
            ev_src = ["data/aee_incidents.jsonl"] if e.get("evidence_tier") == "T2" else ["data/service_events.jsonl"]
            relationships.update(_rel_kv(ev_id, "located_in", m_id, sid, conf, now, source_inputs=ev_src))
            centroid = geo.get(_geo_key(muni))
            if centroid:
                entities[ev_id]["location"] = {
                    "lat": round(float(centroid["lat"]), 6),
                    "lon": round(float(centroid["lon"]), 6),
                    "municipality": muni,
                }

        for asset_ref in e.get("linked_asset_ids", []):
            aid = _fid("ent", "asset", asset_ref)
            relationships.update(_rel_kv(aid, "affected_by", ev_id, sid, conf, now))

    return {"sources": list(sources.values()),
            "entities": list(entities.values()),
            "relationships": list(relationships.values())}


def _entity(eid, sid, name, etype, conf, inputs, now):
    return {
        "entity_id": eid, "source_id": sid, "name": name,
        "normalized_name": _norm(name), "entity_type": etype, "jurisdiction": "PR",
        "confidence": conf, "lineage": _lineage(f"{etype.upper()}_ENTITY", inputs),
        "synthetic": False, "created_at": now, "extracted_at": now,
    }


def _rel_kv(src_ent, rtype, tgt_ent, sid, conf, now, source_inputs=None):
    rid = _fid("rel", src_ent, rtype, tgt_ent)
    return {rid: {
        "relationship_id": rid, "source_id": sid,
        "source_entity_id": src_ent, "target_entity_id": tgt_ent,
        "relationship_type": rtype, "evidence_source_id": sid, "confidence": conf,
        "lineage": _lineage("RELATIONSHIP", source_inputs or ["data/service_events.jsonl"]),
        "synthetic": False, "created_at": now, "extracted_at": now,
    }}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_package(streams, out_dir: Path, mode: str, now: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for stream in ("sources", "entities", "relationships"):
        rows = streams[stream]
        if not rows:
            continue
        fpath = out_dir / f"{stream}.jsonl"
        fpath.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        files.append({"filename": f"{stream}.jsonl", "stream": stream, "record_count": len(rows),
                      "sha256": _sha256(fpath), "schema_id": STREAM_SCHEMA[stream]})
    digest = hashlib.sha256(
        ("|".join(f"{f['filename']}:{f['sha256']}" for f in files) + f"|{mode}").encode()
    ).hexdigest()[:32]
    manifest = {"package_id": f"pkg_{digest}", "producer": PRODUCER,
                "export_contract_version": CONTRACT_VERSION, "mode": mode,
                "created_at": now, "extracted_at": now,
                "federation": {"producer_repo": PRODUCER, "hub_parent": "thehub-pr"},
                "files": files}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return out_dir / "manifest.json"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Export AguaYLuz assets/events as PRII canonical streams.")
    ap.add_argument("--assets", default=str(REPO_ROOT / "data/utility_assets.jsonl"))
    ap.add_argument("--events", default=str(REPO_ROOT / "data/service_events.jsonl"))
    ap.add_argument("--incidents", default=str(REPO_ROOT / "data/aee_incidents.jsonl"),
                    help="per-municipality outage events (AEE/LUMA model); merged into events")
    ap.add_argument("--geo", default=str(REPO_ROOT / "data/geo/pr_municipios.json"))
    ap.add_argument("--out", default=str(REPO_ROOT / "exports/federation"))
    ap.add_argument("--mode", default="test", choices=["test", "production"])
    args = ap.parse_args()

    assets = _load_jsonl(Path(args.assets))
    events = _load_jsonl(Path(args.events)) + _load_jsonl(Path(args.incidents))
    geo = _load_geo(Path(args.geo))
    if not assets and not events:
        print("no input data (data/utility_assets.jsonl / service_events / aee_incidents absent) — nothing to export")
        return 0
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    streams = build_streams(assets, events, now, geo)
    manifest_path = write_package(streams, Path(args.out), args.mode, now)
    counts = {k: len(v) for k, v in streams.items()}
    print(f"wrote {manifest_path} — {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
