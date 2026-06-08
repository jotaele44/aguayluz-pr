"""Pydantic v2 entities mirroring the JSON Schemas in /schemas.

Each model loads its schema at import and runs `jsonschema.validate` in a
`model_validator(mode='after')`. The schema is the single source of truth;
Pydantic adds runtime ergonomics (constructor type checking, IDE support).
"""

from __future__ import annotations

import json
from functools import cache
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import SCHEMAS_DIR

EvidenceTier = Literal["T1", "T2", "T3", "T4"]
ReviewStatus = Literal["accepted", "needs_review", "rejected", "blocked"]
AssetType = Literal["water", "wastewater", "power", "telecom", "fuel", "unknown"]
GeometryType = Literal["point", "line", "polygon", "unknown"]
AssetStatus = Literal["active", "inactive", "damaged", "planned", "unknown"]
EventType = Literal[
    "outage", "restoration", "boil_water", "service_interruption", "project_update", "unknown"
]
AttributeCoverage = Literal["full", "partial"]
ExportStatus = Literal["PASS", "WARN", "FAIL", "BLOCKED"]

Confidence = Annotated[int, Field(ge=0, le=100)]


@cache
def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / f"{name}.schema.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_load_schema(name))


def validate_against_schema(name: str, instance: dict[str, Any]) -> None:
    """Run jsonschema validation; raises `jsonschema.ValidationError` on failure."""
    _validator(name).validate(instance)


class _SchemaValidated(BaseModel):
    """Base class that re-validates the model's dict against its JSON Schema."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    _schema_name: str = ""

    @model_validator(mode="after")
    def _enforce_schema(self) -> _SchemaValidated:
        if self._schema_name:
            validate_against_schema(self._schema_name, self.model_dump(exclude_none=False))
        return self


class UtilityAsset(_SchemaValidated):
    _schema_name: str = "utility_asset"

    asset_id: str
    asset_name: str
    asset_type: AssetType
    asset_subtype: str
    operator: str | None = None
    municipality: str
    lat: float | None = None
    lon: float | None = None
    geometry_type: GeometryType
    status: AssetStatus
    source_ref: str
    source_hash: str | None = None
    evidence_tier: EvidenceTier
    confidence: Confidence
    review_status: ReviewStatus
    attribute_coverage: AttributeCoverage | None = None
    vpuid: str | None = None
    comid: int | None = None
    reachcode: str | None = None
    measure: float | None = None


class ServiceEvent(_SchemaValidated):
    _schema_name: str = "service_event"

    event_id: str
    event_type: EventType
    affected_area: str
    municipality: str | None = None
    zone: str | None = None
    status_text: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    reported_customers_or_users: int | None = None
    source_ref: str
    source_hash: str | None = None
    evidence_tier: EvidenceTier
    confidence: Confidence
    review_status: ReviewStatus
    linked_asset_ids: list[str] = Field(default_factory=list)


class AguayluzBridgeSummary(_SchemaValidated):
    _schema_name: str = "aguayluz_bridge_summary"

    module_id: Literal["aguayluz-pr"] = "aguayluz-pr"
    summary_id: str
    assets_total: int = Field(ge=0)
    events_total: int = Field(ge=0)
    municipalities_covered: list[str]
    service_risk_summary: str
    infrastructure_dependencies: list[str]
    linked_modules: list[str]
    confidence: Confidence
    review_status: ReviewStatus


class Base44Export(_SchemaValidated):
    _schema_name: str = "base44_export"

    module_id: Literal["aguayluz-pr"] = "aguayluz-pr"
    run_id: str
    vector: str
    status: ExportStatus
    coverage_pct: float = Field(ge=0, le=100)
    records_total: int = Field(ge=0)
    records_review: int = Field(ge=0)
    records_blocked: int = Field(ge=0)
    confidence_avg: float = Field(ge=0, le=100)
    source_manifest_path: str
    integration_report_path: str
    sanitized_summary: str
    top_findings: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
