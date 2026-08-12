"""Design-only drought/resilience reference core for AguaYLuz-PR P0.

This module is intentionally outside runtime discovery roots. It provides deterministic,
provenance-conscious primitives for drought-state separation, rapid-onset trajectory
assessment, water-supply-system validation, and a non-activating crosswalk into the
existing AlertEvent contract.

No function here declares an official drought, operating threshold, shortage, or failure.
Scientific/operational thresholds must be supplied explicitly and bound to a source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
import hashlib
import json
import re

DROUGHT_CLASSES = frozenset(
    {"meteorological", "hydrological", "agricultural", "socioeconomic"}
)
DROUGHT_STATES = frozenset(
    {"normal", "watch", "rapid_decline", "drought", "severe", "unknown"}
)
SUPPLY_NODE_TYPES = frozenset(
    {"source", "intake", "well", "treatment", "storage", "distribution", "demand"}
)


@dataclass(frozen=True)
class TrajectoryRule:
    """Explicit caller-supplied rule for a concerning trajectory.

    ``direction`` is ``decrease`` when deterioration means falling values (e.g. storage)
    and ``increase`` when deterioration means rising values (e.g. depth-to-water).
    ``minimum_rate_per_day`` is the absolute minimum concerning rate. It is not inferred
    from the data and therefore cannot silently become an operational threshold.
    """

    metric: str
    direction: str
    minimum_rate_per_day: float
    minimum_span_days: int = 7
    minimum_points: int = 2
    source_ref: str = ""
    rule_id: str = ""

    def validate(self) -> None:
        if self.direction not in {"decrease", "increase"}:
            raise ValueError("direction must be decrease or increase")
        if self.minimum_rate_per_day <= 0:
            raise ValueError("minimum_rate_per_day must be > 0")
        if self.minimum_span_days < 1:
            raise ValueError("minimum_span_days must be >= 1")
        if self.minimum_points < 2:
            raise ValueError("minimum_points must be >= 2")
        if not self.source_ref.strip():
            raise ValueError("source_ref is required so thresholds are provenance-bound")


def _parse_day(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _slug(value: str, limit: int = 40) -> str:
    out = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_").lower()
    return (out or "state")[:limit]


def build_drought_state(
    *,
    drought_class: str,
    state: str,
    observed_date: str,
    geography_id: str,
    source_ref: str,
    evidence_tier: str,
    confidence: int,
    indicators: Iterable[dict[str, Any]],
    review_status: str = "needs_review",
    methodology_ref: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create one class-specific drought state without cross-class inference."""
    if drought_class not in DROUGHT_CLASSES:
        raise ValueError(f"unsupported drought_class: {drought_class}")
    if state not in DROUGHT_STATES:
        raise ValueError(f"unsupported state: {state}")
    _parse_day(observed_date)
    rows = [dict(item) for item in indicators]
    if not rows:
        raise ValueError("at least one indicator is required")
    if not source_ref.strip():
        raise ValueError("source_ref is required")
    if not 0 <= int(confidence) <= 100:
        raise ValueError("confidence must be 0..100")

    identity = {
        "drought_class": drought_class,
        "observed_date": observed_date[:10],
        "geography_id": geography_id,
        "source_ref": source_ref,
        "indicators": rows,
    }
    return {
        "drought_state_id": _stable_id("AYL_DST", identity),
        "drought_class": drought_class,
        "state": state,
        "observed_date": observed_date[:10],
        "geography_id": geography_id,
        "source_ref": source_ref,
        "evidence_tier": evidence_tier,
        "confidence": int(confidence),
        "review_status": review_status,
        "methodology_ref": methodology_ref,
        "indicators": rows,
        "notes": notes,
    }


def assess_rapid_onset(
    observations: Iterable[dict[str, Any]],
    rule: TrajectoryRule,
) -> dict[str, Any]:
    """Assess whether one metric crosses an explicit concerning rate rule.

    The algorithm uses the earliest and latest valid observations after sorting by date.
    It preserves point count/span and returns ``not_assessable`` rather than guessing when
    the denominator is insufficient. The result is an assessment, not an official drought.
    """
    rule.validate()
    valid: list[tuple[date, float, dict[str, Any]]] = []
    for raw in observations:
        if raw.get("metric") != rule.metric:
            continue
        try:
            day = _parse_day(str(raw.get("observed_date") or raw.get("date")))
            value = float(raw["value"])
        except (KeyError, TypeError, ValueError):
            continue
        valid.append((day, value, dict(raw)))
    valid.sort(key=lambda row: row[0])

    if len(valid) < rule.minimum_points:
        return {
            "assessment": "not_assessable",
            "reason": "insufficient_points",
            "metric": rule.metric,
            "point_count": len(valid),
            "rule_source_ref": rule.source_ref,
            "rule_id": rule.rule_id or None,
        }

    first_day, first_value, _ = valid[0]
    last_day, last_value, _ = valid[-1]
    span_days = (last_day - first_day).days
    if span_days < rule.minimum_span_days:
        return {
            "assessment": "not_assessable",
            "reason": "insufficient_span",
            "metric": rule.metric,
            "point_count": len(valid),
            "span_days": span_days,
            "rule_source_ref": rule.source_ref,
            "rule_id": rule.rule_id or None,
        }

    signed_rate = (last_value - first_value) / span_days
    concerning_rate = -signed_rate if rule.direction == "decrease" else signed_rate
    triggered = concerning_rate >= rule.minimum_rate_per_day
    payload = {
        "metric": rule.metric,
        "start_date": first_day.isoformat(),
        "end_date": last_day.isoformat(),
        "start_value": first_value,
        "end_value": last_value,
        "span_days": span_days,
        "point_count": len(valid),
        "signed_rate_per_day": signed_rate,
        "concerning_rate_per_day": concerning_rate,
        "threshold_rate_per_day": rule.minimum_rate_per_day,
        "direction": rule.direction,
        "rule_source_ref": rule.source_ref,
        "rule_id": rule.rule_id or None,
    }
    return {
        "assessment_id": _stable_id("AYL_RAPID", payload),
        "assessment": "rapid_decline" if triggered else "no_rapid_decline",
        **payload,
    }


def validate_water_supply_system(system: dict[str, Any]) -> list[str]:
    """Return deterministic invariant violations for a supply-system graph.

    This validates declared topology only. It never infers a physical connection from
    proximity, shared municipality, names, or equal counts.
    """
    errors: list[str] = []
    nodes = system.get("nodes") or []
    edges = system.get("edges") or []
    node_ids = [str(n.get("node_id") or "") for n in nodes]
    if not nodes:
        errors.append("nodes_empty")
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate_node_id")
    known = set(node_ids)
    for node in nodes:
        if node.get("node_type") not in SUPPLY_NODE_TYPES:
            errors.append(f"unsupported_node_type:{node.get('node_id')}")
    edge_ids: set[str] = set()
    for edge in edges:
        eid = str(edge.get("edge_id") or "")
        if not eid or eid in edge_ids:
            errors.append("missing_or_duplicate_edge_id")
        edge_ids.add(eid)
        src = str(edge.get("from_node_id") or "")
        dst = str(edge.get("to_node_id") or "")
        if src not in known or dst not in known:
            errors.append(f"dangling_edge:{eid}")
        if src == dst and src:
            errors.append(f"self_loop:{eid}")
        if not str(edge.get("binding_ref") or "").strip():
            errors.append(f"unproven_edge:{eid}")
    return sorted(set(errors))


def drought_state_to_alert_candidate(state: dict[str, Any]) -> dict[str, Any]:
    """Crosswalk a drought state into a *draft* existing AlertEvent candidate.

    The candidate is deliberately non-active and ``needs_review``. Cross-class state is
    not synthesized: the title and notes identify exactly one drought class.
    """
    drought_class = str(state["drought_class"])
    if drought_class not in DROUGHT_CLASSES:
        raise ValueError("invalid drought_class")
    observed = _parse_day(str(state["observed_date"]))
    severity_by_state = {
        "normal": 0,
        "watch": 1,
        "rapid_decline": 2,
        "drought": 2,
        "severe": 3,
        "unknown": 0,
    }
    state_name = str(state["state"])
    source_ref = str(state["source_ref"])
    geography_id = str(state["geography_id"])
    return {
        "alert_id": f"AYL_ALR_{observed.strftime('%Y%m%d')}_drought_{_slug(state['drought_state_id'])}",
        "module_id": "HYDRO_OPS",
        "event_type": "hazard",
        "status": "draft",
        "source_title": f"{drought_class} drought state: {state_name}",
        "source_ref": source_ref,
        "source_hash": None,
        "published_at": None,
        "start_at": datetime.combine(observed, datetime.min.time()).isoformat() + "Z",
        "end_at": None,
        "estimated_duration_hr": None,
        "asset_name": geography_id,
        "asset_id": None,
        "operator": None,
        "municipalities": ["(unscoped)"],
        "sectors_impacted": ["water"],
        "latitude": None,
        "longitude": None,
        "coord_confidence": "unknown",
        "severity": severity_by_state[state_name],
        "confidence": int(state["confidence"]),
        "ilap_score": None,
        "covert_flags": [],
        "gap_status": "major" if state.get("review_status") != "accepted" else "minor",
        "review_status": "needs_review",
        "evidence_tier": state["evidence_tier"],
        "linked_asset_ids": [],
        "validation_notes": (
            "Draft crosswalk from one class-specific drought state; no automatic "
            "cross-class inference and no official drought declaration implied."
        ),
    }
