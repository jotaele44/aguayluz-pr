"""Typed contracts for the AguaYLuz source-intelligence control plane."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CoverageRole(str, Enum):
    PRIMARY_AUTHORITY = "PRIMARY_AUTHORITY"
    SECONDARY_AUTHORITY = "SECONDARY_AUTHORITY"
    OPERATIONAL = "OPERATIONAL"
    REGULATORY_RECORD = "REGULATORY_RECORD"
    SPATIAL_AUTHORITY = "SPATIAL_AUTHORITY"
    CORROBORATIVE = "CORROBORATIVE"
    HISTORICAL = "HISTORICAL"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    DERIVED = "DERIVED"
    NONBINDING = "NONBINDING"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class CoverageState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CLASSIFIED = "CLASSIFIED"
    REGISTERED = "REGISTERED"
    ADAPTER_PLANNED = "ADAPTER_PLANNED"
    ADAPTER_IMPLEMENTED = "ADAPTER_IMPLEMENTED"
    ACQUISITION_PASS = "ACQUISITION_PASS"
    PARSER_PASS = "PARSER_PASS"
    IDENTITY_PASS = "IDENTITY_PASS"
    MONITORING_PASS = "MONITORING_PASS"
    PROVENANCE_PASS = "PROVENANCE_PASS"
    DOMAIN_READY = "DOMAIN_READY"
    CERTIFIED = "CERTIFIED"
    BLOCKED = "BLOCKED"
    QUARANTINED = "QUARANTINED"
    UNRESOLVED = "UNRESOLVED"
    NONCANONICAL = "NONCANONICAL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    NO_CHANGE = "NO_CHANGE"
    NEW_MANIFESTATION = "NEW_MANIFESTATION"
    STALE = "STALE"
    FETCH_FAILED = "FETCH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    CONTENT_TYPE_CHANGED = "CONTENT_TYPE_CHANGED"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    PARSE_FAILED = "PARSE_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    QUARANTINED = "QUARANTINED"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    SOURCE_REMOVED = "SOURCE_REMOVED"
    SUPERSEDED = "SUPERSEDED"


class MonitoringMode(str, Enum):
    POLL_INTERVAL = "POLL_INTERVAL"
    DISCOVER_NEW_RELEASE = "DISCOVER_NEW_RELEASE"
    DAILY_INDEX_SCAN = "DAILY_INDEX_SCAN"
    SERVICE_STATE_MONITOR = "SERVICE_STATE_MONITOR"
    IMMUTABLE_ARCHIVE = "IMMUTABLE_ARCHIVE"


class DomainDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    label: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    required_data_classes: tuple[str, ...] = Field(min_length=1)
    certification_rule: str = Field(min_length=1)


class SourceFamilyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_family_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    authority: str = Field(min_length=1)
    label: str = Field(min_length=1)
    canonical_locator: str = Field(min_length=1)
    monitoring_mode: MonitoringMode
    adapter_id: str | None = None
    identity_namespace: str | None = None
    mutable: bool = True


class DomainSourceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain_id: str
    source_family_id: str
    role: CoverageRole
    required: bool = False
    adapter_required: bool = False
    state: CoverageState = CoverageState.REGISTERED
    temporal_scope: str = "CURRENT_AND_HISTORICAL_AS_AVAILABLE"
    spatial_scope: str = "PUERTO_RICO"

    @model_validator(mode="after")
    def required_sources_cannot_be_out_of_scope(self) -> "DomainSourceRequirement":
        if self.required and self.role == CoverageRole.OUT_OF_SCOPE:
            raise ValueError("required source family cannot be OUT_OF_SCOPE")
        return self


class SourceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_family_id: str
    state: HealthState
    last_check: datetime | None = None
    last_success: datetime | None = None
    last_change: datetime | None = None
    current_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    schema_fingerprint: str | None = None
    record_count: int | None = Field(default=None, ge=0)
    error_class: str | None = None


class CoverageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_domains: int = Field(ge=0)
    total_source_families: int = Field(ge=0)
    total_requirements: int = Field(ge=0)
    required_requirements: int = Field(ge=0)
    classified_requirements: int = Field(ge=0)
    unclassified_material_cells: int = Field(ge=0)
    unknown_primary_source_families: int = Field(ge=0)
    domains_without_required_source: tuple[str, ...] = ()
    structural_readiness_score: float = Field(ge=0, le=100)
    coverage_matrix_ready: bool
