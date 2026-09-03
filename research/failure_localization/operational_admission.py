"""Admission and append-only receipt helpers for operational adapters."""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from .contracts import digest, parse_timestamp, stable_id, unique
from .operational_adapter_contracts import (
    AUTHORITY_STATES,
    BUNDLE_SCHEMA,
    DISCLOSURE_STATES,
    EVIDENCE_TIERS,
    FORBIDDEN_ACTIVE_KEYS,
    FRESHNESS_STATES,
    GRAPH_KINDS,
    INPUT_KINDS,
    INPUT_SCHEMA,
    QUALITY_STATES,
    RECEIPT_SCHEMA,
    REVIEW_STATES,
    Admission,
    OperationalAdapterError,
    _is_current,
    _payload_hash,
    _required_text,
    _walk_keys,
)


class OperationalAdmissionMixin:
    def _validate_bundle_envelope(self, bundle: dict[str, Any]) -> None:
        if bundle.get("schema_version") != BUNDLE_SCHEMA:
            raise OperationalAdapterError("unsupported_operational_bundle_schema")
        _required_text(bundle, "bundle_id")
        if bundle.get("mode") != "offline_replay":
            raise OperationalAdapterError("operational_bundle_must_be_offline_replay")
        if not isinstance(bundle.get("records"), list) or not bundle["records"]:
            raise OperationalAdapterError("operational_bundle_records_required")
        input_ids = [str(item.get("input_id") or "") for item in bundle["records"]]
        if len(input_ids) != len(set(input_ids)):
            raise OperationalAdapterError("duplicate_operational_input_id")
        forbidden = sorted(set(_walk_keys(bundle)).intersection(FORBIDDEN_ACTIVE_KEYS))
        if forbidden:
            raise OperationalAdapterError(
                f"active_or_credential_key_forbidden:{','.join(forbidden)}"
            )
        if bundle.get("synthetic_fixture") and not self.synthetic_fixture_mode:
            raise OperationalAdapterError("synthetic_fixture_mode_required")
        if bundle.get("synthetic_fixture"):
            for record in bundle["records"]:
                if record.get("authority") != "synthetic_fixture":
                    raise OperationalAdapterError(
                        "synthetic_bundle_requires_synthetic_fixture_authority"
                    )
                if record.get("evidence_tier") != "T4":
                    raise OperationalAdapterError("synthetic_bundle_requires_t4")

    def _admit_input(self, raw: dict[str, Any], as_of: datetime) -> Admission:
        try:
            record = self._validate_input(raw, as_of)
        except OperationalAdapterError as exc:
            return Admission("rejected", (str(exc),), None)

        reasons: list[str] = []
        if record["review_status"] == "rejected":
            reasons.append("review_status_rejected")
        if record["quality"] == "invalid":
            reasons.append("quality_invalid")
        if record["freshness"] == "future" or parse_timestamp(record["observed_at"]) > as_of:
            reasons.append("future_input")
        if record["input_kind"] in GRAPH_KINDS and not _is_current(record, as_of):
            reasons.append("graph_input_not_current")
        if reasons:
            return Admission("quarantined", tuple(sorted(reasons)), None)

        status = "admitted"
        if record["freshness"] in {"stale", "unknown"}:
            status = "admitted_noncurrent_observation"
        return Admission(status, (), record)

    def _validate_input(self, raw: dict[str, Any], as_of: datetime) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise OperationalAdapterError("operational_input_must_be_object")
        record = copy.deepcopy(raw)
        if record.get("schema_version") != INPUT_SCHEMA:
            raise OperationalAdapterError("unsupported_operational_input_schema")
        for key in (
            "input_id",
            "input_kind",
            "source_id",
            "observed_at",
            "received_at",
            "sha256",
            "evidence_tier",
            "freshness",
            "quality",
            "disclosure",
            "authority",
            "review_status",
        ):
            _required_text(record, key)
        if record["input_kind"] not in INPUT_KINDS:
            raise OperationalAdapterError("unsupported_operational_input_kind")
        if record["evidence_tier"] not in EVIDENCE_TIERS:
            raise OperationalAdapterError("invalid_operational_evidence_tier")
        if record["freshness"] not in FRESHNESS_STATES:
            raise OperationalAdapterError("invalid_operational_freshness")
        if record["quality"] not in QUALITY_STATES:
            raise OperationalAdapterError("invalid_operational_quality")
        if record["disclosure"] not in DISCLOSURE_STATES:
            raise OperationalAdapterError("invalid_operational_disclosure")
        if record["authority"] not in AUTHORITY_STATES:
            raise OperationalAdapterError("invalid_operational_authority")
        if record["review_status"] not in REVIEW_STATES:
            raise OperationalAdapterError("invalid_operational_review_status")
        if not isinstance(record.get("payload"), dict):
            raise OperationalAdapterError("operational_input_payload_required")
        if record["sha256"] != _payload_hash(record["payload"]):
            raise OperationalAdapterError("operational_input_sha256_mismatch")

        try:
            observed = parse_timestamp(record["observed_at"])
            received = parse_timestamp(record["received_at"])
        except ValueError as exc:
            raise OperationalAdapterError(f"invalid_operational_timestamp:{exc}") from exc
        if received < observed:
            raise OperationalAdapterError("received_at_precedes_observed_at")
        if record["freshness"] == "future" and observed <= as_of:
            raise OperationalAdapterError("future_freshness_contradiction")
        if record["authority"] == "synthetic_fixture":
            if not self.synthetic_fixture_mode:
                raise OperationalAdapterError("synthetic_fixture_mode_required")
            if record["evidence_tier"] != "T4":
                raise OperationalAdapterError("synthetic_fixture_must_be_t4")
        return record

    def _receipt(
        self,
        source: dict[str, Any],
        admission: Admission,
        bundle_id: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        input_id = str(source.get("input_id") or "missing")
        return {
            "schema_version": RECEIPT_SCHEMA,
            "adapter_receipt_id": stable_id(
                "AYL_FLREC",
                {
                    "bundle_id": bundle_id,
                    "input_id": input_id,
                    "status": admission.status,
                    "reasons": admission.reasons,
                },
            ),
            "bundle_id": bundle_id,
            "input_id": input_id,
            "input_kind": source.get("input_kind"),
            "source_id": source.get("source_id"),
            "observed_at": source.get("observed_at"),
            "received_at": source.get("received_at"),
            "payload_sha256": source.get("sha256"),
            "as_of": as_of.isoformat(),
            "admission_status": admission.status,
            "reason_codes": list(admission.reasons),
            "append_only": True,
            "offline_only": True,
            "control_action_authorized": False,
        }

    def _append_blocker_receipts(
        self,
        blockers: list[str],
        *,
        bundle_id: str,
        as_of: datetime,
        idempotency_key: str,
    ) -> list[dict[str, Any]]:
        output = []
        for index, blocker in enumerate(unique(blockers), 1):
            receipt = {
                "schema_version": RECEIPT_SCHEMA,
                "adapter_receipt_id": stable_id(
                    "AYL_FLREC",
                    {"bundle_id": bundle_id, "blocker": blocker},
                ),
                "bundle_id": bundle_id,
                "input_id": f"bundle-blocker-{index}",
                "input_kind": "bundle_blocker",
                "source_id": "failure-localization-operational-adapter",
                "observed_at": as_of.isoformat(),
                "received_at": as_of.isoformat(),
                "payload_sha256": digest({"blocker": blocker}),
                "as_of": as_of.isoformat(),
                "admission_status": "quarantined",
                "reason_codes": [blocker],
                "append_only": True,
                "offline_only": True,
                "control_action_authorized": False,
            }
            output.append(
                self.control_plane.store.append_idempotent(
                    "operational_adapter_receipts",
                    receipt,
                    idempotency_key=f"{idempotency_key}:blocker:{index}:{blocker}",
                )
            )
        return output
