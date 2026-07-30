"""Append-only water-disruption intake, validation, and incident lifecycle."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "reported": {"acknowledged", "retracted", "cancelled"},
    "acknowledged": {"confirmed", "disputed", "retracted", "cancelled"},
    "confirmed": {"repair_planned", "repair_in_progress", "partial_restoration", "restored", "disputed", "retracted"},
    "repair_planned": {"repair_in_progress", "partial_restoration", "restored", "disputed", "retracted"},
    "repair_in_progress": {"partial_restoration", "restored", "disputed", "retracted"},
    "partial_restoration": {"repair_in_progress", "restored", "disputed", "retracted"},
    "restored": {"closed", "repair_in_progress", "retracted"},
    "closed": {"repair_in_progress", "retracted"},
    "disputed": {"acknowledged", "confirmed", "retracted", "cancelled"},
    "retracted": set(),
    "cancelled": set(),
}
TRUTH_STRENGTH = {"unverified": 1, "corroborated": 2, "confirmed": 3}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-{digest(value)[:length]}"


class AppendOnlyJsonl:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, record: dict[str, Any]) -> dict[str, Any]:
        persisted = dict(record)
        persisted.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        persisted.setdefault("record_hash", digest(persisted))
        with (self.root / f"{stream}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(persisted) + "\n")
        return persisted

    def read(self, stream: str) -> list[dict[str, Any]]:
        path = self.root / f"{stream}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def latest(self, stream: str, key: str, value: str) -> dict[str, Any] | None:
        return next((row for row in reversed(self.read(stream)) if str(row.get(key)) == value), None)


class WaterIncidentService:
    def __init__(self, root: Path) -> None:
        self.store = AppendOnlyJsonl(root)
        self.shadow_mode = True
        self.notifications_enabled = False
        self.production_promotion_enabled = False

    def intake(self, envelope: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        payload = envelope.get("payload", envelope)
        if payload.get("schema_version") != "centinelas.water-candidate/v0.1":
            raise ValueError("unsupported_candidate_schema")
        if payload.get("truth_state") != "candidate":
            raise ValueError("producer_truth_state_violation")
        candidate_id = str(payload.get("candidate_id") or "")
        if not candidate_id or not payload.get("evidence_ids"):
            raise ValueError("broken_candidate_provenance")
        envelope_hash = digest(payload)
        prior = self.store.latest("intake_receipts", "idempotency_key", idempotency_key)
        if prior:
            if prior["envelope_hash"] != envelope_hash:
                raise ValueError("idempotency_payload_conflict")
            return {**prior, "replayed": True}
        existing = self.store.latest("intake_receipts", "candidate_id", candidate_id)
        if existing and existing["envelope_hash"] != envelope_hash:
            raise ValueError("candidate_payload_changed")
        return self.store.append("intake_receipts", {
            "receipt_id": stable_id("WDR", {"candidate_id": candidate_id, "envelope_hash": envelope_hash}),
            "candidate_id": candidate_id,
            "idempotency_key": idempotency_key,
            "envelope_hash": envelope_hash,
            "schema_decision": "accepted",
            "queue_state": "validation_pending",
            "replayed": False,
            "shadow_mode": True,
        })

    @staticmethod
    def validation_policy(candidate: dict[str, Any], *, authoritative_scope_match: bool = False, independent_source_count: int = 0, reviewer_approved: bool = False, public_infrastructure: bool = True, location_resolved: bool = True, stale: bool = False) -> dict[str, Any]:
        blockers = []
        if not public_infrastructure:
            blockers.append("not_public_infrastructure")
        if not location_resolved:
            blockers.append("location_unresolved")
        if stale:
            blockers.append("stale_report")
        confirmed = not blockers and (authoritative_scope_match or (independent_source_count >= 2 and reviewer_approved))
        if confirmed:
            decision = "confirmed"
        elif blockers:
            decision = "rejected" if "not_public_infrastructure" in blockers else "unverified"
        elif independent_source_count >= 2:
            decision = "corroborated"
        else:
            decision = "unverified"
        return {
            "decision": decision,
            "blockers": blockers,
            "authoritative_scope_match": authoritative_scope_match,
            "independent_source_count": independent_source_count,
            "reviewer_approved": reviewer_approved,
            "confidence_ignored_for_confirmation": True,
        }

    def validate(self, candidate: dict[str, Any], decision: dict[str, Any], reviewer: str, idempotency_key: str) -> dict[str, Any]:
        candidate_id = candidate["candidate_id"]
        validation_hash = digest({"candidate": candidate, "decision": decision, "reviewer": reviewer})
        prior = self.store.latest("validation_events", "idempotency_key", idempotency_key)
        if prior:
            if prior.get("validation_hash") != validation_hash:
                raise ValueError("validation_idempotency_conflict")
            return prior
        event = {
            "validation_id": stable_id("WDV", {"candidate_id": candidate_id, "idempotency_key": idempotency_key}),
            "candidate_id": candidate_id,
            "idempotency_key": idempotency_key,
            "validation_hash": validation_hash,
            "reviewer": reviewer,
            **decision,
        }
        persisted = self.store.append("validation_events", event)
        if decision["decision"] in TRUTH_STRENGTH:
            self.resolve_incident(candidate, decision, persisted["validation_id"])
        return persisted

    def resolve_incident(self, candidate: dict[str, Any], decision: dict[str, Any], validation_id: str | None = None) -> dict[str, Any]:
        incident_id = stable_id("WDI", candidate["dedup_key"])
        existing = self.store.latest("incidents", "incident_id", incident_id)
        if not existing:
            truth_state = decision["decision"]
            lifecycle_state = "confirmed" if truth_state == "confirmed" else "reported"
            existing = self.store.append("incidents", {
                "schema_version": "aguayluz.water-incident/v0.1",
                "incident_id": incident_id,
                "dedup_key": candidate["dedup_key"],
                "event_type": candidate["event_type"],
                "municipalities": candidate.get("municipalities", []),
                "asset_hint": candidate.get("asset_hint"),
                "truth_state": truth_state,
                "lifecycle_state": lifecycle_state,
                "candidate_ids": [candidate["candidate_id"]],
                "evidence_ids": list(candidate["evidence_ids"]),
                "shadow_mode": True,
                "notifications_enabled": False,
                "production_export_eligible": False,
            })
            self.store.append("incident_truth_events", {
                "truth_event_id": stable_id("WDT", {"incident_id": incident_id, "truth_state": truth_state, "validation_id": validation_id}),
                "incident_id": incident_id,
                "from_truth_state": None,
                "to_truth_state": truth_state,
                "validation_id": validation_id,
                "reason": "incident_created",
            })
            self.store.append("lifecycle_events", {"incident_id": incident_id, "from_state": None, "to_state": lifecycle_state, "reason": "incident_created"})
            return existing
        self._reconcile_truth(existing, decision["decision"], validation_id)
        return self.current_incident(incident_id)

    def _reconcile_truth(self, incident: dict[str, Any], proposed: str, validation_id: str | None) -> None:
        current = self.current_incident(incident["incident_id"])
        current_truth = current["truth_state"]
        if TRUTH_STRENGTH[proposed] <= TRUTH_STRENGTH[current_truth]:
            return
        event_key = {"incident_id": incident["incident_id"], "to": proposed, "validation_id": validation_id}
        event_id = stable_id("WDT", event_key)
        if self.store.latest("incident_truth_events", "truth_event_id", event_id):
            return
        self.store.append("incident_truth_events", {
            "truth_event_id": event_id,
            "incident_id": incident["incident_id"],
            "from_truth_state": current_truth,
            "to_truth_state": proposed,
            "validation_id": validation_id,
            "reason": "stronger_validation",
        })
        if proposed == "confirmed" and current["lifecycle_state"] in {"reported", "acknowledged", "disputed"}:
            self.store.append("lifecycle_events", {
                "event_id": stable_id("WDL", {"incident_id": incident["incident_id"], "validation_id": validation_id, "to": "confirmed"}),
                "incident_id": incident["incident_id"],
                "from_state": current["lifecycle_state"],
                "to_state": "confirmed",
                "reason": "validation_promotion",
                "validation_id": validation_id,
            })

    def current_incident(self, incident_id: str) -> dict[str, Any]:
        base = self.store.latest("incidents", "incident_id", incident_id)
        if not base:
            raise KeyError(incident_id)
        current = dict(base)
        truth_events = [row for row in self.store.read("incident_truth_events") if row["incident_id"] == incident_id]
        lifecycle_events = [row for row in self.store.read("lifecycle_events") if row["incident_id"] == incident_id]
        if truth_events:
            current["truth_state"] = truth_events[-1]["to_truth_state"]
        if lifecycle_events:
            current["lifecycle_state"] = lifecycle_events[-1]["to_state"]
        current["truth_events"] = truth_events
        current["lifecycle_events"] = lifecycle_events
        return current

    def transition(self, incident_id: str, to_state: str, reason: str, idempotency_key: str) -> dict[str, Any]:
        prior = self.store.latest("lifecycle_events", "idempotency_key", idempotency_key)
        if prior:
            return prior
        current = self.current_incident(incident_id)["lifecycle_state"]
        if to_state not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid_transition:{current}:{to_state}")
        return self.store.append("lifecycle_events", {
            "event_id": stable_id("WDL", {"incident_id": incident_id, "idempotency_key": idempotency_key}),
            "incident_id": incident_id,
            "idempotency_key": idempotency_key,
            "from_state": current,
            "to_state": to_state,
            "reason": reason,
        })

    def merge(self, target_id: str, source_ids: list[str], reason: str, idempotency_key: str) -> dict[str, Any]:
        prior = self.store.latest("merge_split_events", "idempotency_key", idempotency_key)
        if prior:
            return prior
        for incident_id in [target_id, *source_ids]:
            self.current_incident(incident_id)
        return self.store.append("merge_split_events", {"operation_id": stable_id("WDM", {"target": target_id, "sources": sorted(source_ids), "key": idempotency_key}), "operation": "merge", "target_incident_id": target_id, "source_incident_ids": sorted(source_ids), "reason": reason, "idempotency_key": idempotency_key})

    def split(self, source_id: str, child_dedup_keys: list[str], reason: str, idempotency_key: str) -> dict[str, Any]:
        self.current_incident(source_id)
        prior = self.store.latest("merge_split_events", "idempotency_key", idempotency_key)
        if prior:
            return prior
        child_ids = [stable_id("WDI", key) for key in sorted(child_dedup_keys)]
        return self.store.append("merge_split_events", {"operation_id": stable_id("WDS", {"source": source_id, "children": child_ids, "key": idempotency_key}), "operation": "split", "source_incident_id": source_id, "child_incident_ids": child_ids, "reason": reason, "idempotency_key": idempotency_key})

    def retract(self, candidate_id: str, reason: str, idempotency_key: str) -> dict[str, Any]:
        prior = self.store.latest("retraction_events", "idempotency_key", idempotency_key)
        if prior:
            return prior
        affected = [row["incident_id"] for row in self.store.read("incidents") if candidate_id in row.get("candidate_ids", [])]
        event = self.store.append("retraction_events", {"retraction_id": stable_id("WDRT", {"candidate_id": candidate_id, "key": idempotency_key}), "candidate_id": candidate_id, "affected_incident_ids": affected, "reason": reason, "idempotency_key": idempotency_key, "destructive": False, "correction_notifications_queued": False})
        for incident_id in affected:
            current = self.current_incident(incident_id)
            self.store.append("incident_truth_events", {
                "truth_event_id": stable_id("WDT", {"incident_id": incident_id, "to": "retracted", "key": idempotency_key}),
                "incident_id": incident_id,
                "from_truth_state": current["truth_state"],
                "to_truth_state": "retracted",
                "retraction_id": event["retraction_id"],
                "reason": reason,
            })
            if "retracted" in ALLOWED_TRANSITIONS.get(current["lifecycle_state"], set()):
                self.transition(incident_id, "retracted", reason, f"{idempotency_key}:{incident_id}")
        return event
