"""Fail-closed temporal environmental exposure graph primitives.

This module is deliberately independent of source adapters. It defines the
canonical evidence grammar used after source observations have been frozen:
SOURCE -> RELEASE/STRESSOR -> MEDIUM/PATHWAY -> RECEPTOR -> CONSEQUENCE.

Proximity, nearest-neighbour, same-category, and name similarity are discovery
signals only and can never promote a causal relationship.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from typing import Any

ENTITY_KINDS = frozenset({
    "CONTAMINATED_SITE", "SUPERFUND_SITE", "UST_SITE", "LUST_SITE",
    "INDUSTRIAL_FACILITY", "LANDFILL", "SOLID_WASTE_FACILITY",
    "INJECTION_WELL_SITE", "DISPOSAL_SITE", "WASTEWATER_RELEASE_SITE",
    "SPILL_SITE", "UNKNOWN_SOURCE_SITE", "GROUNDWATER", "SURFACE_WATER",
    "SEDIMENT", "SOIL", "AIR", "GROUNDWATER_PLUME",
    "SURFACE_WATER_IMPAIRMENT", "CONTAMINATED_SEDIMENT",
    "SOIL_CONTAMINATION", "WELLHEAD_PROTECTION_AREA", "CAPTURE_ZONE",
    "MODELED_EXPOSURE_ZONE", "DRINKING_WATER_WELL", "WELLFIELD", "INTAKE",
    "RESERVOIR", "SPRING", "TREATMENT_PLANT", "DISTRIBUTION_SYSTEM",
    "WASTEWATER_PLANT", "NPDES_OUTFALL", "PUMP_STATION", "WATERBODY",
    "ECOLOGICAL_RECEPTOR", "REGULATORY_MANIFESTATION",
})

PREDICATES = frozenset({
    "LOCATED_AT", "RELEASED", "DISCHARGED_TO", "CONTAMINATED", "IMPAIRED",
    "MIGRATES_THROUGH", "HYDRAULICALLY_CONNECTED_TO", "INTERSECTS_CAPTURE_ZONE",
    "DETECTED_AT", "ATTRIBUTED_TO", "POTENTIALLY_AFFECTS", "AFFECTS", "SUPPLIES",
    "TREATED_BY", "SHUT_DOWN_BECAUSE_OF", "REACTIVATED_AFTER", "REPLACED_BY",
    "UPSTREAM_OF", "DOWNGRADIENT_OF", "MONITORED_BY", "REGULATED_AS",
    "LISTED_AS", "REMEDIATED_BY",
})

CAUSAL_STATES = frozenset({
    "NOT_TESTED", "DISCOVERY_CANDIDATE", "SPATIALLY_PLAUSIBLE",
    "HYDROLOGICALLY_PLAUSIBLE", "ANALYTICALLY_SUPPORTED",
    "ATTRIBUTION_SUPPORTED", "AUTHORITATIVELY_ATTRIBUTED",
    "CONTRADICTED", "EXCLUDED", "UNRESOLVED",
})

DISCOVERY_ONLY_EVIDENCE = frozenset({
    "PROXIMITY_ONLY", "NEAREST_ONLY", "NAME_ONLY", "NORMALIZED_NAME_ONLY",
    "SAME_CATEGORY", "SOURCE_ABSENCE", "TEXT_SEARCH_ONLY",
})

CAUSAL_PREDICATES = frozenset({
    "CONTAMINATED", "ATTRIBUTED_TO", "AFFECTS", "SHUT_DOWN_BECAUSE_OF",
    "HYDRAULICALLY_CONNECTED_TO", "MIGRATES_THROUGH",
})

PROMOTED_CAUSAL_STATES = frozenset({
    "ANALYTICALLY_SUPPORTED", "ATTRIBUTION_SUPPORTED", "AUTHORITATIVELY_ATTRIBUTED",
})

ALLOWED_GEOMETRY_RELATIONS = frozenset({
    "FULLY_WITHIN", "PARTIAL", "TOUCH_ONLY", "OUTSIDE", "NULL_EMPTY",
    "UNRESOLVED", "INTERSECTS", "NEAR",
})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: Any) -> str:
    """Return a deterministic content-derived identifier."""
    payload = _canonical(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:24]}"


def derive_entity_id(entity_kind: str, authority: str, authority_id: str) -> str:
    if entity_kind not in ENTITY_KINDS:
        raise ValueError(f"unsupported environmental entity kind: {entity_kind}")
    if not authority.strip() or not authority_id.strip():
        raise ValueError("authority and authority_id are required for canonical entity identity")
    return stable_id("AYL_ENV", entity_kind, authority, authority_id)


def derive_relationship_id(
    subject_id: str,
    predicate: str,
    object_id: str,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> str:
    if predicate not in PREDICATES:
        raise ValueError(f"unsupported exposure predicate: {predicate}")
    return stable_id("AYL_EDGE", subject_id, predicate, object_id, valid_from, valid_until)


def validate_relationship(edge: dict[str, Any]) -> None:
    """Validate graph semantics that JSON Schema alone cannot express."""
    predicate = str(edge.get("predicate") or "")
    causal_state = str(edge.get("causal_state") or "")
    evidence_classes = frozenset(str(v) for v in edge.get("evidence_classes", []))
    contradictions = edge.get("contradictions") or []

    if predicate not in PREDICATES:
        raise ValueError(f"unsupported exposure predicate: {predicate}")
    if causal_state not in CAUSAL_STATES:
        raise ValueError(f"unsupported causal state: {causal_state}")

    geometry_relation = edge.get("geometry_relation")
    if geometry_relation is not None and geometry_relation not in ALLOWED_GEOMETRY_RELATIONS:
        raise ValueError(f"unsupported geometry relation: {geometry_relation}")

    discovery_only = bool(evidence_classes) and evidence_classes <= DISCOVERY_ONLY_EVIDENCE
    if predicate in CAUSAL_PREDICATES and causal_state in PROMOTED_CAUSAL_STATES and discovery_only:
        raise ValueError("causal promotion cannot be based solely on discovery/proximity evidence")

    if causal_state == "AUTHORITATIVELY_ATTRIBUTED":
        if contradictions:
            raise ValueError("authoritative attribution cannot retain open contradictions")
        if not edge.get("source_record_ids"):
            raise ValueError("authoritative attribution requires source_record_ids")

    if predicate == "AFFECTS" and causal_state in {"NOT_TESTED", "DISCOVERY_CANDIDATE"}:
        raise ValueError("AFFECTS cannot be asserted while relationship remains untested/discovery-only")

    if edge.get("valid_from") and edge.get("valid_until") and str(edge["valid_from"]) > str(edge["valid_until"]):
        raise ValueError("valid_from must not be after valid_until")


def _duplicate_values(values: Iterable[str]) -> list[str]:
    counts = Counter(str(value) for value in values)
    return sorted(value for value, count in counts.items() if count > 1)


def integrity_report(
    *,
    entity_ids: Iterable[str],
    observations: Iterable[dict[str, Any]],
    geometries: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    relationships: Iterable[dict[str, Any]],
    external_entity_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Return structural arithmetic and referential-integrity diagnostics.

    This is deliberately not a corpus-certification result. A structurally valid
    empty graph can PASS while the public-source denominator remains OPEN.
    """
    entity_values = [str(value) for value in entity_ids]
    external_values = [str(value) for value in external_entity_ids]
    observation_rows = list(observations)
    geometry_rows = list(geometries)
    event_rows = list(events)
    relationship_rows = list(relationships)

    entities = set(entity_values)
    external_entities = set(external_values)
    endpoint_ids = entities | external_entities
    observation_ids = [str(row.get("observation_id") or "") for row in observation_rows]
    geometry_ids = [str(row.get("geometry_id") or "") for row in geometry_rows]
    event_ids = [str(row.get("event_id") or "") for row in event_rows]
    relationship_ids = [str(row.get("relationship_id") or "") for row in relationship_rows]
    observation_id_set = set(observation_ids)
    geometry_id_set = set(geometry_ids)

    errors: list[str] = []
    states: Counter[str] = Counter()

    duplicate_groups = {
        "entity_id": _duplicate_values(entity_values),
        "external_entity_id": _duplicate_values(external_values),
        "observation_id": _duplicate_values(observation_ids),
        "geometry_id": _duplicate_values(geometry_ids),
        "event_id": _duplicate_values(event_ids),
        "relationship_id": _duplicate_values(relationship_ids),
    }
    for label, values in duplicate_groups.items():
        for value in values:
            errors.append(f"duplicate {label}: {value}")

    overlap = sorted(entities & external_entities)
    for value in overlap:
        errors.append(f"environmental/external identity collision: {value}")

    for row in observation_rows:
        oid = row.get("observation_id")
        for entity_id in row.get("entity_ids", []):
            if entity_id not in endpoint_ids:
                errors.append(f"{oid}: orphan entity_id {entity_id}")

    for row in geometry_rows:
        gid = row.get("geometry_id")
        entity_id = row.get("entity_id")
        if entity_id not in endpoint_ids:
            errors.append(f"{gid}: orphan entity_id {entity_id}")

    for row in event_rows:
        event_id = row.get("event_id")
        for entity_id in row.get("entity_ids", []):
            if entity_id not in endpoint_ids:
                errors.append(f"{event_id}: orphan entity_id {entity_id}")

    for edge in relationship_rows:
        try:
            validate_relationship(edge)
        except ValueError as exc:
            errors.append(f"{edge.get('relationship_id', '<missing>')}: {exc}")
        states[str(edge.get("causal_state") or "MISSING")] += 1

        if edge.get("subject_id") not in endpoint_ids:
            errors.append(f"{edge.get('relationship_id')}: orphan subject_id {edge.get('subject_id')}")
        if edge.get("object_id") not in endpoint_ids:
            errors.append(f"{edge.get('relationship_id')}: orphan object_id {edge.get('object_id')}")

        for oid in edge.get("supporting_observation_ids", []):
            if oid not in observation_id_set:
                errors.append(f"{edge.get('relationship_id')}: orphan observation_id {oid}")
        for gid in edge.get("supporting_geometry_ids", []):
            if gid not in geometry_id_set:
                errors.append(f"{edge.get('relationship_id')}: orphan geometry_id {gid}")

    arithmetic_closes = sum(states.values()) == len(relationship_rows)
    return {
        "environmental_entity_count": len(entity_values),
        "external_entity_count": len(external_values),
        "observation_count": len(observation_rows),
        "geometry_count": len(geometry_rows),
        "event_count": len(event_rows),
        "relationship_count": len(relationship_rows),
        "state_counts": dict(sorted(states.items())),
        "state_count_sum": sum(states.values()),
        "arithmetic_closes": arithmetic_closes,
        "duplicate_ids": duplicate_groups,
        "error_count": len(errors),
        "errors": errors,
        "structural_integrity_state": "PASS" if not errors and arithmetic_closes else "FAIL",
        "corpus_certification_state": "OPEN",
    }
