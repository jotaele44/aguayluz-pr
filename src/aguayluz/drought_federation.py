"""Deterministic drought federation contracts.

This module is intentionally offline and side-effect free.  It separates canonical
hydrologic observations, reported impacts, restrictions, outlooks, and synthesis
source documents so a narrative report cannot silently overwrite instrument data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

RecordKind = Literal[
    "classification_observation",
    "hydrologic_indicator",
    "impact_event",
    "water_restriction",
    "outlook",
    "source_document",
]
EvidenceTier = Literal["T1", "T2", "T3", "T4"]
ValueQualifier = Literal["exact", "approximate", "lower_bound", "upper_bound", "range"]


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_sha256(value: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 over canonical UTF-8 JSON."""

    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def deterministic_record_id(kind: RecordKind, source_id: str, source_record_id: str) -> str:
    """Build a stable record identifier without collapsing distinct source claims."""

    material = f"{kind}\x1f{source_id.strip()}\x1f{source_record_id.strip()}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"AYL_DROUGHT_{kind.upper()}_{digest}"


@dataclass(frozen=True)
class DroughtRecord:
    """Versioned envelope for one drought-domain record."""

    kind: RecordKind
    source_id: str
    source_record_id: str
    observed_at: str | None
    issued_at: str
    retrieved_at: str
    evidence_tier: EvidenceTier
    payload: Mapping[str, Any]
    quality: Mapping[str, Any]
    uncertainty: Mapping[str, Any]
    lineage: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        record = {
            "schema_version": "aguayluz.drought-record/v0.1",
            "record_id": deterministic_record_id(
                self.kind, self.source_id, self.source_record_id
            ),
            "kind": self.kind,
            "source_id": self.source_id,
            "source_record_id": self.source_record_id,
            "observed_at": self.observed_at,
            "issued_at": self.issued_at,
            "retrieved_at": self.retrieved_at,
            "evidence_tier": self.evidence_tier,
            "payload": dict(self.payload),
            "quality": dict(self.quality),
            "uncertainty": dict(self.uncertainty),
            "lineage": dict(self.lineage),
        }
        record["content_sha256"] = content_sha256(record)
        return record


def normalize_reported_value(
    *,
    value: float | int | None = None,
    unit: str | None = None,
    qualifier: ValueQualifier,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
    raw_text: str,
) -> dict[str, Any]:
    """Preserve approximate/range semantics instead of manufacturing precision."""

    if qualifier == "range":
        if minimum is None or maximum is None or minimum > maximum:
            raise ValueError("range values require ordered minimum and maximum")
        if value is not None:
            raise ValueError("range values must not provide an exact value")
    elif value is None:
        raise ValueError(f"{qualifier} values require value")

    return {
        "value": value,
        "minimum": minimum,
        "maximum": maximum,
        "unit": unit,
        "qualifier": qualifier,
        "raw_text": raw_text,
    }


def classify_date_text(raw_text: str, *, corrected_date: str | None = None) -> dict[str, Any]:
    """Represent a malformed source date without silently repairing it."""

    result: dict[str, Any] = {
        "raw_text": raw_text,
        "status": "valid",
        "normalized_date": raw_text,
        "correction_authority": None,
    }
    try:
        datetime.fromisoformat(raw_text)
    except ValueError:
        result.update(
            {
                "status": "source_typo_unresolved" if corrected_date is None else "corrected",
                "normalized_date": corrected_date,
                "correction_authority": None,
            }
        )
    return result


def build_nidis_source_document(
    *, source_sha256: str, retrieved_at: str, claim_ids: list[str]
) -> DroughtRecord:
    """Create the bounded NIDIS synthesis document record."""

    datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    return DroughtRecord(
        kind="source_document",
        source_id="NOAA_NIDIS",
        source_record_id="drought-update-pr-usvi-2026-07-23",
        observed_at=None,
        issued_at="2026-07-23T00:00:00-04:00",
        retrieved_at=retrieved_at,
        evidence_tier="T2",
        payload={
            "title": "Drought Update for Puerto Rico and the U.S. Virgin Islands",
            "report_date": "2026-07-23",
            "source_sha256": source_sha256,
            "claim_ids": sorted(set(claim_ids)),
            "canonical_observation_authority": False,
        },
        quality={"review_status": "accepted_synthesis", "freshness": "historical_snapshot"},
        uncertainty={"narrative_claims_require_source_resolution": True},
        lineage={
            "source_url": (
                "https://www.drought.gov/drought-status-updates/"
                "drought-update-puerto-rico-and-us-virgin-islands-2026-07-23"
            ),
            "retrieved_by": "manual_bounded_ingest",
        },
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
