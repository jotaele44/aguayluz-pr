"""Mycelial observation contracts for AguaYLuz-PR.

These models mirror the JSON Schemas in /schemas and keep the schema files as
the source of truth, matching src/aguayluz/models.py.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import validate_against_schema

EvidenceTier = Literal["T1", "T2", "T3", "T4"]
ReviewStatus = Literal["accepted", "needs_review", "rejected", "blocked"]
Confidence = Annotated[int, Field(ge=0, le=100)]


class _SchemaValidated(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    _schema_name: str = ""

    @model_validator(mode="after")
    def _enforce_schema(self) -> _SchemaValidated:
        if self._schema_name:
            validate_against_schema(self._schema_name, self.model_dump(exclude_none=False))
        return self


class SourceLicense(_SchemaValidated):
    _schema_name: str = "source_license"

    license_id: str
    license_name: str
    license_url: str | None = None
    reuse_allowed: bool
    commercial_use_allowed: bool | None = None
    derivatives_allowed: bool
    attribution_required: bool
    attribution_text: str | None = None
    location_precision_allowed: Literal["precise", "generalized", "prohibited"]
    redistribution_allowed: Literal["full", "derived_only", "none"]
    required_citation: str
    notes: str | None = None


class ObservationSource(_SchemaValidated):
    _schema_name: str = "observation_source"

    source_id: str
    source_name: str
    source_type: Literal[
        "public_database",
        "research_partner",
        "field_survey",
        "literature",
        "agency_record",
        "citizen_science",
        "derived_dataset",
    ]
    source_ref: str
    source_url: str | None = None
    access_method: Literal["manual_download", "api", "archive", "local_file", "partner_transfer"]
    evidence_tier: EvidenceTier
    license_id: str
    attribution_required: bool
    access_date: str
    extracted_at: str
    source_hash: str | None = None
    notes: str | None = None


class RawObservation(_SchemaValidated):
    _schema_name: str = "raw_observation"

    observation_id: str
    source_id: str
    observed_at: str | None = None
    reported_at: str | None = None
    taxon_label_raw: str
    taxon_rank: Literal["kingdom", "phylum", "class", "order", "family", "genus", "species", "unknown"]
    scientific_name: str | None = None
    common_name: str | None = None
    substrate: Literal[
        "soil",
        "wood",
        "leaf_litter",
        "root_zone",
        "waterlogged_soil",
        "built_environment",
        "unknown",
    ] = "unknown"
    habitat_context: Literal[
        "forest",
        "mangrove",
        "karst",
        "riparian",
        "urban",
        "agricultural",
        "coastal",
        "reservoir_margin",
        "unknown",
    ] = "unknown"
    municipality: str | None
    lat: float
    lon: float
    coordinate_precision_m: float
    location_source: Literal["gps", "geocoded", "centroid", "source_metadata", "unknown"]
    photo_refs: list[str] = Field(default_factory=list)
    voucher_ref: str | None = None
    observer_type: Literal["agency", "researcher", "citizen", "automated", "unknown"] = "unknown"
    source_ref: str
    source_hash: str | None = None
    evidence_tier: EvidenceTier
    license_id: str
    access_guidance_present: Literal[False] = False
    review_status: ReviewStatus
    confidence: Confidence


class VerificationStatus(_SchemaValidated):
    _schema_name: str = "verification_status"

    verification_id: str
    observation_id: str
    status: Literal[
        "unverified",
        "source_verified",
        "taxon_verified",
        "location_verified",
        "duplicate",
        "rejected",
        "blocked",
    ]
    verification_method: Literal[
        "source_authority",
        "image_review",
        "metadata_consistency",
        "spatial_consistency",
        "cross_source_match",
        "manual_review",
    ]
    reviewer: str | None = None
    verified_at: str | None = None
    confidence_delta: Annotated[int, Field(ge=-100, le=100)]
    flags: list[Literal[
        "taxon_uncertain",
        "location_uncertain",
        "duplicate_candidate",
        "license_restricted",
        "sensitive_site",
        "access_guidance_detected",
        "needs_expert_review",
    ]] = Field(default_factory=list)
    notes: str | None = None


class GridCellAggregation(_SchemaValidated):
    _schema_name: str = "grid_cell_aggregation"

    grid_id: str
    grid_scheme: Literal["degree_bin", "h3", "geohash", "custom_pr_grid"]
    grid_resolution: str
    geometry: dict[str, Any] | None = None
    centroid_lat: float
    centroid_lon: float
    municipalities: list[str]
    observation_count: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    taxa_count: int = Field(ge=0)
    dominant_habitat_context: str | None = None
    dominant_substrate: str | None = None
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    mean_confidence: float = Field(ge=0, le=100)
    source_count: int = Field(ge=0)
    attribution_refs: list[str]
    precision_mode: Literal["precise_research", "aggregate_public"]
    review_status: Literal["accepted", "needs_review", "blocked"]
