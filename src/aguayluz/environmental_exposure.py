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


class _PFAS:
    """Internal PFAS specialization of the environmental exposure plane."""

    substances = {
        "PFOA": {"cas": "335-67-1", "name": "perfluorooctanoic acid"},
        "PFOS": {"cas": "1763-23-1", "name": "perfluorooctanesulfonic acid"},
        "PFHxS": {"cas": "355-46-4", "name": "perfluorohexanesulfonic acid"},
        "PFNA": {"cas": "375-95-1", "name": "perfluorononanoic acid"},
        "HFPO-DA": {
            "cas": "13252-13-6",
            "name": "hexafluoropropylene oxide dimer acid",
        },
        "PFBS": {"cas": "375-73-5", "name": "perfluorobutanesulfonic acid"},
    }
    evidence_states = frozenset({
        "MEASURED", "ALLEGED", "ASSOCIATED", "CANDIDATE", "ATTRIBUTED",
        "ADJUDICATED", "CONTRADICTED", "EXCLUDED", "UNRESOLVED",
    })
    identity_cardinalities = frozenset({
        "1:1", "1:N", "N:1", "N:N", "0:1", "UNRESOLVED",
    })
    spatial_states = frozenset({
        "FULLY_WITHIN", "PARTIAL", "TOUCH_ONLY", "OUTSIDE", "NULL_EMPTY",
        "UNRESOLVED",
    })
    discovery_only = frozenset({
        "NAME_ONLY", "NORMALIZED_NAME_ONLY", "COUNT_EQUALITY", "NEAREST_ONLY",
        "PROXIMITY_ONLY", "SAME_CATEGORY", "SOURCE_ABSENCE", "TEXT_SEARCH_ONLY",
    })

    @staticmethod
    def normalize_ng_l(value: float, unit: str) -> float:
        unit_norm = unit.strip().lower().replace("µ", "u")
        if unit_norm in {"ng/l", "ppt"}:
            return float(value)
        if unit_norm in {"ug/l", "ppb"}:
            return float(value) * 1000.0
        raise ValueError(f"unsupported PFAS concentration unit: {unit}")

    @classmethod
    def validate_measurement(cls, row: dict[str, Any]) -> None:
        analyte = str(row.get("analyte") or "")
        if analyte not in cls.substances:
            raise ValueError(f"unsupported canonical PFAS analyte: {analyte}")
        if row.get("evidence_state") != "MEASURED":
            raise ValueError("analytical observations must retain evidence_state=MEASURED")
        if not row.get("source_record_id"):
            raise ValueError("measurement requires source_record_id")
        if not row.get("sample_date"):
            raise ValueError("measurement requires sample_date")
        sign = row.get("result_sign")
        if sign not in {"=", "<"}:
            raise ValueError("result_sign must be '=' or '<'")
        value = row.get("result_value")
        if sign == "=" and value is None:
            raise ValueError("detected result requires numeric result_value")
        if sign == "<" and value is not None:
            raise ValueError("non-detect must not synthesize a numeric result_value")
        if sign == "=" and not row.get("result_unit"):
            raise ValueError("numeric result requires result_unit")

    @classmethod
    def validate_binding(cls, row: dict[str, Any]) -> None:
        state = str(row.get("evidence_state") or "")
        if state not in cls.evidence_states:
            raise ValueError(f"unsupported evidence_state: {state}")
        cardinality = str(row.get("identity_cardinality") or "UNRESOLVED")
        if cardinality not in cls.identity_cardinalities:
            raise ValueError(f"unsupported identity cardinality: {cardinality}")
        spatial = row.get("spatial_state")
        if spatial is not None and spatial not in cls.spatial_states:
            raise ValueError(f"unsupported spatial_state: {spatial}")
        evidence_classes = frozenset(str(v) for v in row.get("evidence_classes", []))
        if (
            state in {"ATTRIBUTED", "ADJUDICATED"}
            and evidence_classes
            and evidence_classes <= cls.discovery_only
        ):
            raise ValueError("attribution cannot be established from discovery-only evidence")
        if state == "ADJUDICATED":
            if cardinality == "UNRESOLVED":
                raise ValueError("adjudicated binding requires resolved cardinality")
            if row.get("contradictions"):
                raise ValueError("adjudicated binding cannot retain open contradictions")
            if not row.get("source_record_ids"):
                raise ValueError("adjudicated binding requires source_record_ids")

    @staticmethod
    def current_rule(
        rules: Iterable[dict[str, Any]], analyte: str, as_of: str
    ) -> dict[str, Any] | None:
        candidates = [
            rule
            for rule in rules
            if rule.get("analyte") == analyte
            and (
                rule.get("effective_from") is None
                or str(rule.get("effective_from")) <= as_of
            )
            and str(rule.get("legal_state") or "").startswith("IN_FORCE")
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda rule: (
                str(rule.get("effective_from") or ""),
                str(rule.get("rule_id") or ""),
            ),
        )[-1]

    @classmethod
    def compare_measurement_to_rule(
        cls,
        measurement: dict[str, Any],
        rule: dict[str, Any] | None,
        *,
        as_of: str,
    ) -> dict[str, Any]:
        cls.validate_measurement(measurement)
        if rule is None or rule.get("value") is None:
            return {"state": "NO_APPLICABLE_NUMERIC_RULE", "compliance_finding": False}
        if measurement["result_sign"] == "<":
            return {"state": "NONDETECT_NOT_COMPARABLE", "compliance_finding": False}
        observed = cls.normalize_ng_l(
            float(measurement["result_value"]), str(measurement["result_unit"])
        )
        threshold = cls.normalize_ng_l(float(rule["value"]), str(rule["unit"]))
        return {
            "state": "ABOVE_REFERENCE" if observed > threshold else "AT_OR_BELOW_REFERENCE",
            "observed_ng_l": observed,
            "threshold_ng_l": threshold,
            "rule_id": rule.get("rule_id"),
            "as_of": as_of,
            "compliance_finding": False,
            "note": "A single occurrence measurement is not an MCL compliance determination.",
        }

    @classmethod
    def certification_report(
        cls,
        *,
        source_manifestations: Iterable[dict[str, Any]],
        measurements: Iterable[dict[str, Any]],
        bindings: Iterable[dict[str, Any]],
        unresolved_material: Iterable[str],
    ) -> dict[str, Any]:
        sources = list(source_manifestations)
        observations = list(measurements)
        binding_rows = list(bindings)
        unresolved = sorted(set(str(v) for v in unresolved_material if str(v)))
        errors: list[str] = []
        source_ids = [str(row.get("source_record_id") or "") for row in sources]
        if len(source_ids) != len(set(source_ids)):
            errors.append("duplicate source_record_id")
        for row in sources:
            if (
                not row.get("source_record_id")
                or not row.get("url")
                or not row.get("retrieved_utc")
            ):
                errors.append(
                    f"incomplete source manifestation: {row.get('source_record_id')}"
                )
            if row.get("byte_sha256") is None:
                unresolved.append(f"SOURCE_HASH_OPEN:{row.get('source_record_id')}")
        for row in observations:
            try:
                cls.validate_measurement(row)
            except ValueError as exc:
                errors.append(str(exc))
        for row in binding_rows:
            try:
                cls.validate_binding(row)
            except ValueError as exc:
                errors.append(str(exc))
        unresolved = sorted(set(unresolved))
        structural = "PASS" if not errors else "FAIL"
        certification = "PASS" if structural == "PASS" and not unresolved else "OPEN"
        return {
            "source_count": len(sources),
            "measurement_count": len(observations),
            "binding_count": len(binding_rows),
            "structural_state": structural,
            "error_count": len(errors),
            "errors": errors,
            "unresolved_material_count": len(unresolved),
            "unresolved_material": unresolved,
            "certification_state": certification,
        }
