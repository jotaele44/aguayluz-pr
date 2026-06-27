"""Pydantic v2 entities for the AguaYLuz-PR operational alert system.

Mirrors the pattern in :mod:`aguayluz.models`: each model declares a
``_schema_name`` and re-validates its dict against the matching JSON Schema in
``/schemas`` via the shared :class:`aguayluz.models._SchemaValidated` base.

The alert system is a permanent multi-sector framework (10 modules; 5 active:
HYDRO_OPS, POWER_OPS, WEATHER_HAZARD, CONTAMINATION, DAM_SAFETY). It is
harmonized to repo idioms (confidence 0-100, evidence_tier T1-T4, AYL_ ids)
while preserving the workbook's operational fields (severity floor 0-5,
gap_status, structural covert flags).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .models import Confidence, EvidenceTier, ReviewStatus, _SchemaValidated

ModuleId = Literal[
    "HYDRO_OPS",
    "POWER_OPS",
    "WEATHER_HAZARD",
    "CONTAMINATION",
    "TRANSPORT_ACCESS",
    "TELECOM_SCADA",
    "DAM_SAFETY",
    "SEISMIC_GEO",
    "INDUSTRIAL",
    "PUBLIC_NOTICE",
]
AlertEventType = Literal[
    "maintenance", "outage", "failure", "quality", "hazard", "inspection", "unknown"
]
AlertStatus = Literal["draft", "validated", "active", "closed", "rejected"]
CoordConfidence = Literal["exact", "approximate", "unknown"]
GapStatus = Literal["none", "minor", "major", "blocking"]
GapSeverity = Literal["minor", "major", "blocking"]
GapState = Literal["open", "closed"]
ActivationStatus = Literal["active", "dormant"]
Priority = Literal["critical", "high", "medium", "low"]
HydroRelevance = Literal["direct", "indirect", "evidence"]

# Operational severity uses the workbook's 0-5 scale (distinct from confidence).
Severity = int

#: Active modules immediately enabled per the workbook README.
ACTIVE_MODULES: frozenset[str] = frozenset(
    {"HYDRO_OPS", "POWER_OPS", "WEATHER_HAZARD", "CONTAMINATION", "DAM_SAFETY"}
)


class AlertEvent(_SchemaValidated):
    _schema_name: str = "alert_event"

    alert_id: str
    module_id: ModuleId
    event_type: AlertEventType
    status: AlertStatus
    source_title: str
    source_ref: str
    source_hash: str | None = None
    published_at: str | None = None
    start_at: str
    end_at: str | None = None
    estimated_duration_hr: float | None = None
    asset_name: str
    asset_id: str | None = None
    operator: str | None = None
    municipalities: list[str]
    sectors_impacted: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    coord_confidence: CoordConfidence
    severity: int = Field(ge=0, le=5)
    confidence: Confidence
    ilap_score: int | None = Field(default=None, ge=0, le=5)
    covert_flags: list[str] = Field(default_factory=list)
    gap_status: GapStatus
    review_status: ReviewStatus
    evidence_tier: EvidenceTier
    linked_asset_ids: list[str] = Field(default_factory=list)
    validation_notes: str | None = None


class AlertModule(_SchemaValidated):
    _schema_name: str = "alert_module"

    module_id: ModuleId
    module_name: str
    sector: str
    activation_status: ActivationStatus
    priority: Priority
    hydro_dependency_relevance: HydroRelevance
    default_severity_floor: int = Field(ge=0, le=5)
    primary_sources: str | None = None
    notes: str | None = None


class DependencyEdge(_SchemaValidated):
    _schema_name: str = "alert_dependency_edge"

    edge_id: str
    from_node_type: str
    from_node_id: str | None = None
    to_node_type: str
    to_node_id: str | None = None
    dependency_type: str
    confidence: Confidence
    evidence_required: bool
    notes: str | None = None


class AlertGap(_SchemaValidated):
    _schema_name: str = "alert_gap"

    gap_id: str
    alert_id: str | None = None
    module_id: str
    gap_type: str
    severity: GapSeverity
    blocking: bool
    description: str
    next_action: str
    status: GapState = "open"
