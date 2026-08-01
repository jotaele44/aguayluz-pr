"""Canonical AguaYLuz ASGI application with metric-safe monitoring contracts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.backend import main as legacy
from server.backend.monitoring_alert_operations import federation_alert_export, lifecycle_alerts
from server.backend.monitoring_incident_ledger import (
    ALLOWED_EVENTS,
    append_event,
    escalation_candidates,
    federation_delta,
    materialized_state,
    notification_outbox,
    read_events,
    replay,
    timeline,
    verify_chain,
)
from server.backend.monitoring_quality import SERIES_METADATA_REGISTRY, series_quality
from server.backend.water_disruption_api import router as water_disruption_router


def _is_overridden_route(route: Any) -> bool:
    """Exclude legacy GET routes whose contracts are replaced by this canonical app."""
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", set())
    return "GET" in methods and path in {"/readings", "/assets"}


app = FastAPI(title=legacy.app.title)
app.router.routes.extend(route for route in legacy.app.router.routes if not _is_overridden_route(route))
app.exception_handlers.update(legacy.app.exception_handlers)
app.dependency_overrides.update(legacy.app.dependency_overrides)
for middleware in reversed(legacy.app.user_middleware):
    app.add_middleware(middleware.cls, *middleware.args, **middleware.kwargs)
app.include_router(water_disruption_router)

READING_VECTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "reservoir": {"path": legacy.DATA / "reservoir_levels.jsonl", "metrics": {"reservoir_elevation": {"units": {"ft"}}, "reservoir_storage_pct": {"units": {"%"}}, "streamflow": {"units": {"ft3/s", "ft³/s"}}, "gage_height": {"units": {"ft"}}}, "metric_required": True},
    "groundwater": {"path": legacy.DATA / "groundwater_levels.jsonl", "metrics": {"groundwater_level": {"units": {"ft"}}}, "metric_required": False},
    "coastal": {"path": legacy.DATA / "coastal_levels.jsonl", "metrics": {"coastal_water_level": {"units": {"ft"}}}, "metric_required": False},
}

ASSET_GRAPH_SCHEMA_VERSION = "aguayluz.water-asset-impact/v0.1"
ASSET_STATUS_ORDER = {"unknown": 0, "stale": 1, "derived": 2, "suspected": 3, "confirmed": 4}
SENSITIVE_SUBTYPE_TERMS = (
    "valve",
    "interconnection",
    "pressure_reducing",
    "scada",
    "control",
    "feeder",
)
CRITICAL_FACILITY_TERMS = (
    "hospital",
    "medical",
    "dialysis",
    "school",
    "shelter",
    "fire station",
    "police",
)
RELATIONSHIP_TYPES = {
    "upstream_of": "UPSTREAM_OF",
    "downstream_of": "DOWNSTREAM_OF",
    "supplies": "SUPPLIES",
    "energizes": "SUPPLIES",
    "depends_on": "DEPENDS_ON",
    "powered_by": "POWERED_BY",
    "backup_for": "BACKUP_FOR",
    "located_in": "LOCATED_IN",
    "serves": "SERVES",
    "monitored_by": "MONITORED_BY",
}
PROPAGATION_RELATIONSHIPS = {"UPSTREAM_OF", "SUPPLIES", "BACKUP_FOR"}


class IncidentTransition(BaseModel):
    event_type: str
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class BootstrapRequest(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _norm(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def _counter(rows: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(rows).items(), key=lambda item: (-item[1], item[0])))


def _source_label(asset: dict[str, Any]) -> str:
    operator = str(asset.get("operator") or "").strip()
    if operator:
        return operator
    ref = str(asset.get("source_ref") or "").strip()
    if not ref:
        return "unresolved"
    prefix = re.split(r"[:/\s]", ref, maxsplit=1)[0].strip()
    return prefix or "unresolved"


def _provenance_class(asset: dict[str, Any]) -> str:
    subtype = str(asset.get("asset_subtype") or "").lower()
    if any(term in subtype for term in SENSITIVE_SUBTYPE_TERMS):
        return "operator_restricted"
    review = str(asset.get("review_status") or "")
    tier = str(asset.get("evidence_tier") or "")
    confidence = int(asset.get("confidence") or 0)
    if review in {"rejected", "blocked"} or not asset.get("source_ref"):
        return "unresolved"
    if str(asset.get("asset_id") or "").startswith("LOCAL_"):
        return "public_secondary"
    if tier == "T1" and review == "accepted" and confidence >= 70:
        return "public_authoritative"
    if tier in {"T1", "T2"} and confidence >= 50:
        return "public_secondary"
    if confidence > 0:
        return "inferred"
    return "unresolved"


def _identifier_quality(asset: dict[str, Any]) -> str:
    asset_id = str(asset.get("asset_id") or "")
    if not asset_id:
        return "weak"
    if asset_id.startswith("LOCAL_"):
        return "local_deterministic"
    if asset.get("source_ref"):
        return "source_bound"
    return "weak"


def _position_uncertainty(asset: dict[str, Any]) -> str:
    if not isinstance(asset.get("lat"), (int, float)) or not isinstance(asset.get("lon"), (int, float)):
        return "unknown"
    if _provenance_class(asset) == "public_authoritative" and int(asset.get("confidence") or 0) >= 80:
        return "exact"
    return "approximate"


def _asset_rank(asset: dict[str, Any]) -> tuple[int, int, int, int, int]:
    review_rank = {"accepted": 4, "needs_review": 3, "blocked": 2, "rejected": 1}
    tier_rank = {"T1": 4, "T2": 3, "T3": 2, "T4": 1}
    geocoded = int(isinstance(asset.get("lat"), (int, float)) and isinstance(asset.get("lon"), (int, float)))
    return (
        review_rank.get(str(asset.get("review_status") or ""), 0),
        tier_rank.get(str(asset.get("evidence_tier") or ""), 0),
        int(asset.get("confidence") or 0),
        geocoded,
        int(bool(asset.get("source_ref"))),
    )


def _crosswalk_aliases() -> tuple[dict[str, str], dict[str, list[str]]]:
    aliases: dict[str, str] = {}
    members_by_canonical: dict[str, list[str]] = {}
    for cluster in legacy._load_jsonl(legacy.DATA / "asset_crosswalk.jsonl"):
        canonical_id = str(cluster.get("canonical_asset_id") or "").strip()
        members = sorted({str(value) for value in cluster.get("member_asset_ids", []) if value})
        if not canonical_id or not members:
            continue
        members_by_canonical[canonical_id] = members
        for member in members:
            aliases[member] = canonical_id
    return aliases, members_by_canonical


def _canonical_assets() -> tuple[list[dict[str, Any]], dict[str, str]]:
    aliases, members_by_canonical = _crosswalk_aliases()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position, source in enumerate(legacy._assets):
        row = dict(source)
        raw_id = str(row.get("asset_id") or "").strip()
        if not raw_id:
            raw_id = f"UNRESOLVED_{_digest({'position': position, 'row': row})[:16]}"
            row["asset_id"] = raw_id
        grouped[aliases.get(raw_id, raw_id)].append(row)

    nodes: list[dict[str, Any]] = []
    canonical_aliases: dict[str, str] = {}
    for canonical_id, rows in grouped.items():
        preferred = next((row for row in rows if row.get("asset_id") == canonical_id), None)
        chosen = dict(preferred or max(rows, key=_asset_rank))
        all_aliases = sorted(
            {str(row.get("asset_id")) for row in rows if row.get("asset_id")}
            | set(members_by_canonical.get(canonical_id, []))
        )
        for alias in all_aliases:
            canonical_aliases[alias] = canonical_id
        chosen["asset_id"] = canonical_id
        chosen["canonical_asset_id"] = canonical_id
        chosen["alias_asset_ids"] = [alias for alias in all_aliases if alias != canonical_id]
        chosen["source_record_count"] = len(rows)
        chosen["duplicate_records_collapsed"] = max(0, len(rows) - 1)
        chosen["provenance_class"] = _provenance_class(chosen)
        chosen["identifier_quality"] = _identifier_quality(chosen)
        chosen["position_uncertainty"] = _position_uncertainty(chosen)
        chosen["restricted_detail"] = chosen["provenance_class"] == "operator_restricted"
        municipio = str(chosen.get("municipality") or "").strip()
        chosen["service_areas"] = [] if _norm(municipio) in {"", "PUERTO RICO", "(UNSCOPED)", "UNKNOWN"} else [municipio]
        searchable = f"{chosen.get('asset_name', '')} {chosen.get('asset_subtype', '')}".lower()
        chosen["critical_facility"] = any(term in searchable for term in CRITICAL_FACILITY_TERMS)
        nodes.append(chosen)
    return sorted(nodes, key=lambda item: str(item["asset_id"])), canonical_aliases


def _municipio_names() -> list[str]:
    result: set[str] = set()
    for feature in legacy._municipios_geojson.get("features", []):
        props = feature.get("properties", {})
        value = (
            props.get("name")
            or props.get("NAME")
            or props.get("NAME20")
            or props.get("NAMELSAD")
            or props.get("municipality")
        )
        if value:
            result.add(str(value))
    return sorted(result)


def _relationship_graph(nodes: list[dict[str, Any]], aliases: dict[str, str]) -> tuple[list[dict[str, Any]], int]:
    node_ids = {str(node["asset_id"]) for node in nodes}
    relationships: list[dict[str, Any]] = []
    skipped_unknown = 0

    for node in nodes:
        for municipio in node.get("service_areas", []):
            body = {
                "from_node_id": node["asset_id"],
                "to_node_id": f"municipio:{_norm(municipio)}",
                "relationship_type": "LOCATED_IN",
                "confidence": int(node.get("confidence") or 0),
                "evidence_class": "direct_attribute",
                "inferred": False,
                "propagation_allowed": False,
                "source_ref": node.get("source_ref"),
                "notes": "Derived directly from the canonical asset municipality attribute.",
            }
            body["relationship_id"] = f"AYLR_{_digest(body)[:20]}"
            relationships.append(body)

    for edge in legacy._alert_edges:
        dependency = str(edge.get("dependency_type") or "").lower().strip()
        relationship_type = RELATIONSHIP_TYPES.get(dependency)
        if relationship_type is None:
            skipped_unknown += 1
            continue
        raw_from = str(edge.get("from_node_id") or "").strip()
        raw_to = str(edge.get("to_node_id") or "").strip()
        if not raw_from or not raw_to:
            skipped_unknown += 1
            continue
        from_id = aliases.get(raw_from, raw_from)
        to_id = aliases.get(raw_to, raw_to)
        if from_id not in node_ids and to_id not in node_ids:
            continue
        confidence = int(edge.get("confidence") or 0)
        inferred = bool(edge.get("evidence_required")) or confidence < 80
        body = {
            "from_node_id": from_id,
            "to_node_id": to_id,
            "relationship_type": relationship_type,
            "confidence": confidence,
            "evidence_class": "inferred_proxy" if inferred else "corroborated",
            "inferred": inferred,
            "propagation_allowed": relationship_type in PROPAGATION_RELATIONSHIPS,
            "source_ref": edge.get("edge_id"),
            "notes": edge.get("notes"),
        }
        body["relationship_id"] = str(edge.get("edge_id") or f"AYLR_{_digest(body)[:20]}")
        relationships.append(body)

    unique = {item["relationship_id"]: item for item in relationships}
    return sorted(unique.values(), key=lambda item: item["relationship_id"]), skipped_unknown


def _evidence_time(row: dict[str, Any]) -> datetime | None:
    for key in ("start_at", "published_at", "end_at", "occurred_at", "last_event_at"):
        parsed = legacy._parse_dt(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _impact_evidence(
    nodes: list[dict[str, Any]],
    aliases: dict[str, str],
    relationships: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    node_ids = {str(node["asset_id"]) for node in nodes}
    evidence_by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    contradictory_by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)

    all_times = [_evidence_time(alert) for alert in legacy._alerts]
    all_times.extend(_evidence_time(event) for event in read_events())
    reference_time = max((value for value in all_times if value is not None), default=None)

    for alert in legacy._alerts:
        explicit_id = str(alert.get("asset_id") or "").strip()
        linked_ids = {str(value) for value in alert.get("linked_asset_ids", []) if value}
        candidate_ids = set(linked_ids)
        if explicit_id:
            candidate_ids.add(explicit_id)
        actionable = str(alert.get("status") or "").lower() not in legacy.INACTIVE_ALERT_STATUS
        for raw_id in candidate_ids:
            asset_id = aliases.get(raw_id, raw_id)
            if asset_id not in node_ids:
                continue
            explicit = bool(explicit_id and aliases.get(explicit_id, explicit_id) == asset_id)
            if explicit and alert.get("review_status") == "accepted" and alert.get("evidence_tier") == "T1":
                status = "confirmed"
                confidence = int(alert.get("confidence") or 0)
            elif explicit:
                status = "suspected"
                confidence = max(0, int(alert.get("confidence") or 0) - 10)
            elif alert.get("module_id") in {"HYDRO_OPS", "CONTAMINATION"}:
                status = "suspected"
                confidence = max(0, int(alert.get("confidence") or 0) - 20)
            else:
                status = "derived"
                confidence = max(0, int(alert.get("confidence") or 0) - 30)
            occurred = _evidence_time(alert)
            stale = bool(
                actionable
                and occurred is not None
                and reference_time is not None
                and (reference_time - occurred).total_seconds() > 7 * 86400
            )
            item = {
                "evidence_id": alert.get("alert_id"),
                "evidence_kind": "operational_alert",
                "status": "stale" if stale else status,
                "cause": alert.get("source_title") or alert.get("event_type"),
                "module_id": alert.get("module_id"),
                "confidence": confidence,
                "evidence_tier": alert.get("evidence_tier"),
                "review_status": alert.get("review_status"),
                "occurred_at": occurred.isoformat() if occurred else None,
                "direct": explicit,
                "inference": not explicit,
                "source_ref": alert.get("source_ref"),
            }
            if actionable:
                evidence_by_asset[asset_id].append(item)
            else:
                contradictory_by_asset[asset_id].append({**item, "contradiction_reason": "inactive_or_rejected_evidence"})

    for event in read_events():
        payload = event.get("payload", {})
        evidence = payload.get("evidence") if isinstance(payload, dict) else None
        if not isinstance(evidence, dict):
            continue
        raw_ids: set[str] = set()
        for key in ("asset_id", "site_no"):
            if evidence.get(key):
                raw_ids.add(str(evidence[key]))
        raw_ids.update(str(value) for value in evidence.get("linked_asset_ids", []) if value)
        for raw_id in raw_ids:
            candidates = {
                aliases.get(raw_id, raw_id),
                aliases.get(f"USGS_{raw_id}", f"USGS_{raw_id}"),
                aliases.get(f"USGSGW_{raw_id}", f"USGSGW_{raw_id}"),
            }
            for asset_id in candidates & node_ids:
                resolved = event.get("event_type") == "resolved"
                item = {
                    "evidence_id": event.get("event_id"),
                    "incident_id": event.get("incident_id"),
                    "evidence_kind": "append_only_incident_event",
                    "status": "confirmed" if not resolved else "unknown",
                    "cause": event.get("reason"),
                    "confidence": 90,
                    "evidence_tier": "T1",
                    "review_status": "accepted",
                    "occurred_at": event.get("occurred_at"),
                    "direct": True,
                    "inference": False,
                    "source_ref": "monitoring_incident_ledger",
                }
                (contradictory_by_asset if resolved else evidence_by_asset)[asset_id].append(item)

    best: dict[str, dict[str, Any]] = {}
    timeline: list[dict[str, Any]] = []
    for node in nodes:
        asset_id = str(node["asset_id"])
        evidence = sorted(
            evidence_by_asset.get(asset_id, []),
            key=lambda item: (
                ASSET_STATUS_ORDER.get(str(item["status"]), 0),
                int(item.get("confidence") or 0),
                str(item.get("occurred_at") or ""),
            ),
            reverse=True,
        )
        chosen = evidence[0] if evidence else None
        status = str(chosen["status"]) if chosen else "unknown"
        best[asset_id] = {
            "asset_id": asset_id,
            "impact_status": status,
            "impact_confidence": int(chosen.get("confidence") or 0) if chosen else 0,
            "cause": chosen.get("cause") if chosen else None,
            "direct": bool(chosen and chosen.get("direct")),
            "hop_count": 0 if chosen else None,
            "evidence": evidence,
            "contradictions": contradictory_by_asset.get(asset_id, []),
            "freshness_basis": "relative_to_latest_corpus_evidence",
        }
        for item in evidence:
            timeline.append({"asset_id": asset_id, **item})

    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relationship in relationships:
        if relationship.get("propagation_allowed"):
            outgoing[str(relationship["from_node_id"])].append(relationship)

    queue = deque(
        (asset_id, 0, int(item["impact_confidence"]))
        for asset_id, item in best.items()
        if item["impact_status"] in {"confirmed", "suspected"} and item["impact_confidence"] > 0
    )
    visited: dict[str, int] = {asset_id: 0 for asset_id, _, _ in queue}
    derived_paths: list[dict[str, Any]] = []
    while queue:
        source_id, hops, confidence = queue.popleft()
        if hops >= 3:
            continue
        for relationship in outgoing.get(source_id, []):
            target_id = str(relationship["to_node_id"])
            if target_id not in best:
                continue
            next_hops = hops + 1
            next_confidence = max(
                0,
                min(confidence, int(relationship.get("confidence") or 0)) - 15,
            )
            if next_confidence <= 0 or visited.get(target_id, 99) <= next_hops:
                continue
            visited[target_id] = next_hops
            path = {
                "from_asset_id": source_id,
                "to_asset_id": target_id,
                "relationship_id": relationship["relationship_id"],
                "relationship_type": relationship["relationship_type"],
                "hop_count": next_hops,
                "confidence": next_confidence,
                "inference": True,
            }
            derived_paths.append(path)
            current = best[target_id]
            if ASSET_STATUS_ORDER[current["impact_status"]] < ASSET_STATUS_ORDER["derived"]:
                current.update(
                    {
                        "impact_status": "derived",
                        "impact_confidence": next_confidence,
                        "cause": f"Dependency exposure via {relationship['relationship_type']}",
                        "direct": False,
                        "hop_count": next_hops,
                    }
                )
            queue.append((target_id, next_hops, next_confidence))

    return best, sorted(timeline, key=lambda item: str(item.get("occurred_at") or ""), reverse=True), derived_paths


def _public_asset(node: dict[str, Any], mode: str) -> dict[str, Any]:
    item = dict(node)
    if mode == "public" and item.get("restricted_detail"):
        item["lat"] = None
        item["lon"] = None
        item["source_ref"] = "restricted"
        item["asset_name"] = f"{item.get('asset_subtype') or 'control asset'} — {item.get('municipality') or 'Puerto Rico'}"
        item["position_uncertainty"] = "withheld"
    return item


def _asset_switchboard(mode: str) -> dict[str, Any]:
    nodes, aliases = _canonical_assets()
    relationships, skipped_relationships = _relationship_graph(nodes, aliases)
    impacts, timeline, derived_paths = _impact_evidence(nodes, aliases, relationships)
    enriched = [{**_public_asset(node, mode), **impacts[str(node["asset_id"])]} for node in nodes]

    raw_ids = [str(row.get("asset_id") or "") for row in legacy._assets if row.get("asset_id")]
    municipalities = _municipio_names()
    represented_norm = {
        _norm(node.get("municipality"))
        for node in nodes
        if _norm(node.get("municipality")) not in {"", "PUERTO RICO", "(UNSCOPED)", "UNKNOWN"}
    }
    missing_municipalities = [name for name in municipalities if _norm(name) not in represented_norm]
    unresolved_municipality = sum(
        _norm(node.get("municipality")) in {"", "PUERTO RICO", "(UNSCOPED)", "UNKNOWN"}
        for node in nodes
    )
    by_source = _counter([_source_label(node) for node in nodes])
    inventory = {
        "source_record_total": len(legacy._assets),
        "canonical_asset_total": len(nodes),
        "records_collapsed": max(0, len(legacy._assets) - len(nodes)),
        "duplicate_source_id_count": sum(count - 1 for count in Counter(raw_ids).values() if count > 1),
        "duplicate_canonical_id_count": len(nodes) - len({node["asset_id"] for node in nodes}),
        "by_type": _counter([str(node.get("asset_type") or "unknown") for node in nodes]),
        "by_subtype": _counter([str(node.get("asset_subtype") or "unknown") for node in nodes]),
        "by_source": by_source,
        "geometry": {
            "mapped": sum(
                isinstance(node.get("lat"), (int, float)) and isinstance(node.get("lon"), (int, float))
                for node in nodes
            ),
            "unmapped": sum(
                not (isinstance(node.get("lat"), (int, float)) and isinstance(node.get("lon"), (int, float)))
                for node in nodes
            ),
            "by_geometry_type": _counter([str(node.get("geometry_type") or "unknown") for node in nodes]),
        },
        "municipality": {
            "resolved": len(nodes) - unresolved_municipality,
            "unresolved": unresolved_municipality,
        },
        "identifier_quality": _counter([str(node["identifier_quality"]) for node in nodes]),
        "provenance_class": _counter([str(node["provenance_class"]) for node in nodes]),
        "evidence_tier": _counter([str(node.get("evidence_tier") or "unknown") for node in nodes]),
    }
    impact_counts = _counter([str(node["impact_status"]) for node in enriched])
    contradictions = [
        {"asset_id": node["asset_id"], "items": node["contradictions"]}
        for node in enriched
        if node["contradictions"]
    ]
    gaps = []
    if inventory["geometry"]["unmapped"]:
        gaps.append({"gap": "missing_geometry", "count": inventory["geometry"]["unmapped"], "blocking": False})
    if unresolved_municipality:
        gaps.append({"gap": "unresolved_municipality", "count": unresolved_municipality, "blocking": False})
    if missing_municipalities:
        gaps.append({"gap": "municipio_coverage", "count": len(missing_municipalities), "blocking": False})
    if skipped_relationships:
        gaps.append({"gap": "unmapped_relationship_vocabulary", "count": skipped_relationships, "blocking": False})
    gaps.append(
        {
            "gap": "authoritative_hydraulic_topology",
            "count": sum(1 for relationship in relationships if relationship.get("inferred")),
            "blocking": False,
            "note": "Inferred edges remain visible but cannot confirm a failure or control state.",
        }
    )

    digest_material = {
        "assets": [
            {
                "asset_id": node["asset_id"],
                "source_hash": node.get("source_hash"),
                "source_ref": node.get("source_ref"),
                "confidence": node.get("confidence"),
                "review_status": node.get("review_status"),
            }
            for node in nodes
        ],
        "relationships": relationships,
        "impact_evidence": [
            {
                "asset_id": item["asset_id"],
                "evidence_id": item.get("evidence_id"),
                "status": item.get("status"),
                "confidence": item.get("confidence"),
            }
            for item in timeline
        ],
    }
    return {
        "schema_version": ASSET_GRAPH_SCHEMA_VERSION,
        "baseline_id": f"AYLAG_{_digest(digest_material)[:24]}",
        "shadow_mode": True,
        "public_notification_enabled": False,
        "automatic_control_actions": False,
        "view_mode": mode,
        "inventory": inventory,
        "municipio_accounting": {
            "expected_count": len(municipalities),
            "represented_count": len(municipalities) - len(missing_municipalities),
            "unresolved_asset_count": unresolved_municipality,
            "missing": missing_municipalities,
            "complete": bool(municipalities) and not missing_municipalities,
        },
        "impact_counts": impact_counts,
        "relationship_count": len(relationships),
        "derived_path_count": len(derived_paths),
        "contradiction_count": sum(len(item["items"]) for item in contradictions),
        "assets": enriched,
        "relationships": relationships,
        "derived_paths": derived_paths,
        "timeline": timeline,
        "contradictions": contradictions,
        "coverage_gaps": gaps,
        "safety": {
            "no_fabricated_topology": True,
            "confidence_only_confirmation_forbidden": True,
            "restricted_control_detail_withheld_in_public_view": mode == "public",
        },
    }


def _reading_dt(row: dict[str, Any]) -> datetime | None:
    return legacy._parse_dt(row.get("observed_date") or row.get("timestamp") or row.get("date") or row.get("time"))


def _resolve_vector(kind: str, metric: str | None) -> tuple[dict[str, Any], str]:
    vector = READING_VECTOR_REGISTRY.get(kind)
    if vector is None:
        raise HTTPException(status_code=400, detail={"error": "unknown_reading_kind", "kind": kind, "allowed": sorted(READING_VECTOR_REGISTRY)})
    metrics: dict[str, dict[str, Any]] = vector["metrics"]
    if metric is None:
        if vector["metric_required"]:
            raise HTTPException(status_code=400, detail={"error": "metric_required", "kind": kind, "allowed": sorted(metrics)})
        metric = next(iter(metrics))
    if metric not in metrics:
        raise HTTPException(status_code=400, detail={"error": "unknown_reading_metric", "kind": kind, "metric": metric, "allowed": sorted(metrics)})
    return vector, metric


def _series_rows(kind: str, metric: str) -> list[dict[str, Any]]:
    vector = READING_VECTOR_REGISTRY[kind]
    allowed_units = vector["metrics"][metric]["units"]
    return [row for row in legacy._load_jsonl(Path(vector["path"])) if row.get("metric") == metric and row.get("unit") in allowed_units]


def _all_incidents(metrics: list[str]) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for metric in metrics:
        metadata = SERIES_METADATA_REGISTRY[metric]
        incidents.extend(lifecycle_alerts(metric, _series_rows(metadata["kind"], metric), legacy._parse_dt))
    return incidents


@app.get("/assets")
def assets(
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    impact: bool = Query(default=False),
    view: str = Query(default="public"),
    impact_status: str | None = Query(default=None),
    municipality: str | None = Query(default=None),
) -> JSONResponse:
    if view not in {"public", "operator"}:
        raise HTTPException(status_code=400, detail={"error": "unknown_asset_view", "view": view})
    operator_view_available = os.getenv("AGUAYLUZ_OPERATOR_ASSET_VIEW_ENABLED", "").lower() in {"1", "true", "yes"}
    if view == "operator" and not operator_view_available:
        raise HTTPException(status_code=403, detail={"error": "operator_asset_view_disabled"})
    if impact:
        payload = _asset_switchboard(view)
        payload["operator_view_available"] = operator_view_available
        items = payload["assets"]
        if type:
            items = [item for item in items if item.get("asset_type") == type]
        if search:
            needle = search.lower()
            items = [
                item for item in items
                if needle in str(item.get("asset_name") or "").lower()
                or needle in str(item.get("asset_id") or "").lower()
                or needle in str(item.get("municipality") or "").lower()
            ]
        if impact_status:
            if impact_status not in ASSET_STATUS_ORDER:
                raise HTTPException(status_code=400, detail={"error": "unknown_impact_status", "impact_status": impact_status})
            items = [item for item in items if item.get("impact_status") == impact_status]
        if municipality:
            key = _norm(municipality)
            items = [item for item in items if _norm(item.get("municipality")) == key]
        payload["assets"] = items
        payload["filtered_asset_count"] = len(items)
        return JSONResponse(payload)

    result = legacy._assets
    if type:
        result = [asset for asset in result if asset.get("asset_type") == type]
    if search:
        needle = search.lower()
        result = [asset for asset in result if needle in (asset.get("asset_name") or "").lower()]
    return JSONResponse(result)


@app.get("/readings")
def readings(kind: str = Query(default="reservoir"), metric: str | None = Query(default=None), parameter_code: str | None = Query(default=None), site_no: str | None = Query(default=None), since: str | None = Query(default=None), until: str | None = Query(default=None)) -> JSONResponse:
    vector, metric = _resolve_vector(kind, metric)
    since_dt, until_dt = legacy._parse_dt(since), legacy._parse_dt(until)
    if since and since_dt is None:
        raise HTTPException(status_code=400, detail={"error": "invalid_since", "value": since})
    if until and until_dt is None:
        raise HTTPException(status_code=400, detail={"error": "invalid_until", "value": until})
    if since_dt and until_dt and since_dt > until_dt:
        raise HTTPException(status_code=400, detail={"error": "invalid_time_range"})
    rows = _series_rows(kind, metric)
    if parameter_code:
        rows = [row for row in rows if str(row.get("parameter_code") or "") == parameter_code]
    if site_no:
        rows = [row for row in rows if str(row.get("site_no") or "") == site_no]
    if since_dt or until_dt:
        rows = [row for row in rows if (observed := _reading_dt(row)) is not None and (not since_dt or observed >= since_dt) and (not until_dt or observed <= until_dt)]
    rows = sorted(rows, key=lambda row: (str(row.get("site_no") or ""), str(row.get("observed_date") or ""), str(row.get("parameter_code") or "")))
    units = sorted({str(row.get("unit")) for row in rows if row.get("unit") not in (None, "")})
    parameter_codes = sorted({str(row.get("parameter_code")) for row in rows if row.get("parameter_code") not in (None, "")})
    sites = Counter(str(row.get("site_no") or "unknown") for row in rows)
    return JSONResponse({"kind": kind, "metric": metric, "parameter_code": parameter_code, "site_no": site_no, "since": since, "until": until, "record_count": len(rows), "site_count": len(sites), "units": units, "parameter_codes": parameter_codes, "mixed_units": len(units) > 1, "provenance": SERIES_METADATA_REGISTRY[metric], "quality": series_quality(metric, rows, legacy._parse_dt), "items": rows})


@app.get("/monitoring/health")
def monitoring_health() -> JSONResponse:
    vectors = {}
    for metric, metadata in SERIES_METADATA_REGISTRY.items():
        rows = _series_rows(metadata["kind"], metric)
        vectors[metric] = {"kind": metadata["kind"], "record_count": len(rows), "quality": series_quality(metric, rows, legacy._parse_dt), "threshold_provenance": metadata["threshold"]["provenance"]}
    events = read_events()
    chain_valid = True
    try:
        verify_chain(events)
    except ValueError:
        chain_valid = False
    return JSONResponse({"series_count": len(vectors), "vectors": vectors, "shadow_water_pipeline": True, "incident_ledger": {"event_count": len(events), "chain_valid": chain_valid, "notification_delivery_enabled": False}})


@app.get("/monitoring/alerts")
def monitoring_alerts(metric: str | None = Query(default=None), state: str = Query(default="active")) -> JSONResponse:
    metrics = [metric] if metric else list(SERIES_METADATA_REGISTRY)
    unknown = [name for name in metrics if name not in SERIES_METADATA_REGISTRY]
    if unknown:
        raise HTTPException(status_code=400, detail={"error": "unknown_reading_metric", "metric": unknown[0]})
    if state not in {"active", "resolved", "all"}:
        raise HTTPException(status_code=400, detail={"error": "unknown_alert_state", "state": state})
    incidents = _all_incidents(metrics)
    if state != "all":
        incidents = [item for item in incidents if item["state"] == state]
    return JSONResponse({"total": len(incidents), "state": state, "items": incidents})


@app.get("/monitoring/alert-operations")
def monitoring_alert_operations() -> JSONResponse:
    incidents = _all_incidents(list(SERIES_METADATA_REGISTRY))
    return JSONResponse({"incident_count": len(incidents), "active_count": sum(item["state"] == "active" for item in incidents), "resolved_count": sum(item["state"] == "resolved" for item in incidents), "deduplicated": True, "items": incidents})


@app.post("/monitoring/incidents/bootstrap", dependencies=[Depends(legacy._require_key)])
def bootstrap_incident_ledger(body: BootstrapRequest) -> JSONResponse:
    existing = materialized_state()
    created = []
    for incident in _all_incidents(list(SERIES_METADATA_REGISTRY)):
        if incident["incident_id"] in existing:
            continue
        created.append(append_event(incident["incident_id"], "opened", body.actor, body.reason, {
            "source": "phase2_materialization", "threshold_version": incident["dedup_key"], "evidence": incident,
        }))
    return JSONResponse({"created": len(created), "events": created})


@app.get("/monitoring/incidents")
def monitoring_incidents() -> JSONResponse:
    events = read_events()
    states = replay(events)
    return JSONResponse({
        "incident_count": len(states), "event_count": len(events), "append_only": True,
        "replay_equals_materialized_state": states == materialized_state(),
        "items": sorted(states.values(), key=lambda item: item["incident_id"]),
    })


@app.get("/monitoring/incidents/{incident_id}/timeline")
def monitoring_incident_timeline(incident_id: str) -> JSONResponse:
    items = timeline(incident_id)
    if not items:
        raise HTTPException(status_code=404, detail={"error": "incident_not_found", "incident_id": incident_id})
    return JSONResponse({"incident_id": incident_id, "event_count": len(items), "items": items})


@app.post("/monitoring/incidents/{incident_id}/transitions", dependencies=[Depends(legacy._require_key)])
def monitoring_incident_transition(incident_id: str, body: IncidentTransition) -> JSONResponse:
    if body.event_type not in ALLOWED_EVENTS - {"opened", "escalated"}:
        raise HTTPException(status_code=400, detail={"error": "unauthorized_transition_type", "event_type": body.event_type})
    states = materialized_state()
    if incident_id not in states:
        raise HTTPException(status_code=404, detail={"error": "incident_not_found", "incident_id": incident_id})
    event = append_event(incident_id, body.event_type, body.actor, body.reason, body.payload)
    return JSONResponse({"event": event, "state": materialized_state()[incident_id]})


@app.get("/monitoring/incidents/escalations/candidates")
def monitoring_escalation_candidates() -> JSONResponse:
    items = escalation_candidates(materialized_state())
    return JSONResponse({"total": len(items), "maintenance_aware": True, "items": items})


@app.get("/monitoring/incidents/notification-outbox")
def monitoring_notification_outbox() -> JSONResponse:
    return JSONResponse(notification_outbox(materialized_state()))


@app.get("/export/monitoring.json")
def export_monitoring() -> JSONResponse:
    series = []
    for metric, metadata in SERIES_METADATA_REGISTRY.items():
        rows = _series_rows(metadata["kind"], metric)
        certified = [row for row in rows if not row.get("provisional")]
        series.append({"metric": metric, "kind": metadata["kind"], "unit": metadata["unit"], "provenance": metadata, "quality": series_quality(metric, rows, legacy._parse_dt), "certified_record_count": len(certified), "items": certified})
    return JSONResponse({"schema_version": "1.0.0", "series": series})


@app.get("/export/federation/monitoring-alerts.json")
def export_federation_monitoring_alerts() -> JSONResponse:
    return JSONResponse(federation_alert_export(_all_incidents(list(SERIES_METADATA_REGISTRY))))


@app.get("/export/federation/monitoring-incident-events.json")
def export_federation_monitoring_incident_events(cursor: str | None = Query(default=None)) -> JSONResponse:
    try:
        return JSONResponse(federation_delta(read_events(), cursor))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "cursor": cursor}) from exc
