"""Design-only contracts for provenance-safe regulatory ingestion.

This module performs no network, persistence, scheduler, or entity-promotion work.
Provider implementations must be introduced and activated in separate reviewed
changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence


class Provider(StrEnum):
    EPA = "EPA"
    FDA = "FDA"
    USGS = "USGS"
    DRNA = "DRNA"
    PRASA_AAA = "PRASA_AAA"
    PREQB = "PREQB"


class RecordFamily(StrEnum):
    ENTITY = "entity"
    PERMIT = "permit"
    INSPECTION = "inspection"
    ENFORCEMENT = "enforcement"


class FreshnessState(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"
    STALE = "stale"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider: Provider
    record_families: frozenset[RecordFamily]
    pagination: str
    authentication_class: str
    rate_limit_policy: str
    public_export_constraints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryCheckpoint:
    provider: Provider
    cursor: str | None = None
    watermark: datetime | None = None
    opaque_state: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecordLocator:
    provider: Provider
    provider_record_id: str
    locator: str
    record_family: RecordFamily


@dataclass(frozen=True, slots=True)
class RawRegulatoryRecord:
    locator: RecordLocator
    content: bytes
    media_type: str
    retrieved_at: datetime
    transport_metadata: Mapping[str, str | int | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    receipt_id: str
    provider: Provider
    retrieved_at: datetime
    request_locator: str
    sha256: str
    byte_count: int
    media_type: str
    retrieval_status: str
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    redactions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegulatoryObservation:
    observation_id: str
    record_family: RecordFamily
    provider: Provider
    provider_record_id: str
    observed_at: datetime
    retrieved_at: datetime
    source_receipt_id: str
    normalization_version: str
    evidence_tier: str
    freshness_state: FreshnessState
    payload: Mapping[str, Any]
    identifiers: tuple[tuple[str, str], ...] = ()
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class RegulatoryProviderAdapter(Protocol):
    """Provider-neutral, side-effect-bounded ingestion interface."""

    def capabilities(self) -> ProviderCapabilities:
        """Declare static adapter behavior and export restrictions."""

    def discover(
        self,
        query: Mapping[str, Any],
        checkpoint: DiscoveryCheckpoint | None = None,
    ) -> tuple[Sequence[RecordLocator], DiscoveryCheckpoint]:
        """Return locators only; discovery must not promote facility identity."""

    def fetch(self, locator: RecordLocator) -> tuple[RawRegulatoryRecord, SourceReceipt]:
        """Return immutable raw bytes and their cryptographic receipt."""

    def normalize(
        self,
        raw_record: RawRegulatoryRecord,
        receipt: SourceReceipt,
    ) -> Sequence[RegulatoryObservation]:
        """Emit source assertions only; canonical linkage is forbidden here."""

    def checkpoint(self) -> DiscoveryCheckpoint:
        """Return resumable state containing no secrets or authorization data."""


PROVIDER_BASELINE_CAPABILITIES: dict[Provider, ProviderCapabilities] = {
    Provider.EPA: ProviderCapabilities(Provider.EPA, frozenset(RecordFamily), "provider-specific", "public_or_key", "bounded"),
    Provider.FDA: ProviderCapabilities(Provider.FDA, frozenset(RecordFamily), "provider-specific", "public_or_key", "bounded"),
    Provider.USGS: ProviderCapabilities(Provider.USGS, frozenset({RecordFamily.ENTITY}), "provider-specific", "public_or_key", "bounded"),
    Provider.DRNA: ProviderCapabilities(Provider.DRNA, frozenset(RecordFamily), "record-dependent", "record-dependent", "manual_until_approved"),
    Provider.PRASA_AAA: ProviderCapabilities(Provider.PRASA_AAA, frozenset(RecordFamily), "record-dependent", "record-dependent", "manual_until_approved"),
    Provider.PREQB: ProviderCapabilities(Provider.PREQB, frozenset(RecordFamily), "archive-dependent", "public", "manual_until_approved"),
}
