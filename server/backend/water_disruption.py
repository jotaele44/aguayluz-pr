"""Append-only water-disruption intake, validation, and incident lifecycle."""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
ALLOWED_TRANSITIONS: dict[str, set[str]] = {'reported': {'acknowledged', 'retracted', 'cancelled'}, 'acknowledged': {'confirmed', 'disputed', 'retracted', 'cancelled'}, 'confirmed': {'repair_planned', 'repair_in_progress', 'partial_restoration', 'restored', 'disputed', 'retracted'}, 'repair_planned': {'repair_in_progress', 'partial_restoration', 'restored', 'disputed', 'retracted'}, 'repair_in_progress': {'partial_restoration', 'restored', 'disputed', 'retracted'}, 'partial_restoration': {'repair_in_progress', 'restored', 'disputed', 'retracted'}, 'restored': {'closed', 'repair_in_progress', 'retracted'}, 'closed': {'repair_in_progress', 'retracted'}, 'disputed': {'acknowledged', 'confirmed', 'retracted', 'cancelled'}, 'retracted': set(), 'cancelled': set()}
TRUTH_STRENGTH = {'unverified': 1, 'corroborated': 2, 'confirmed': 3}

def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value: Any) -> str:
    import hashlib
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()

def stable_id(prefix: str, value: Any, length: int=24) -> str:
    return f'{prefix}-{digest(value)[:length]}'
_REPO = Path(__file__).resolve().parents[2]
_LAGUNA_COVERAGE_PATH = _REPO / "config" / "laguna_cartagena_monitoring_coverage.v0.2.json"
_LAGUNA_SCHEMA_VERSION = "aguayluz.laguna-cartagena-observation/v0.2"
_LAGUNA_DIRECT_METRICS = {
    "lagoon_stage", "outflow_discharge", "groundwater_level", "specific_conductance",
    "water_temperature", "dissolved_oxygen", "ph", "turbidity", "nitrate",
    "ammonia", "phosphorus", "fecal_indicator",
}
_LAGUNA_OPERATION_METRICS = {
    "canal_release", "treatment_withdrawal", "agricultural_turnout", "gate_position",
    "known_leak_flow", "terminal_flow",
}
_LAGUNA_ALLOWED_METRICS = _LAGUNA_DIRECT_METRICS | _LAGUNA_OPERATION_METRICS | {
    "precipitation", "soil_moisture",
}
_LAGUNA_DERIVED_FIELDS = {
    "current_condition_eligible", "eligibility_reasons", "stale", "claim_scope",
    "evaluated_at",
}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _load_laguna_config() -> dict[str, Any]:
    try:
        return json.loads(_LAGUNA_COVERAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _freshness_limit(metric: str) -> timedelta:
    if metric in _LAGUNA_OPERATION_METRICS:
        return timedelta(hours=36)
    if metric in {"precipitation", "soil_moisture"}:
        return timedelta(days=7)
    if metric in {"specific_conductance", "dissolved_oxygen", "ph", "turbidity", "nitrate", "ammonia", "phosphorus", "fecal_indicator"}:
        return timedelta(days=45)
    return timedelta(hours=72)


def _validate_laguna_observation(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != _LAGUNA_SCHEMA_VERSION:
        raise ValueError("unsupported_laguna_observation_schema")
    if _LAGUNA_DERIVED_FIELDS & payload.keys():
        raise ValueError("derived_current_condition_fields_forbidden")
    required = {
        "observation_id", "observation_window_id", "observed_at", "source_id",
        "source_record_id", "source_hash", "provider", "location_id", "location_name",
        "metric", "value", "unit", "evidence_tier", "direct_or_proxy",
        "hydrologic_representativeness", "historical_baseline", "qa_status",
        "evidence_ids", "shadow_mode",
    }
    missing = sorted(field for field in required if payload.get(field) in (None, "", []))
    if missing:
        raise ValueError(f"laguna_observation_missing:{','.join(missing)}")
    if payload["metric"] not in _LAGUNA_ALLOWED_METRICS:
        raise ValueError("laguna_observation_unknown_metric")
    if _parse_datetime(payload["observed_at"]) is None:
        raise ValueError("laguna_observation_invalid_time")
    if payload.get("valid_until") and _parse_datetime(payload["valid_until"]) is None:
        raise ValueError("laguna_observation_invalid_valid_until")
    if payload.get("evidence_tier") not in {"T1", "T2", "T3", "T4"}:
        raise ValueError("laguna_observation_invalid_evidence_tier")
    if payload.get("direct_or_proxy") not in {"direct", "proxy", "context"}:
        raise ValueError("laguna_observation_invalid_directness")
    if payload.get("hydrologic_representativeness") not in {"direct", "high", "medium", "low", "none"}:
        raise ValueError("laguna_observation_invalid_representativeness")
    if payload.get("qa_status") not in {"accepted", "provisional", "needs_review", "rejected"}:
        raise ValueError("laguna_observation_invalid_qa_status")
    if payload.get("shadow_mode") is not True:
        raise ValueError("laguna_observation_shadow_mode_required")
    source_hash = str(payload.get("source_hash", ""))
    if len(source_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in source_hash):
        raise ValueError("laguna_observation_invalid_source_hash")


class _LagunaCartagenaControlPlane:
    def __init__(self, store: Any) -> None:
        self.store = store

    def intake(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        _validate_laguna_observation(payload)
        envelope_hash = digest(payload)
        prior = self.store.latest("laguna_cartagena_intake_receipts", "idempotency_key", idempotency_key)
        if prior:
            if prior["envelope_hash"] != envelope_hash:
                raise ValueError("idempotency_payload_conflict")
            return {**prior, "replayed": True}
        observation_id = str(payload["observation_id"])
        existing = self.store.latest("laguna_cartagena_observations", "observation_id", observation_id)
        if existing and existing.get("source_payload_hash") != envelope_hash:
            raise ValueError("laguna_observation_payload_changed")
        evaluated = self.evaluate(payload)
        if not existing:
            self.store.append("laguna_cartagena_observations", evaluated)
        return self.store.append("laguna_cartagena_intake_receipts", {
            "receipt_id": stable_id("LCR", {"observation_id": observation_id, "envelope_hash": envelope_hash}),
            "observation_id": observation_id, "idempotency_key": idempotency_key,
            "envelope_hash": envelope_hash, "schema_decision": "accepted",
            "queue_state": "materialized_shadow", "replayed": False,
            "current_condition_eligible": evaluated["current_condition_eligible"],
            "eligibility_reasons": evaluated["eligibility_reasons"], "shadow_mode": True,
            "notifications_enabled": False, "production_promotion_enabled": False,
        })

    def evaluate(self, payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        metric = str(payload.get("metric", ""))
        observed = _parse_datetime(payload.get("observed_at"))
        reasons: list[str] = []
        if observed is None:
            reasons.append("invalid_observation_time")
        elif observed > now + timedelta(hours=1):
            reasons.append("future_observation")
        elif now - observed > _freshness_limit(metric):
            reasons.append("stale_observation")
        valid_until = _parse_datetime(payload.get("valid_until"))
        if valid_until and valid_until < now:
            reasons.append("validity_window_expired")
        if payload.get("historical_baseline"):
            reasons.append("historical_baseline_not_current")
        if str(payload.get("location_id", "")).upper() == "GUIL":
            reasons.append("guil_not_lajas_groundwater_substitute")
        if payload.get("qa_status") in {"needs_review", "rejected"}:
            reasons.append(f"qa_{payload['qa_status']}")
        direct = metric in _LAGUNA_DIRECT_METRICS
        if direct and payload.get("direct_or_proxy") != "direct":
            reasons.append("direct_target_metric_requires_direct_measurement")
        if direct and payload.get("hydrologic_representativeness") != "direct":
            reasons.append("direct_target_metric_requires_direct_representativeness")
        distance = payload.get("distance_from_target_km")
        if direct and isinstance(distance, (int, float)) and distance > 5:
            reasons.append("direct_target_metric_too_far_from_target")
        if metric in _LAGUNA_OPERATION_METRICS and (
            payload.get("direct_or_proxy") == "context"
            or payload.get("hydrologic_representativeness") in {"low", "none"}
        ):
            reasons.append("operational_record_not_hydrologically_representative")
        result = dict(payload)
        result.update({
            "source_payload_hash": digest(payload), "evaluated_at": now.isoformat(),
            "stale": bool({"stale_observation", "validity_window_expired", "historical_baseline_not_current"} & set(reasons)),
            "current_condition_eligible": not reasons,
            "eligibility_reasons": sorted(set(reasons)),
            "claim_scope": "laguna_direct" if direct else "canal_system_context" if metric in _LAGUNA_OPERATION_METRICS else "regional_context",
        })
        return result

    @staticmethod
    def _balance(current: list[dict[str, Any]], config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        required = config.get("synchronization_policy", {}).get("required_balance_metrics", [])
        operational = [row for row in current if row.get("metric") in set(required) | {"known_leak_flow"}]
        if not operational:
            return ({"status": "no_current_window", "window_id": None, "max_skew_hours": None, "missing_metrics": sorted(required)}, {"status": "not_computed", "reason": "no_current_synchronized_operational_window", "root_cause_claim": None})
        windows: dict[str, list[dict[str, Any]]] = {}
        for row in operational:
            windows.setdefault(str(row["observation_window_id"]), []).append(row)
        window_id, rows = max(windows.items(), key=lambda item: max(_parse_datetime(row["observed_at"]) for row in item[1]))
        latest = {str(row["metric"]): row for row in sorted(rows, key=lambda row: _parse_datetime(row["observed_at"]))}
        missing = sorted(metric for metric in required if metric not in latest)
        times = [_parse_datetime(row["observed_at"]) for row in latest.values()]
        skew = (max(times) - min(times)).total_seconds() / 3600 if len(times) > 1 else 0.0
        units = {row.get("unit") for row in latest.values()}
        allowed = float(config.get("synchronization_policy", {}).get("max_skew_hours", 24))
        status = "incomplete" if missing else "unsynchronized" if skew > allowed else "mixed_or_unsupported_units" if units != {"ft3/s"} else "synchronized"
        sync = {"status": status, "window_id": window_id, "max_skew_hours": round(skew, 3), "allowed_skew_hours": allowed, "missing_metrics": missing, "units": sorted(units)}
        if status != "synchronized":
            return sync, {"status": "not_computed", "reason": f"operational_window_{status}", "root_cause_claim": None}
        value = lambda metric: float(latest.get(metric, {}).get("value", 0))
        release, treatment, agriculture, terminal, known_leak = map(value, ["canal_release", "treatment_withdrawal", "agricultural_turnout", "terminal_flow", "known_leak_flow"])
        residual = release - treatment - agriculture - terminal - known_leak
        tolerance_fraction = float(config.get("synchronization_policy", {}).get("balance_tolerance_fraction", 0.15))
        tolerance = abs(release) * tolerance_fraction
        balance_status = "invalid_nonpositive_release" if release <= 0 else "contradictory_negative_residual" if residual < -tolerance else "unexplained_positive_residual" if residual > tolerance else "balanced_within_tolerance"
        return sync, {"status": balance_status, "window_id": window_id, "unit": "ft3/s", "canal_release": release, "treatment_withdrawal": treatment, "agricultural_turnout": agriculture, "terminal_flow": terminal, "known_leak_flow": known_leak, "explained_flow": treatment + agriculture + terminal + known_leak, "residual": residual, "residual_fraction": residual / release if release else None, "tolerance_fraction": tolerance_fraction, "root_cause_claim": None, "interpretation": "Residual is an accounting gap requiring field verification; it is not automatically classified as leakage."}

    def summary(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        config = _load_laguna_config()
        evaluated = [self.evaluate(row, now=now) for row in self.store.read("laguna_cartagena_observations")]
        current = [row for row in evaluated if row["current_condition_eligible"]]
        latest = {str(row["metric"]): row for row in sorted(current, key=lambda row: _parse_datetime(row["observed_at"]))}
        current = list(latest.values())
        direct_current = [row for row in current if row["claim_scope"] == "laguna_direct"]
        required_direct = config.get("required_current_metrics", [])
        missing_direct = sorted(metric for metric in required_direct if metric not in latest)
        coverage = []
        for item in config.get("coverage", []):
            record = dict(item)
            matching = [row for row in evaluated if str(row.get("location_id")) in set(record.get("location_ids", []))]
            matching_current = [row for row in matching if row["current_condition_eligible"]]
            record["ingested_record_count"] = len(matching)
            record["current_record_count"] = len(matching_current)
            record["coverage_state"] = "direct_current" if matching_current and record.get("direct_or_proxy") == "direct" else "current_context" if matching_current else "historical_only" if record.get("historical_baseline") else "gap"
            coverage.append(record)
        sync, balance = self._balance(current, config)
        hypotheses = []
        if sync["status"] == "unsynchronized":
            hypotheses.append({"cause": "measurement_asynchrony", "state": "supported", "confidence": 90, "basis": "Operational observations exceed the permitted synchronization window.", "requires_field_verification": True})
        if balance.get("status") not in {"not_computed", "invalid_nonpositive_release"}:
            release = float(balance.get("canal_release", 0))
            allocated = float(balance.get("treatment_withdrawal", 0)) + float(balance.get("agricultural_turnout", 0))
            if release > 0 and allocated / release >= 0.6:
                hypotheses.append({"cause": "allocated_withdrawal", "state": "supported", "confidence": 70, "basis": "Synchronized allocations account for at least 60% of release.", "requires_field_verification": False})
            if balance["status"] == "unexplained_positive_residual":
                hypotheses.append({"cause": "conveyance_loss", "state": "candidate", "confidence": 45, "basis": "Synchronized accounting leaves a positive residual above tolerance.", "requires_field_verification": True})
        rejected = [row for row in evaluated if not row["current_condition_eligible"]]
        counts: dict[str, int] = {}
        for row in rejected:
            for reason in row["eligibility_reasons"]:
                counts[reason] = counts.get(reason, 0) + 1
        contradictions = [{"type": reason, "record_count": count, "effect": "excluded_from_current_condition"} for reason, count in sorted(counts.items())]
        if balance.get("status") == "contradictory_negative_residual":
            contradictions.append({"type": "downstream_flows_exceed_upstream_release", "record_count": 1, "effect": "water_balance_rejected"})
        if not hypotheses or missing_direct:
            hypotheses.append({"cause": "unknown", "state": "active", "confidence": 100 if not current else 60, "basis": "Required direct measurements remain unavailable or incomplete.", "requires_field_verification": True})
        return {
            "schema_version": "aguayluz.laguna-cartagena-control-plane/v0.2",
            "generated_at": now.isoformat(), "target": config.get("target", {}),
            "shadow_mode": True, "alerts_enabled": False, "notifications_enabled": False,
            "automatic_control_actions_enabled": False, "coverage": coverage,
            "coverage_summary": {"source_count": len(coverage), "direct_current_source_count": sum(item["coverage_state"] == "direct_current" for item in coverage), "historical_only_source_count": sum(item["coverage_state"] == "historical_only" for item in coverage), "gap_source_count": sum(item["coverage_state"] == "gap" for item in coverage)},
            "current_condition": {"status": "observed" if direct_current else "unknown", "eligible_observation_count": len(current), "direct_observation_count": len(direct_current), "items": sorted(current, key=lambda row: str(row["metric"])), "missing_required_metrics": missing_direct},
            "rejected_current_observations": [{"observation_id": row.get("observation_id"), "metric": row.get("metric"), "location_id": row.get("location_id"), "eligibility_reasons": row["eligibility_reasons"]} for row in rejected],
            "synchronization": sync, "water_balance": balance,
            "historical_ranges": {"status": "registered_in_coverage_ledger", "items": []},
            "hypotheses": hypotheses, "contradictions": contradictions,
            "mitigation_priority": [{"priority": 1, "action": "Collect a synchronized one-day direct field baseline.", "blocked_by": missing_direct}, {"priority": 2, "action": "Obtain synchronized canal release, withdrawals, turnouts, gates, leaks, and terminal flow.", "blocked_by": sync.get("missing_metrics", [])}, {"priority": 3, "action": "Maintain explicit unknown state until direct and representative evidence is current.", "blocked_by": []}],
            "preserve": {"no_stale_to_current_promotion": True, "no_guil_to_lajas_groundwater_substitution": True, "no_unsynchronized_mass_balance_claims": True, "no_contamination_or_low_lake_alert_without_current_direct_measurement": True, "no_automatic_control_actions": True},
        }

class AppendOnlyJsonl:

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, record: dict[str, Any]) -> dict[str, Any]:
        persisted = dict(record)
        persisted.setdefault('recorded_at', datetime.now(timezone.utc).isoformat())
        persisted.setdefault('record_hash', digest(persisted))
        with (self.root / f'{stream}.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(canonical_json(persisted) + '\n')
        return persisted

    def read(self, stream: str) -> list[dict[str, Any]]:
        path = self.root / f'{stream}.jsonl'
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def latest(self, stream: str, key: str, value: str) -> dict[str, Any] | None:
        return next((row for row in reversed(self.read(stream)) if str(row.get(key)) == value), None)

class WaterIncidentService:

    def __init__(self, root: Path) -> None:
        self.store = AppendOnlyJsonl(root)
        self.shadow_mode = True
        self.notifications_enabled = False
        self.production_promotion_enabled = False
        self.laguna_cartagena = _LagunaCartagenaControlPlane(self.store)

    def intake(self, envelope: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        payload = envelope.get('payload', envelope)
        if payload.get('schema_version') == _LAGUNA_SCHEMA_VERSION:
            return self.laguna_cartagena.intake(payload, idempotency_key)
        if payload.get('schema_version') != 'centinelas.water-candidate/v0.1':
            raise ValueError('unsupported_candidate_schema')
        if payload.get('truth_state') != 'candidate':
            raise ValueError('producer_truth_state_violation')
        candidate_id = str(payload.get('candidate_id') or '')
        if not candidate_id or not payload.get('evidence_ids'):
            raise ValueError('broken_candidate_provenance')
        envelope_hash = digest(payload)
        prior = self.store.latest('intake_receipts', 'idempotency_key', idempotency_key)
        if prior:
            if prior['envelope_hash'] != envelope_hash:
                raise ValueError('idempotency_payload_conflict')
            return {**prior, 'replayed': True}
        existing = self.store.latest('intake_receipts', 'candidate_id', candidate_id)
        if existing and existing['envelope_hash'] != envelope_hash:
            raise ValueError('candidate_payload_changed')
        return self.store.append('intake_receipts', {'receipt_id': stable_id('WDR', {'candidate_id': candidate_id, 'envelope_hash': envelope_hash}), 'candidate_id': candidate_id, 'idempotency_key': idempotency_key, 'envelope_hash': envelope_hash, 'schema_decision': 'accepted', 'queue_state': 'validation_pending', 'replayed': False, 'shadow_mode': True})

    def laguna_cartagena_summary(self, *, now: datetime | None=None) -> dict[str, Any]:
        return self.laguna_cartagena.summary(now=now)

    @staticmethod
    def validation_policy(candidate: dict[str, Any], *, authoritative_scope_match: bool=False, independent_source_count: int=0, reviewer_approved: bool=False, public_infrastructure: bool=True, location_resolved: bool=True, stale: bool=False) -> dict[str, Any]:
        blockers = []
        if not public_infrastructure:
            blockers.append('not_public_infrastructure')
        if not location_resolved:
            blockers.append('location_unresolved')
        if stale:
            blockers.append('stale_report')
        confirmed = not blockers and (authoritative_scope_match or (independent_source_count >= 2 and reviewer_approved))
        if confirmed:
            decision = 'confirmed'
        elif blockers:
            decision = 'rejected' if 'not_public_infrastructure' in blockers else 'unverified'
        elif independent_source_count >= 2:
            decision = 'corroborated'
        else:
            decision = 'unverified'
        return {'decision': decision, 'blockers': blockers, 'authoritative_scope_match': authoritative_scope_match, 'independent_source_count': independent_source_count, 'reviewer_approved': reviewer_approved, 'confidence_ignored_for_confirmation': True}

    def validate(self, candidate: dict[str, Any], decision: dict[str, Any], reviewer: str, idempotency_key: str) -> dict[str, Any]:
        candidate_id = candidate['candidate_id']
        validation_hash = digest({'candidate': candidate, 'decision': decision, 'reviewer': reviewer})
        prior = self.store.latest('validation_events', 'idempotency_key', idempotency_key)
        if prior:
            if prior.get('validation_hash') != validation_hash:
                raise ValueError('validation_idempotency_conflict')
            return prior
        event = {'validation_id': stable_id('WDV', {'candidate_id': candidate_id, 'idempotency_key': idempotency_key}), 'candidate_id': candidate_id, 'idempotency_key': idempotency_key, 'validation_hash': validation_hash, 'reviewer': reviewer, **decision}
        persisted = self.store.append('validation_events', event)
        if decision['decision'] in TRUTH_STRENGTH:
            self.resolve_incident(candidate, decision, persisted['validation_id'])
        return persisted

    def resolve_incident(self, candidate: dict[str, Any], decision: dict[str, Any], validation_id: str | None=None) -> dict[str, Any]:
        incident_id = stable_id('WDI', candidate['dedup_key'])
        existing = self.store.latest('incidents', 'incident_id', incident_id)
        if not existing:
            truth_state = decision['decision']
            lifecycle_state = 'confirmed' if truth_state == 'confirmed' else 'reported'
            existing = self.store.append('incidents', {'schema_version': 'aguayluz.water-incident/v0.1', 'incident_id': incident_id, 'dedup_key': candidate['dedup_key'], 'event_type': candidate['event_type'], 'municipalities': candidate.get('municipalities', []), 'asset_hint': candidate.get('asset_hint'), 'truth_state': truth_state, 'lifecycle_state': lifecycle_state, 'candidate_ids': [candidate['candidate_id']], 'evidence_ids': list(candidate['evidence_ids']), 'shadow_mode': True, 'notifications_enabled': False, 'production_export_eligible': False})
            self.store.append('incident_truth_events', {'truth_event_id': stable_id('WDT', {'incident_id': incident_id, 'truth_state': truth_state, 'validation_id': validation_id}), 'incident_id': incident_id, 'from_truth_state': None, 'to_truth_state': truth_state, 'validation_id': validation_id, 'reason': 'incident_created'})
            self.store.append('lifecycle_events', {'incident_id': incident_id, 'from_state': None, 'to_state': lifecycle_state, 'reason': 'incident_created'})
            return existing
        self._reconcile_truth(existing, decision['decision'], validation_id)
        return self.current_incident(incident_id)

    def _reconcile_truth(self, incident: dict[str, Any], proposed: str, validation_id: str | None) -> None:
        current = self.current_incident(incident['incident_id'])
        current_truth = current['truth_state']
        if TRUTH_STRENGTH[proposed] <= TRUTH_STRENGTH[current_truth]:
            return
        event_key = {'incident_id': incident['incident_id'], 'to': proposed, 'validation_id': validation_id}
        event_id = stable_id('WDT', event_key)
        if self.store.latest('incident_truth_events', 'truth_event_id', event_id):
            return
        self.store.append('incident_truth_events', {'truth_event_id': event_id, 'incident_id': incident['incident_id'], 'from_truth_state': current_truth, 'to_truth_state': proposed, 'validation_id': validation_id, 'reason': 'stronger_validation'})
        if proposed == 'confirmed' and current['lifecycle_state'] in {'reported', 'acknowledged', 'disputed'}:
            self.store.append('lifecycle_events', {'event_id': stable_id('WDL', {'incident_id': incident['incident_id'], 'validation_id': validation_id, 'to': 'confirmed'}), 'incident_id': incident['incident_id'], 'from_state': current['lifecycle_state'], 'to_state': 'confirmed', 'reason': 'validation_promotion', 'validation_id': validation_id})

    def current_incident(self, incident_id: str) -> dict[str, Any]:
        base = self.store.latest('incidents', 'incident_id', incident_id)
        if not base:
            raise KeyError(incident_id)
        current = dict(base)
        truth_events = [row for row in self.store.read('incident_truth_events') if row['incident_id'] == incident_id]
        lifecycle_events = [row for row in self.store.read('lifecycle_events') if row['incident_id'] == incident_id]
        if truth_events:
            current['truth_state'] = truth_events[-1]['to_truth_state']
        if lifecycle_events:
            current['lifecycle_state'] = lifecycle_events[-1]['to_state']
        current['truth_events'] = truth_events
        current['lifecycle_events'] = lifecycle_events
        return current

    def transition(self, incident_id: str, to_state: str, reason: str, idempotency_key: str) -> dict[str, Any]:
        prior = self.store.latest('lifecycle_events', 'idempotency_key', idempotency_key)
        if prior:
            return prior
        current = self.current_incident(incident_id)['lifecycle_state']
        if to_state not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f'invalid_transition:{current}:{to_state}')
        return self.store.append('lifecycle_events', {'event_id': stable_id('WDL', {'incident_id': incident_id, 'idempotency_key': idempotency_key}), 'incident_id': incident_id, 'idempotency_key': idempotency_key, 'from_state': current, 'to_state': to_state, 'reason': reason})

    def merge(self, target_id: str, source_ids: list[str], reason: str, idempotency_key: str) -> dict[str, Any]:
        prior = self.store.latest('merge_split_events', 'idempotency_key', idempotency_key)
        if prior:
            return prior
        for incident_id in [target_id, *source_ids]:
            self.current_incident(incident_id)
        return self.store.append('merge_split_events', {'operation_id': stable_id('WDM', {'target': target_id, 'sources': sorted(source_ids), 'key': idempotency_key}), 'operation': 'merge', 'target_incident_id': target_id, 'source_incident_ids': sorted(source_ids), 'reason': reason, 'idempotency_key': idempotency_key})

    def split(self, source_id: str, child_dedup_keys: list[str], reason: str, idempotency_key: str) -> dict[str, Any]:
        self.current_incident(source_id)
        prior = self.store.latest('merge_split_events', 'idempotency_key', idempotency_key)
        if prior:
            return prior
        child_ids = [stable_id('WDI', key) for key in sorted(child_dedup_keys)]
        return self.store.append('merge_split_events', {'operation_id': stable_id('WDS', {'source': source_id, 'children': child_ids, 'key': idempotency_key}), 'operation': 'split', 'source_incident_id': source_id, 'child_incident_ids': child_ids, 'reason': reason, 'idempotency_key': idempotency_key})

    def retract(self, candidate_id: str, reason: str, idempotency_key: str) -> dict[str, Any]:
        prior = self.store.latest('retraction_events', 'idempotency_key', idempotency_key)
        if prior:
            return prior
        affected = [row['incident_id'] for row in self.store.read('incidents') if candidate_id in row.get('candidate_ids', [])]
        event = self.store.append('retraction_events', {'retraction_id': stable_id('WDRT', {'candidate_id': candidate_id, 'key': idempotency_key}), 'candidate_id': candidate_id, 'affected_incident_ids': affected, 'reason': reason, 'idempotency_key': idempotency_key, 'destructive': False, 'correction_notifications_queued': False})
        for incident_id in affected:
            current = self.current_incident(incident_id)
            self.store.append('incident_truth_events', {'truth_event_id': stable_id('WDT', {'incident_id': incident_id, 'to': 'retracted', 'key': idempotency_key}), 'incident_id': incident_id, 'from_truth_state': current['truth_state'], 'to_truth_state': 'retracted', 'retraction_id': event['retraction_id'], 'reason': reason})
            if 'retracted' in ALLOWED_TRANSITIONS.get(current['lifecycle_state'], set()):
                self.transition(incident_id, 'retracted', reason, f'{idempotency_key}:{incident_id}')
        return event
