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
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prii_export_utils import fid as _fid
from prii_export_utils import norm as _norm
from prii_export_utils import sha256 as _sha256

# Allow `python scripts/federation_export.py` from a fresh clone without an
# editable install. The outputs/* generator imports aguayluz.{models,validation}
# lazily; without this bootstrap those imports raise ModuleNotFoundError mid-run
# (after the streams have already been written). Mirrors the pattern in
# scripts/validate_repo.py.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCER = "aguayluz-pr"
CONTRACT_VERSION = "1.0.0"
PRODUCER_SCRIPT = "scripts/federation_export.py"
VECTOR = "AGUAYLUZ_WATER_POWER_INFRASTRUCTURE_INTELLIGENCE"
STREAM_SCHEMA = {
    "sources": "federation_source.schema.json",
    "entities": "federation_entity.schema.json",
    "relationships": "federation_relationship.schema.json",
    "alerts": "federation_alert.schema.json",
}
ALERT_INPUTS = ["data/alert_events.jsonl"]

# outputs/* deliverable: the operator-facing snapshot half of the canonical
# contract. Each filename maps to a schema in schemas/. Validated against its
# schema before write so the gate set (G01-G06) sees only compliant records.
OUTPUT_FILES = (
    "utility_assets.json",      # array of utility_asset records
    "service_events.json",      # array of service_event records (PREPS + AEE merged)
    "monitoring_readings.json", # array of monitoring_reading records (USGS time-series)
    "source_manifest.json",     # SourceManifest envelope
    "review_queue.json",        # ReviewQueue envelope
    "bridge_summary.json",      # AguayluzBridgeSummary envelope
    "base44_export.json",       # Base44 envelope (Hub-conformant)
    "integration_report.json",  # IntegrationReport (coverage + gates ledger); WRITTEN LAST
)
GATE_IDS = (
    "G01_SCHEMA", "G02_SOURCE_MANIFEST", "G03_CONFIDENCE", "G04_REVIEW_QUEUE",
    "G05_COVERAGE_LEDGER", "G06_BASE44_EXPORT", "G07_NO_SECRETS", "G08_TESTS",
)
WELL_KNOWN_GAPS = [
    "StreamCat NLCD attributes unavailable for VPU 21",
    "aee_incidents.jsonl is a 2025-03-03 point-in-time snapshot; LIVE per-municipio feed pending",
]
NEXT_ACTIONS_DEFAULT = [
    "AYL_INGEST_LIVE_OUTAGES",
    "AYL_REVIEWER_PASS_OSM_WATER",
]


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


def build_streams(assets: list[dict[str, Any]], events: list[dict[str, Any]], now: str, geo: dict[str, dict] | None = None, crosswalk: list[dict[str, Any]] | None = None, alerts: list[dict[str, Any]] | None = None, dep_edges: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    inputs = ["data/utility_assets.jsonl", "data/service_events.jsonl", "data/aee_incidents.jsonl"]
    geo = geo or {}
    crosswalk = crosswalk or []
    dep_edges = dep_edges or []
    sources: dict[str, dict[str, Any]] = {}
    entities: dict[str, dict[str, Any]] = {}
    relationships: dict[str, dict[str, Any]] = {}
    alert_rows: dict[str, dict[str, Any]] = {}

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

        # Rich, operator-facing asset fields for the Hub's water surface
        # (AguaYLuz page columns: municipality/status/operator/sensitivity). These
        # already live on the source rows; carry them through the canonical export
        # in an `attributes` block so the Hub renders them instead of blank cells.
        attrs = {
            "municipality": a.get("municipality"),
            "asset_subtype": a.get("asset_subtype"),
            "status": a.get("status"),
            "review_status": a.get("review_status"),
            "operator": a.get("operator"),
            "owner_agency": a.get("operator"),
            "evidence_tier": a.get("evidence_tier"),
            "attribute_coverage": a.get("attribute_coverage"),
            # coarse criticality signal for the Continuity Risks surface: power-drawing
            # water assets are the ones a grid outage takes offline.
            "sensitivity": "power_dependent"
            if any(k in (a.get("asset_subtype") or "").lower()
                   for k in ("pumping_station", "pump", "treatment", "wtp"))
            else None,
        }
        attrs = {k: v for k, v in attrs.items() if v not in (None, "", [])}
        if attrs:
            entities[aid]["attributes"] = attrs

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

    # Cross-source dedup: each non-canonical member -[duplicate_of]-> canonical.
    # Additive (all asset entities are kept); consumers collapse to the canonical
    # set by dropping nodes that have an outgoing duplicate_of edge. Source: the
    # data/asset_crosswalk.jsonl produced by scripts/dedup_power_assets.py.
    cw_inputs = ["data/asset_crosswalk.jsonl"]
    for cl in crosswalk:
        canon_ref = cl.get("canonical_asset_id")
        canon_ent = _fid("ent", "asset", canon_ref)
        if canon_ent not in entities:
            continue
        for member_ref in cl.get("member_asset_ids", []):
            if member_ref == canon_ref:
                continue
            mem_ent = _fid("ent", "asset", member_ref)
            if mem_ent not in entities:
                continue
            sid = entities[mem_ent]["source_id"]
            relationships.update(_rel_kv(mem_ent, "duplicate_of", canon_ent, sid,
                                         entities[mem_ent].get("confidence", 0.5), now,
                                         source_inputs=cw_inputs))

    # Water<->power dependency crosswalk -> canonical `relationships`. Each
    # `energizes` edge (power_node -> hydro_asset) becomes a water-asset
    # -[energized_by]-> power-asset relationship, so the Hub can surface which
    # water assets a grid outage would take offline (Continuity Risks). Only edges
    # whose both endpoints are exported assets are emitted.
    de_inputs = ["data/alert_dependency_edges.jsonl"]
    for de in dep_edges:
        if de.get("dependency_type") != "energizes":
            continue
        water_ref, power_ref = de.get("to_node_id"), de.get("from_node_id")
        if not water_ref or not power_ref:
            continue
        w_ent = _fid("ent", "asset", water_ref)
        p_ent = _fid("ent", "asset", power_ref)
        if w_ent not in entities or p_ent not in entities:
            continue
        sid = entities[w_ent]["source_id"]
        conf = _conf(de.get("confidence"))
        relationships.update(
            _rel_kv(w_ent, "energized_by", p_ent, sid, conf, now, source_inputs=de_inputs)
        )

    # Operational alert events -> canonical `alerts` stream. Each alert registers
    # its source, scales confidence to 0-1, and (when matched) links to the
    # affected utility asset entity for cross-producer correlation in the Hub.
    for al in alerts or []:
        conf = _conf(al.get("confidence"))
        sid = source_for(al.get("source_ref", ""), al.get("source_hash"), conf)
        alert_id = _fid("alrt", al.get("alert_id"))
        attributes = {
            "aguayluz_alert_id": al.get("alert_id"),
            "asset_name": al.get("asset_name"),
            "municipalities": al.get("municipalities", []),
            "sectors_impacted": al.get("sectors_impacted", []),
            "coord_confidence": al.get("coord_confidence"),
            "review_status": al.get("review_status"),
            "evidence_tier": al.get("evidence_tier"),
            "covert_flags": al.get("covert_flags", []),
        }
        attributes = {k: v for k, v in attributes.items() if v not in (None, [], "")}
        row: dict[str, Any] = {
            "alert_id": alert_id,
            "source_id": sid,
            "module": al.get("module_id"),
            "alert_type": al.get("event_type"),
            "severity": al.get("severity"),
            "status": al.get("status"),
            "gap_status": al.get("gap_status"),
            "start_at": al.get("start_at"),
            "observed_at": al.get("published_at") or al.get("start_at"),
            "attributes": attributes,
            "confidence": conf,
            "lineage": _lineage("ALERT_EVENT", ALERT_INPUTS),
            "synthetic": str(al.get("source_ref", "")).startswith("seed://"),
            "created_at": now,
            "extracted_at": now,
        }
        if al.get("end_at"):
            row["end_at"] = al["end_at"]
        if al.get("asset_id"):
            row["entity_id"] = _fid("ent", "asset", al["asset_id"])
        lat, lon = al.get("latitude"), al.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            loc = {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}
            munis = al.get("municipalities") or []
            if munis and munis[0] != "(unscoped)":
                loc["municipality"] = munis[0]
            row["location"] = loc
        alert_rows[alert_id] = row

    return {"sources": list(sources.values()),
            "entities": list(entities.values()),
            "relationships": list(relationships.values()),
            "alerts": list(alert_rows.values())}


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


def write_package(streams, out_dir: Path, mode: str, now: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for stream in ("sources", "entities", "relationships", "alerts"):
        rows = streams.get(stream, [])
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


# ---------------------------------------------------------------------------
# outputs/* deliverable generator (operator-facing snapshot)
# ---------------------------------------------------------------------------

def _run_id(now: str) -> str:
    """Build a run_id matching ^[0-9]{8}T[0-9]{6}Z_[A-Za-z0-9_-]+$."""
    stamp = now.replace("-", "").replace(":", "")  # 2026-06-08T13:45:24Z -> 20260608T134524Z
    return f"{stamp}_export"


def _summary_id(now: str) -> str:
    """Build a summary_id matching ^AYL_SUM_[0-9]{8}_[A-Za-z0-9_-]+$."""
    return f"AYL_SUM_{now[:10].replace('-', '')}_export"


def _compute_aggregates(assets: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts + averages for the base44/bridge_summary envelopes."""
    all_records = list(assets) + list(events)
    review = sum(1 for r in all_records if r.get("review_status") == "needs_review")
    blocked = sum(1 for r in all_records if r.get("review_status") == "blocked")
    confidences = [r["confidence"] for r in all_records if isinstance(r.get("confidence"), (int, float))]
    conf_avg = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
    munis = sorted({
        r.get("municipality") for r in all_records
        if r.get("municipality") and r.get("municipality") != "unknown"
    })
    located = sum(1 for r in all_records if isinstance(r.get("lat"), (int, float)))
    return {
        "records_total": len(all_records),
        "records_review": review,
        "records_blocked": blocked,
        "confidence_avg": conf_avg,
        "municipalities_covered": munis,
        "located": located,
    }


def _validate_and_write(path: Path, schema_name: str, data: Any) -> None:
    """Validate against the named schema (raise on mismatch) then write JSON."""
    # Local import so the script doesn't require the package on a fresh clone for
    # the streams-only path; needed only when the outputs/ generator runs.
    from aguayluz.models import validate_against_schema
    validate_against_schema(schema_name, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _validate_record_list(records: list[dict[str, Any]], schema_name: str) -> None:
    """Per-record schema validation (mirrors gate G01_SCHEMA's list-iteration path)."""
    from aguayluz.models import validate_against_schema
    for i, rec in enumerate(records):
        try:
            validate_against_schema(schema_name, rec)
        except Exception as exc:
            raise ValueError(f"{schema_name}[{i}] failed schema validation: {exc}") from exc


def _derive_aggregate_status(gate_results: list[Any]) -> str:
    """Roll an iterable of GateResult into a base44 envelope status.

    Precedence: any FAIL → FAIL; else any WARN → WARN; else PASS.
    SKIP is treated as benign (the gate had nothing to check). This mirrors
    the way `validate_repo.py` decides whether to exit 0 or 1.
    """
    statuses = [getattr(r, "status", r) for r in gate_results]
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(s == "WARN" for s in statuses):
        return "WARN"
    return "PASS"


def _coverage_pct(located: int, total: int) -> float:
    """Real coverage ratio. 0% when no records to cover (vs. dividing by zero)."""
    if total <= 0:
        return 0.0
    return round((located / total) * 100, 2)


def build_outputs(
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    aggregates: dict[str, Any],
    now: str,
    outputs_dir: Path,
    readings: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Materialize all 8 files under outputs/. integration_report.json is last
    (references the others). Returns per-file record counts for logging.

    `readings` (monitoring_reading rows, e.g. USGS daily reservoir levels) are a
    parallel time-series deliverable — validated and written to
    monitoring_readings.json, but intentionally NOT folded into the asset/event
    coverage aggregates (they have no lat/lon of their own; they reference an
    asset_id) nor projected as entity-graph nodes (anti-bloat: 1 reservoir × daily
    history would dwarf the entity set)."""
    readings = readings or []
    outputs_dir.mkdir(parents=True, exist_ok=True)
    run_id = _run_id(now)
    summary_id = _summary_id(now)
    today = now[:10]

    # 1+2. Per-record arrays — validated individually for the same per-record
    # iteration the G01 gate does, then written as a JSON array.
    _validate_record_list(assets, "utility_asset")
    (outputs_dir / "utility_assets.json").write_text(json.dumps(assets, indent=2, sort_keys=True))
    _validate_record_list(events, "service_event")
    (outputs_dir / "service_events.json").write_text(json.dumps(events, indent=2, sort_keys=True))

    # 2b. monitoring_readings — time-series observations (always written, even if
    # empty, so the deliverable file-set is deterministic).
    _validate_record_list(readings, "monitoring_reading")
    (outputs_dir / "monitoring_readings.json").write_text(json.dumps(readings, indent=2, sort_keys=True))

    # 3. source_manifest — one entry per unique source_ref across both record lists.
    seen: dict[str, dict[str, Any]] = {}
    for r in assets + events:
        ref = r.get("source_ref")
        if not ref or ref in seen:
            continue
        seen[ref] = {
            "source_ref": ref,
            "source_hash": r.get("source_hash"),
            "tier": r.get("evidence_tier", "T3"),
            "access_date": today,
            "citation": None,
            "notes": None,
        }
    manifest = {
        "module_id": "aguayluz-pr",
        "generated_at": now,
        "entries": sorted(seen.values(), key=lambda e: e["source_ref"]),
    }
    _validate_and_write(outputs_dir / "source_manifest.json", "source_manifest", manifest)

    # 4. review_queue — one item per record where review_status ∈ {needs_review, blocked}.
    items: list[dict[str, Any]] = []
    for r in assets + events:
        status = r.get("review_status")
        if status not in ("needs_review", "blocked"):
            continue
        ref = r.get("asset_id") or r.get("event_id") or "unknown"
        item: dict[str, Any] = {
            "record_ref": ref,
            "reason": f"upstream review_status={status} (evidence_tier={r.get('evidence_tier', '?')})",
            "severity": "warn" if status == "needs_review" else "block",
        }
        if r.get("evidence_tier"):
            item["evidence_tier"] = r["evidence_tier"]
        if isinstance(r.get("confidence"), int):
            item["confidence"] = r["confidence"]
        items.append(item)
    review_queue = {"module_id": "aguayluz-pr", "generated_at": now, "items": items}
    _validate_and_write(outputs_dir / "review_queue.json", "review_queue", review_queue)

    # 5. bridge_summary — module-level aggregates for the Hub.
    coverage_pct = _coverage_pct(aggregates["located"], aggregates["records_total"])
    bridge = {
        "module_id": "aguayluz-pr",
        "summary_id": summary_id,
        "assets_total": len(assets),
        "events_total": len(events),
        "municipalities_covered": aggregates["municipalities_covered"],
        "service_risk_summary": (
            f"{aggregates['records_review']} of {aggregates['records_total']} records carry "
            f"review_status=needs_review; {aggregates['records_blocked']} blocked; "
            f"coverage_pct={coverage_pct}; mean evidence confidence "
            f"{aggregates['confidence_avg']}/100 across {len(aggregates['municipalities_covered'])} "
            "municipalities."
        ),
        "infrastructure_dependencies": [
            "NHDPlus V2.1 (VPU 21)",
            "EPA WATERS REST API",
            "USGS NWIS Site Service",
            "HIFLD electric substations",
            "PR_Geodata OSM extracts (water/wastewater)",
            "LUMA outages_by_town (SuperSonicHub1 mirror)",
        ],
        "linked_modules": ["thehub-pr"],
        "confidence": round(aggregates["confidence_avg"]),
        "review_status": "needs_review" if aggregates["records_review"] > 0 else "accepted",
    }
    _validate_and_write(outputs_dir / "bridge_summary.json", "aguayluz_bridge_summary", bridge)

    # 6 + 7. The health-signal pair (base44_export + integration_report) must
    # report REAL gate state, not constants. Otherwise the deliverable's
    # headline is a green light wired to "on": a future failure (a leaked
    # secret → G07 FAIL; a blocked record arriving) would still emit
    # status=PASS, defeating the point of the gate system.
    #
    # Bootstrap dance:
    #   - delete any stale base44_export.json and integration_report.json so
    #     gates G05/G06 honestly report SKIP on this pass (rather than
    #     re-validating last run's file)
    #   - run validate_repo gates against the 5 files we just wrote
    #   - derive the aggregate status (any FAIL → FAIL; any WARN → WARN;
    #     else PASS); record each gate's real result in the ledger
    #   - write base44_export and integration_report with those measured
    #     values. Subsequent validate_repo runs will inspect these files
    #     for G05/G06 and PASS/FAIL them on their own merits.
    for stale in ("integration_report.json", "base44_export.json"):
        (outputs_dir / stale).unlink(missing_ok=True)

    from aguayluz.validation import run_gates  # local import; same reason as _validate_and_write
    report = run_gates()
    gate_ledger = [
        {"id": r.gate_id, "status": r.status, "details": r.details or None}
        for r in report.results
    ]
    aggregate_status = _derive_aggregate_status(report.results)

    n_power = sum(1 for a in assets if a.get("asset_type") == "power")
    n_water = sum(1 for a in assets if a.get("asset_type") in ("water", "wastewater"))
    base44 = {
        "module_id": "aguayluz-pr",
        "run_id": run_id,
        "vector": VECTOR,
        "status": aggregate_status,
        "coverage_pct": coverage_pct,
        "records_total": aggregates["records_total"],
        "records_review": aggregates["records_review"],
        "records_blocked": aggregates["records_blocked"],
        "confidence_avg": aggregates["confidence_avg"],
        "source_manifest_path": "outputs/source_manifest.json",
        "integration_report_path": "outputs/integration_report.json",
        "sanitized_summary": (
            f"{aggregates['records_total']} canonical records ({n_power} power, {n_water} water/wastewater, "
            f"{len(assets) - n_power - n_water} other assets, {len(events)} service events) across "
            f"{len(aggregates['municipalities_covered'])} municipalities. "
            f"{aggregates['records_review']} await reviewer adjudication; mean confidence "
            f"{aggregates['confidence_avg']}/100. "
            f"coverage_pct = geolocation rate "
            f"({aggregates['located']}/{aggregates['records_total']} records carry lat/lon); "
            "ingestion completeness is implicit 100% (no target population enumerated upstream)."
        ),
        "top_findings": [],
        "contradictions": [],
        "gaps": list(WELL_KNOWN_GAPS),
        "next_actions": list(NEXT_ACTIONS_DEFAULT),
    }
    _validate_and_write(outputs_dir / "base44_export.json", "base44_export", base44)

    # Coverage ledger: `unresolved` and `gaps` must reflect REAL state, not
    # constants. Without coords means the record can't participate in spatial
    # joins downstream (PRIIS scoring, spiderweb correlate_spatial), so each
    # such record is a measurable coverage gap.
    unresolved = aggregates["records_total"] - aggregates["located"]
    coverage_gaps: list[str] = []
    if unresolved > 0:
        coverage_gaps.append(
            f"{unresolved} record(s) lack lat/lon and cannot anchor spatial joins "
            "(typically: PREPS island-wide events + AEE incidents whose geo "
            "centroid is injected at stream-build time, not input ingest)"
        )
    integration = {
        "module_id": "aguayluz-pr",
        "run_id": run_id,
        "vector": VECTOR,
        "generated_at": now,
        "coverage": {
            "expected": aggregates["records_total"],
            "located": aggregates["located"],
            "ingested": aggregates["records_total"],
            "deduped": 0,
            "unresolved": unresolved,
            "gaps": coverage_gaps,
            "coverage_pct": coverage_pct,
        },
        "gates": gate_ledger,
    }
    _validate_and_write(outputs_dir / "integration_report.json", "integration_report", integration)

    return {
        "utility_assets": len(assets),
        "service_events": len(events),
        "monitoring_readings": len(readings),
        "source_manifest_entries": len(manifest["entries"]),
        "review_queue_items": len(items),
        "bridge_summary": 1,
        "base44_export": 1,
        "integration_report": 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export AguaYLuz assets/events as PRII canonical streams.")
    ap.add_argument("--assets", default=str(REPO_ROOT / "data/utility_assets.jsonl"))
    ap.add_argument("--events", default=str(REPO_ROOT / "data/service_events.jsonl"))
    ap.add_argument("--incidents", default=str(REPO_ROOT / "data/aee_incidents.jsonl"),
                    help="per-municipality outage events (AEE/LUMA model); merged into events")
    ap.add_argument("--readings", nargs="*", default=None,
                    help="monitoring_reading time-series files. Default: data/reservoir_levels.jsonl "
                         "+ every data/*_readings.jsonl (reliability, generation, …) — new sources "
                         "flow in automatically. Concatenated into outputs/monitoring_readings.json")
    ap.add_argument("--alerts", default=str(REPO_ROOT / "data/alert_events.jsonl"),
                    help="operational alert events; projected into the canonical alerts stream")
    ap.add_argument("--geo", default=str(REPO_ROOT / "data/geo/pr_municipios.json"))
    ap.add_argument("--crosswalk", default=str(REPO_ROOT / "data/asset_crosswalk.jsonl"),
                    help="cross-source dedup clusters; emits member -[duplicate_of]-> canonical edges")
    ap.add_argument("--dep-edges", default=str(REPO_ROOT / "data/alert_dependency_edges.jsonl"),
                    help="alert dependency edges; `energizes` edges emit water -[energized_by]-> power relationships")
    ap.add_argument("--out", default=str(REPO_ROOT / "exports/federation"))
    ap.add_argument("--outputs", default=str(REPO_ROOT / "outputs"),
                    help="operator-facing snapshot directory (7-file deliverable). Pass empty string to skip.")
    ap.add_argument("--no-outputs", action="store_true",
                    help="skip the outputs/* deliverable; emit canonical streams only")
    ap.add_argument("--mode", default="test", choices=["test", "production"])
    args = ap.parse_args()

    raw_events = _load_jsonl(Path(args.events))
    raw_incidents = _load_jsonl(Path(args.incidents))
    assets = _load_jsonl(Path(args.assets))
    alerts = _load_jsonl(Path(args.alerts))
    events = raw_events + raw_incidents
    geo = _load_geo(Path(args.geo))
    crosswalk = _load_jsonl(Path(args.crosswalk))
    dep_edges = _load_jsonl(Path(args.dep_edges))
    if not assets and not events and not alerts:
        print("no input data (data/utility_assets.jsonl / service_events / aee_incidents / alert_events absent) — nothing to export")
        return 0
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    streams = build_streams(assets, events, now, geo, crosswalk, alerts, dep_edges)
    manifest_path = write_package(streams, Path(args.out), args.mode, now)
    counts = {k: len(v) for k, v in streams.items()}
    print(f"wrote {manifest_path} — {counts}")

    if not args.no_outputs and args.outputs:
        reading_paths = args.readings if args.readings is not None else (
            [str(REPO_ROOT / "data/reservoir_levels.jsonl")]
            + sorted(str(p) for p in (REPO_ROOT / "data").glob("*_readings.jsonl"))
        )
        readings = [r for p in reading_paths for r in _load_jsonl(Path(p))]
        aggregates = _compute_aggregates(assets, events)
        outputs_counts = build_outputs(assets, events, aggregates, now, Path(args.outputs), readings)
        print(f"wrote outputs/* — {outputs_counts}")
        # outputs/alert_events.json: operator-facing alert snapshot, validated
        # per-record against the alert_event schema so gate G01 covers it.
        if alerts:
            _validate_record_list(alerts, "alert_event")
            (Path(args.outputs) / "alert_events.json").write_text(
                json.dumps(alerts, indent=2, sort_keys=True)
            )
            print(f"wrote outputs/alert_events.json — {len(alerts)} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
