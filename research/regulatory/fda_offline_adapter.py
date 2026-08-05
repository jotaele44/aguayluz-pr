"""Disabled, offline-only FDA adapter research vertical slice.

This module has no network client, persistence, scheduler registration, entity
promotion, or compliance inference. It accepts only an injected fixture client.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_RECORD_FAMILY = {
    "establishment": "entity",
    "registration": "permit",
    "device_listing": "permit",
    "inspection": "inspection",
    "recall": "enforcement",
    "warning_letter": "enforcement",
}


@dataclass(frozen=True, slots=True)
class OfflineLocator:
    provider_record_id: str
    record_type: str
    index: int


@dataclass(frozen=True, slots=True)
class OfflineCheckpoint:
    cursor: int
    fixture_revision: str


class OfflineFDAClient:
    """Immutable fixture-backed client; it cannot perform network I/O."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._revision = str(fixture["fixture_revision"])
        self._records = tuple(dict(record) for record in fixture["records"])

    @property
    def revision(self) -> str:
        return self._revision

    def locators(self, start: int = 0) -> tuple[OfflineLocator, ...]:
        return tuple(
            OfflineLocator(str(record["provider_record_id"]), str(record["record_type"]), index)
            for index, record in enumerate(self._records[start:], start=start)
        )

    def read(self, locator: OfflineLocator) -> bytes:
        record = self._records[locator.index]
        if record["provider_record_id"] != locator.provider_record_id:
            raise ValueError("fixture locator mismatch")
        return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


class FDAOfflineAdapter:
    """Research adapter that remains disabled unless explicitly constructed enabled."""

    def __init__(self, client: OfflineFDAClient, *, enabled: bool = False) -> None:
        self._client = client
        self._enabled = enabled
        self._cursor = 0

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise RuntimeError("FDA offline adapter is disabled")

    def discover(self, checkpoint: OfflineCheckpoint | None = None) -> tuple[tuple[OfflineLocator, ...], OfflineCheckpoint]:
        self._require_enabled()
        start = checkpoint.cursor if checkpoint else 0
        if checkpoint and checkpoint.fixture_revision != self._client.revision:
            raise ValueError("fixture revision mismatch")
        locators = self._client.locators(start)
        self._cursor = start + len(locators)
        return locators, self.checkpoint()

    def fetch(self, locator: OfflineLocator) -> tuple[bytes, dict[str, Any]]:
        self._require_enabled()
        raw = self._client.read(locator)
        digest = hashlib.sha256(raw).hexdigest()
        receipt = {
            "receipt_id": f"AYL_REGRCPT_FDA_{digest[:24]}",
            "provider": "FDA",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "request_locator": f"fixture://fda/{self._client.revision}/{locator.index}",
            "sha256": digest,
            "byte_count": len(raw),
            "media_type": "application/json",
            "retrieval_status": "success",
            "redactions": [],
        }
        return raw, receipt

    def normalize(self, raw: bytes, receipt: dict[str, Any], *, version: str = "fda-offline/v0.6") -> dict[str, Any]:
        self._require_enabled()
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            raise ValueError("receipt hash mismatch")
        record = json.loads(raw)
        record_type = str(record["record_type"])
        if record_type not in _RECORD_FAMILY:
            raise ValueError(f"unsupported FDA record type: {record_type}")
        freshness = self._freshness(record)
        material = b"\0".join(
            [b"FDA", str(record["provider_record_id"]).encode(), raw, version.encode()]
        )
        identifiers = []
        for key in (
            "fei",
            "registration_number",
            "listing_number",
            "inspection_id",
            "recall_number",
            "warning_letter_id",
        ):
            if value := record.get(key):
                identifiers.append({"scheme": key, "value": str(value), "issuer": "FDA"})
        observation = {
            "observation_id": f"AYL_REGOBS_FDA_{hashlib.sha256(material).hexdigest()[:24]}",
            "record_family": _RECORD_FAMILY[record_type],
            "provider": "FDA",
            "provider_record_id": str(record["provider_record_id"]),
            "observed_at": str(record["observed_at"]),
            "retrieved_at": receipt["retrieved_at"],
            "source_receipt_id": receipt["receipt_id"],
            "normalization_version": version,
            "evidence_tier": "T1",
            "freshness_state": freshness,
            "source_asserted_status": str(record.get("status", "unknown")),
            "identifiers": identifiers,
            "payload": {key: value for key, value in record.items() if key not in {"fei"}},
        }
        if valid_until := record.get("valid_until"):
            observation["valid_until"] = valid_until
        if supersedes := record.get("supersedes_provider_record_id"):
            observation["supersedes_observation_id"] = f"AYL_REGOBS_FDA_SOURCE_{supersedes}"
        return observation

    def checkpoint(self) -> OfflineCheckpoint:
        return OfflineCheckpoint(self._cursor, self._client.revision)

    @staticmethod
    def _freshness(record: dict[str, Any]) -> str:
        status = str(record.get("status", "unknown")).lower()
        if status in {"historical", "terminated", "closed", "retracted"}:
            return "historical"
        valid_until = record.get("valid_until")
        if valid_until and valid_until < "2026-08-04T00:00:00Z":
            return "stale"
        if status in {"active", "registered", "listed"}:
            return "current"
        return "unknown"
