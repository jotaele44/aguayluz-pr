"""Canonical Puerto Rico hazard/advisory plane primitives.

This module is source-adapter independent. It preserves raw source semantics,
revision history, cardinality and evidence class while refusing to promote
spatial/temporal coincidence into causation.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HazardFamily(str, Enum):
    WATER_HEALTH = "WATER_HEALTH"
    FOOD_SAFETY = "FOOD_SAFETY"
    AGRICULTURAL_HEALTH = "AGRICULTURAL_HEALTH"
    ANIMAL_HEALTH = "ANIMAL_HEALTH"
    HUMAN_INFECTIOUS_DISEASE = "HUMAN_INFECTIOUS_DISEASE"
    WASTEWATER_SURVEILLANCE = "WASTEWATER_SURVEILLANCE"
    ENVIRONMENTAL_HEALTH = "ENVIRONMENTAL_HEALTH"


class RecordKind(str, Enum):
    EVENT = "EVENT"
    OBSERVATION = "OBSERVATION"
    ADVISORY = "ADVISORY"
    ACTION = "ACTION"


class RecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    UNRESOLVED = "UNRESOLVED"


class CaseClass(str, Enum):
    SUSPECTED = "SUSPECTED"
    PROBABLE = "PROBABLE"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"


class EvidenceClass(str, Enum):
    STABLE_ID = "STABLE_ID"
    AUTHORITATIVE_BINDING = "AUTHORITATIVE_BINDING"
    CERTIFIED_GEOMETRY = "CERTIFIED_GEOMETRY"
    POINT_IN_POLYGON_WITH_ALIAS = "POINT_IN_POLYGON_WITH_ALIAS"
    POINT_IN_POLYGON = "POINT_IN_POLYGON"
    ALIAS_WITH_SPATIOTEMPORAL_SUPPORT = "ALIAS_WITH_SPATIOTEMPORAL_SUPPORT"
    HISTORICAL_CONTINUITY = "HISTORICAL_CONTINUITY"
    PROXIMITY = "PROXIMITY"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    UNRESOLVED = "UNRESOLVED"


class RelationshipType(str, Enum):
    SAME_LOCATION = "SAME_LOCATION"
    SPATIALLY_INTERSECTS = "SPATIALLY_INTERSECTS"
    SAME_WATERSHED = "SAME_WATERSHED"
    UPSTREAM_OF = "UPSTREAM_OF"
    DOWNSTREAM_OF = "DOWNSTREAM_OF"
    SAME_SEWERSHED = "SAME_SEWERSHED"
    SAME_WATER_SYSTEM = "SAME_WATER_SYSTEM"
    TEMPORALLY_OVERLAPS = "TEMPORALLY_OVERLAPS"
    PRODUCT_DISTRIBUTED_TO = "PRODUCT_DISTRIBUTED_TO"
    CONFIRMED_EXPOSURE = "CONFIRMED_EXPOSURE"
    OFFICIALLY_ASSOCIATED = "OFFICIALLY_ASSOCIATED"
    EPIDEMIOLOGICALLY_LINKED = "EPIDEMIOLOGICALLY_LINKED"
    STATISTICAL_ASSOCIATION = "STATISTICAL_ASSOCIATION"
    CAUSALLY_CONFIRMED = "CAUSALLY_CONFIRMED"


CAUSAL_RELATIONSHIPS = {
    RelationshipType.CONFIRMED_EXPOSURE,
    RelationshipType.OFFICIALLY_ASSOCIATED,
    RelationshipType.EPIDEMIOLOGICALLY_LINKED,
    RelationshipType.STATISTICAL_ASSOCIATION,
    RelationshipType.CAUSALLY_CONFIRMED,
}


class Manifestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifestation_id: str = Field(min_length=1)
    source_authority: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    retrieved_at_utc: datetime
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_signature: str | None = None
    record_count: int | None = Field(default=None, ge=0)


class HazardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1)
    record_kind: RecordKind
    family: HazardFamily
    hazard_type: str = Field(min_length=1)
    source_authority: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    manifestation_id: str = Field(min_length=1)

    title_raw: str = Field(min_length=1)
    description_raw: str | None = None
    normalized_label: str | None = None
    canonical_agent_id: str | None = None

    status: RecordStatus
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    reported_at: datetime | None = None
    issued_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    municipality_id: str | None = None
    barrio_id: str | None = None
    watershed_id: str | None = None
    water_system_id: str | None = None
    facility_id: str | None = None
    geography_basis: str | None = None
    geometry_precision: str | None = None

    case_class: CaseClass | None = None
    case_definition_version: str | None = None
    suspected_cases: int | None = Field(default=None, ge=0)
    probable_cases: int | None = Field(default=None, ge=0)
    confirmed_cases: int | None = Field(default=None, ge=0)
    provisional: bool = False
    suppressed: bool = False

    supersedes_record_id: str | None = None
    raw_attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_temporal_and_case_semantics(self) -> "HazardRecord":
        if self.observed_from and self.observed_to and self.observed_to < self.observed_from:
            raise ValueError("observed_to cannot precede observed_from")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        if self.family == HazardFamily.HUMAN_INFECTIOUS_DISEASE:
            if self.case_class is None:
                raise ValueError("human disease records require case_class")
            if self.case_definition_version is None:
                raise ValueError("human disease records require case_definition_version")
        return self


class HazardRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    predicate: RelationshipType
    object_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    source_manifestation_ids: list[str] = Field(min_length=1)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    distance_m: float | None = Field(default=None, ge=0)
    method: str | None = None
    effect_size: float | None = None
    confidence_interval: str | None = None
    p_value: float | None = Field(default=None, ge=0, le=1)
    sample_size: int | None = Field(default=None, ge=0)
    confounders: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_causality_firewall(self) -> "HazardRelationship":
        if self.predicate in CAUSAL_RELATIONSHIPS:
            if self.evidence_class in {
                EvidenceClass.PROXIMITY,
                EvidenceClass.DISCOVERY_ONLY,
                EvidenceClass.UNRESOLVED,
                EvidenceClass.POINT_IN_POLYGON,
            }:
                raise ValueError("causal/epidemiological predicates require independent evidence")
        if self.predicate == RelationshipType.STATISTICAL_ASSOCIATION:
            if self.method is None or self.sample_size is None:
                raise ValueError("statistical association requires method and sample_size")
        if self.predicate == RelationshipType.CAUSALLY_CONFIRMED:
            if self.evidence_class not in {
                EvidenceClass.STABLE_ID,
                EvidenceClass.AUTHORITATIVE_BINDING,
            }:
                raise ValueError("causal confirmation requires authoritative evidence")
        return self


def canonical_json_sha256(payload: Any) -> str:
    """Hash a canonical JSON serialization; never compare aggregate hashes otherwise."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def current_records(records: list[HazardRecord]) -> list[HazardRecord]:
    """Whole-row latest-selection without field aggregation/synthetic records."""
    superseded = {row.supersedes_record_id for row in records if row.supersedes_record_id}
    candidates = [row for row in records if row.record_id not in superseded]
    return [row for row in candidates if row.status != RecordStatus.SUPERSEDED]


def validate_identity_uniqueness(records: list[HazardRecord]) -> list[str]:
    counts = Counter(row.record_id for row in records)
    return sorted(record_id for record_id, count in counts.items() if count > 1)


def source_arithmetic(
    source_count: int,
    retained_count: int,
    excluded_count: int,
    unresolved_count: int,
) -> dict[str, Any]:
    if min(source_count, retained_count, excluded_count, unresolved_count) < 0:
        raise ValueError("counts must be non-negative")
    accounted = retained_count + excluded_count + unresolved_count
    return {
        "source": source_count,
        "retained": retained_count,
        "excluded": excluded_count,
        "unresolved": unresolved_count,
        "accounted": accounted,
        "delta": source_count - accounted,
        "state": "PASS" if source_count == accounted else "FAIL",
    }


def integrity_report(
    records: list[HazardRecord],
    relationships: list[HazardRelationship],
    manifestations: list[Manifestation],
) -> dict[str, Any]:
    record_ids = {row.record_id for row in records}
    manifestation_ids = {row.manifestation_id for row in manifestations}
    duplicate_record_ids = validate_identity_uniqueness(records)
    dangling_relationships = sorted(
        row.relationship_id
        for row in relationships
        if row.subject_id not in record_ids or row.object_id not in record_ids
    )
    missing_manifestations = sorted({
        manifestation_id
        for row in records
        for manifestation_id in [row.manifestation_id]
        if manifestation_id not in manifestation_ids
    } | {
        manifestation_id
        for row in relationships
        for manifestation_id in row.source_manifestation_ids
        if manifestation_id not in manifestation_ids
    })
    unresolved = []
    if duplicate_record_ids:
        unresolved.append("DUPLICATE_RECORD_IDS")
    if dangling_relationships:
        unresolved.append("DANGLING_RELATIONSHIPS")
    if missing_manifestations:
        unresolved.append("MISSING_SOURCE_MANIFESTATIONS")
    return {
        "state": "PASS" if not unresolved else "FAIL",
        "counts": {
            "records": len(records),
            "current_records": len(current_records(records)),
            "relationships": len(relationships),
            "manifestations": len(manifestations),
        },
        "duplicate_record_ids": duplicate_record_ids,
        "dangling_relationships": dangling_relationships,
        "missing_manifestations": missing_manifestations,
        "unresolved": unresolved,
    }
