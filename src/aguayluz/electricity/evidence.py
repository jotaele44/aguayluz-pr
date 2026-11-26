"""Versioned source claims with independent epistemic and review classifications."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EvidenceClass(str, Enum):
    OBSERVED = "OBSERVED"
    RECONSTRUCTED = "RECONSTRUCTED"
    FORECAST = "FORECAST"
    SOURCE_CANDIDATE = "SOURCE_CANDIDATE"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SourceReceipt(StrictModel):
    schema_version: Literal["aguayluz.electricity-source/v1"] = "aguayluz.electricity-source/v1"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)
    source_url: str
    authority: str = Field(min_length=1)
    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None = None
    license: str = "UNRESOLVED"
    schema_signature: str = Field(min_length=1)
    request_parameters: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def safe_url(self) -> SourceReceipt:
        url = urlsplit(self.source_url)
        # Queries may contain credentials. Store source identity without any query.
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("source URL must be credential-free HTTPS without query or fragment")
        if any("key" in k.lower() or "token" in k.lower() or "secret" in k.lower() for k, _ in self.request_parameters):
            raise ValueError("credential parameters cannot enter a receipt")
        return self


class Measurement(StrictModel):
    schema_version: Literal["aguayluz.electricity-measurement/v1"] = "aguayluz.electricity-measurement/v1"
    entity_id: str = Field(min_length=1, max_length=200)
    metric: str = Field(min_length=1)
    value: float
    unit: Literal["MW", "MWh", "kWh", "%", "USD/kWh", "m", "m3", "m3/s"]
    interval_start: AwareDatetime
    interval_end: AwareDatetime
    evidence_class: EvidenceClass
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_flags: tuple[str, ...] = ()
    method_version: str | None = None
    uncertainty: float | None = Field(default=None, ge=0)
    issued_at: AwareDatetime | None = None
    review_state: Literal["AUDIT_ONLY"] = "AUDIT_ONLY"

    @model_validator(mode="after")
    def scientific_requirements(self) -> Measurement:
        if self.interval_end <= self.interval_start:
            raise ValueError("measurement interval must be positive")
        if self.evidence_class in {EvidenceClass.RECONSTRUCTED, EvidenceClass.FORECAST} and (
            not self.method_version or self.uncertainty is None
        ):
            raise ValueError("derived states require method version and uncertainty")
        if self.evidence_class == EvidenceClass.FORECAST and (
            self.issued_at is None or self.issued_at > self.interval_start
        ):
            raise ValueError("forecast issue time must precede its target interval")
        return self


class GeneratorClaim(StrictModel):
    schema_version: Literal["aguayluz.electricity-generator/v1"] = "aguayluz.electricity-generator/v1"
    source_system: Literal["EIA-860M", "EIA-860", "EIA-923"]
    plant_id: str = Field(pattern=r"^[1-9][0-9]*$")
    generator_id: str = Field(min_length=1, max_length=32)
    valid_from: datetime
    valid_to: datetime | None = None
    name: str = Field(min_length=1)
    nameplate_mw: float = Field(ge=0)
    status: str = Field(min_length=1)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_state: Literal["AUDIT_ONLY"] = "AUDIT_ONLY"
    evidence_class: Literal["SOURCE_CANDIDATE"] = "SOURCE_CANDIDATE"

    @model_validator(mode="after")
    def valid_interval(self) -> GeneratorClaim:
        if self.valid_from.tzinfo is None or (self.valid_to is not None and (
            self.valid_to.tzinfo is None or self.valid_to <= self.valid_from
        )):
            raise ValueError("identity intervals require aware, increasing timestamps")
        if self.generator_id != self.generator_id.strip():
            raise ValueError("preserve raw generator identifiers; whitespace needs adjudication")
        return self

    @property
    def source_identity(self) -> str:
        # Names, coordinates, and neighboring assets never enter identity construction.
        return f"{self.source_system}:{self.plant_id}:{self.generator_id}"


def reconcile_claims(claims: list[GeneratorClaim]) -> dict:
    """Retain all versions and report conflicting overlaps; never infer crosswalks."""
    ordered = sorted(claims, key=lambda c: (c.source_identity, c.valid_from, c.receipt_sha256))
    conflicts = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            if left.source_identity != right.source_identity:
                continue
            overlaps = (left.valid_to is None or right.valid_from < left.valid_to) and (
                right.valid_to is None or left.valid_from < right.valid_to
            )
            if overlaps and (left.nameplate_mw, left.status, left.name) != (right.nameplate_mw, right.status, right.name):
                conflicts.append({"identity": left.source_identity, "left": left.receipt_sha256,
                                  "right": right.receipt_sha256, "state": "UNRESOLVED"})
    return {"claims": [c.model_dump(mode="json") for c in ordered], "contradictions": conflicts,
            "canonical_promotion": "BLOCKED", "identity_basis": "SOURCE_IDENTIFIER_ONLY"}
