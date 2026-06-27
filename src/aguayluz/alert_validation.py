"""VAL-001..010 — the AguaYLuz-PR alert validation pipeline.

These are the workbook's operational acceptance rules, expressed in the
``GateResult``-style of :mod:`aguayluz.validation`. Each rule returns an
:class:`AlertViolation` when it fails; :func:`validate_alert` aggregates them
into an :class:`AlertValidationResult`. A record is ``valid`` only when no
*rejecting* rule fails (every rule rejects except the advisory VAL-008).

This module is schema-agnostic on purpose: it operates on plain dicts so it can
back the ``validate_alert`` MCP tool and run before Pydantic/JSON-Schema
construction. JSON Schema still owns type/enum/range checks; these rules add the
cross-field and contextual logic schema cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ViolationSeverity = Literal["blocking", "major", "minor"]

#: Controlled vocabulary for event_type (mirrors alert_event.schema.json).
EVENT_TYPES: frozenset[str] = frozenset(
    {"maintenance", "outage", "failure", "quality", "hazard", "inspection", "unknown"}
)

#: The 10 registry module ids (mirrors the alert module registry).
MODULE_IDS: frozenset[str] = frozenset(
    {
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
    }
)

#: Allowed structural covert indicators (VAL-010). Anything outside this set is
#: treated as an unsupported interpretation and rejected.
COVERT_FLAG_VOCAB: frozenset[str] = frozenset(
    {
        "intake_dependency",
        "service_area_disruption",
        "power_dependency",
        "telemetry_loss",
        "structural_concern",
        "contamination_pathway",
        "access_constraint",
        "watershed_effect",
    }
)

#: confidence at or below this (0-100 scale) cannot be gap-free (VAL-009).
LOW_CONFIDENCE_THRESHOLD = 40

#: Lifecycle states that constitute "production linking" for VAL-008.
_PRODUCTION_STATES: frozenset[str] = frozenset({"validated", "active"})


@dataclass
class AlertViolation:
    rule_id: str
    scope: str
    severity: ViolationSeverity
    message: str
    #: Whether failing this rule rejects the record (workbook reject_if_false).
    rejecting: bool = True


@dataclass
class AlertValidationResult:
    alert_id: str
    violations: list[AlertViolation] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(v.rejecting for v in self.violations)

    @property
    def rejecting_violations(self) -> list[AlertViolation]:
        return [v for v in self.violations if v.rejecting]

    def as_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "valid": self.valid,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "scope": v.scope,
                    "severity": v.severity,
                    "rejecting": v.rejecting,
                    "message": v.message,
                }
                for v in self.violations
            ],
        }


def validate_alert(
    alert: dict,
    *,
    known_alert_ids: set[str] | None = None,
    known_module_ids: frozenset[str] | set[str] = MODULE_IDS,
) -> AlertValidationResult:
    """Run VAL-001..010 against a single alert dict.

    ``known_alert_ids`` supplies ids already present so VAL-001 can detect
    duplicates; pass the ids seen so far when validating a batch.
    """
    known_alert_ids = known_alert_ids or set()
    aid = alert.get("alert_id", "")
    res = AlertValidationResult(alert_id=aid or "<missing>")

    # VAL-001 — alert_id unique and non-empty (blocking).
    if not aid:
        res.violations.append(
            AlertViolation("VAL-001", "event", "blocking", "alert_id is empty.")
        )
    elif aid in known_alert_ids:
        res.violations.append(
            AlertViolation("VAL-001", "event", "blocking", f"duplicate alert_id: {aid}")
        )

    # VAL-002 — module_id exists in the registry (blocking).
    module_id = alert.get("module_id")
    if module_id not in known_module_ids:
        res.violations.append(
            AlertViolation("VAL-002", "event", "blocking", f"unknown module_id: {module_id!r}")
        )

    # VAL-003 — start_at <= end_at when end_at exists (blocking).
    start_at, end_at = alert.get("start_at"), alert.get("end_at")
    if start_at and end_at and str(start_at) > str(end_at):
        res.violations.append(
            AlertViolation(
                "VAL-003", "event", "blocking", f"start_at {start_at} is after end_at {end_at}."
            )
        )

    # VAL-004 — source_hash or source_ref present (blocking).
    if not (alert.get("source_hash") or alert.get("source_ref")):
        res.violations.append(
            AlertViolation(
                "VAL-004", "event", "blocking", "no source_ref or source_hash (source-less alert)."
            )
        )

    # VAL-005 — latitude/longitude both present or both null (major).
    lat, lon = alert.get("latitude"), alert.get("longitude")
    if (lat is None) != (lon is None):
        res.violations.append(
            AlertViolation("VAL-005", "geo", "major", "latitude/longitude must both be set or both null.")
        )

    # VAL-006 — coord_confidence 'exact' requires source-backed coordinates (major).
    if alert.get("coord_confidence") == "exact" and (
        lat is None or lon is None or not alert.get("source_ref")
    ):
        res.violations.append(
            AlertViolation(
                "VAL-006",
                "geo",
                "major",
                "coord_confidence 'exact' requires both coordinates and a source_ref.",
            )
        )

    # VAL-007 — event_type in controlled vocabulary (blocking).
    if alert.get("event_type") not in EVENT_TYPES:
        res.violations.append(
            AlertViolation(
                "VAL-007", "classification", "blocking", f"event_type not in vocabulary: {alert.get('event_type')!r}"
            )
        )

    # VAL-008 — asset_id required before production linking (minor, advisory).
    if alert.get("status") in _PRODUCTION_STATES and not alert.get("asset_id"):
        res.violations.append(
            AlertViolation(
                "VAL-008",
                "dependency",
                "minor",
                f"status {alert.get('status')!r} should have a matched asset_id before production linking.",
                rejecting=False,
            )
        )

    # VAL-009 — low confidence cannot be gap-free (major).
    confidence = alert.get("confidence")
    if (
        isinstance(confidence, int)
        and confidence <= LOW_CONFIDENCE_THRESHOLD
        and alert.get("gap_status") in (None, "none")
    ):
        res.violations.append(
            AlertViolation(
                "VAL-009",
                "confidence",
                "major",
                f"confidence {confidence} <= {LOW_CONFIDENCE_THRESHOLD} forces gap_status minor/major/blocking.",
            )
        )

    # VAL-010 — only controlled structural covert indicators allowed (blocking).
    unsupported = [f for f in alert.get("covert_flags", []) if f not in COVERT_FLAG_VOCAB]
    if unsupported:
        res.violations.append(
            AlertViolation(
                "VAL-010",
                "safety",
                "blocking",
                f"unsupported covert_flags (not structural vocabulary): {unsupported}",
            )
        )

    return res


def validate_alerts(alerts: list[dict]) -> list[AlertValidationResult]:
    """Validate a batch, threading seen ids so VAL-001 detects duplicates."""
    seen: set[str] = set()
    results: list[AlertValidationResult] = []
    for alert in alerts:
        results.append(validate_alert(alert, known_alert_ids=set(seen)))
        if alert.get("alert_id"):
            seen.add(alert["alert_id"])
    return results
