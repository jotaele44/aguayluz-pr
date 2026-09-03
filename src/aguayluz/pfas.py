"""PFAS evidence primitives for AguaYLuz-PR.

This module is intentionally fail-closed. Measurements, source/release evidence,
water-system identity, spatial relationships, regulatory status, and legal claims
are separate facts. No name/proximity-only evidence can establish causation.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

PFAS_SUBSTANCES = {
    "PFOA": {"cas": "335-67-1", "name": "perfluorooctanoic acid"},
    "PFOS": {"cas": "1763-23-1", "name": "perfluorooctanesulfonic acid"},
    "PFHxS": {"cas": "355-46-4", "name": "perfluorohexanesulfonic acid"},
    "PFNA": {"cas": "375-95-1", "name": "perfluorononanoic acid"},
    "HFPO-DA": {"cas": "13252-13-6", "name": "hexafluoropropylene oxide dimer acid"},
    "PFBS": {"cas": "375-73-5", "name": "perfluorobutanesulfonic acid"},
}

EVIDENCE_STATES = frozenset({
    "MEASURED", "ALLEGED", "ASSOCIATED", "CANDIDATE", "ATTRIBUTED",
    "ADJUDICATED", "CONTRADICTED", "EXCLUDED", "UNRESOLVED",
})
IDENTITY_CARDINALITIES = frozenset({"1:1", "1:N", "N:1", "N:N", "0:1", "UNRESOLVED"})
SPATIAL_STATES = frozenset({
    "FULLY_WITHIN", "PARTIAL", "TOUCH_ONLY", "OUTSIDE", "NULL_EMPTY", "UNRESOLVED",
})
CERT_STATES = frozenset({
    "PASS", "FAIL", "OPEN", "BLOCKED", "PROVISIONAL", "AUDIT_ONLY",
    "NONCANONICAL", "CANDIDATE_NOT_IDENTITY", "UNRESOLVED", "SUPERSEDED",
})
DISCOVERY_ONLY = frozenset({
    "NAME_ONLY", "NORMALIZED_NAME_ONLY", "COUNT_EQUALITY", "NEAREST_ONLY",
    "PROXIMITY_ONLY", "SAME_CATEGORY", "SOURCE_ABSENCE", "TEXT_SEARCH_ONLY",
})

@dataclass(frozen=True)
class RegulatoryRule:
    rule_id: str
    analyte: str
    value: float | None
    unit: str
    rule_type: str
    legal_state: str
    effective_from: str | None
    compliance_from: str | None
    source_record_id: str


def normalize_ng_l(value: float, unit: str) -> float:
    unit_norm = unit.strip().lower().replace("µ", "u")
    if unit_norm in {"ng/l", "ppt"}:
        return float(value)
    if unit_norm in {"ug/l", "ppb"}:
        return float(value) * 1000.0
    raise ValueError(f"unsupported PFAS concentration unit: {unit}")


def validate_measurement(row: dict[str, Any]) -> None:
    analyte = str(row.get("analyte") or "")
    if analyte not in PFAS_SUBSTANCES:
        raise ValueError(f"unsupported canonical PFAS analyte: {analyte}")
    if row.get("evidence_state") != "MEASURED":
        raise ValueError("analytical observations must retain evidence_state=MEASURED")
    if not row.get("source_record_id"):
        raise ValueError("measurement requires source_record_id")
    if not row.get("sample_date"):
        raise ValueError("measurement requires sample_date")
    sign = row.get("result_sign")
    if sign not in {"=", "<"}:
        raise ValueError("result_sign must be '=' or '<'")
    value = row.get("result_value")
    if sign == "=" and value is None:
        raise ValueError("detected result requires numeric result_value")
    if sign == "<" and value is not None:
        raise ValueError("non-detect must not synthesize a numeric result_value")
    if sign == "=" and not row.get("result_unit"):
        raise ValueError("numeric result requires result_unit")


def validate_binding(row: dict[str, Any]) -> None:
    state = str(row.get("evidence_state") or "")
    if state not in EVIDENCE_STATES:
        raise ValueError(f"unsupported evidence_state: {state}")
    cardinality = str(row.get("identity_cardinalityity") or row.get("identity_cardinality") or "UNRESOLVED")
    if cardinality not in IDENTITY_CARDINALITIES:
        raise ValueError(f"unsupported identity cardinality: {cardinality}")
    spatial = row.get("spatial_state")
    if spatial is not None and spatial not in SPATIAL_STATES:
        raise ValueError(f"unsupported spatial_state: {spatial}")
    evidence_classes = frozenset(str(v) for v in row.get("evidence_classes", []))
    if state in {"ATTRIBUTED", "ADJUDICATED"} and evidence_classes and evidence_classes <= DISCOVERY_ONLY:
        raise ValueError("attribution cannot be established from discovery-only evidence")
    if state == "ADJUDICATED":
        if cardinality == "UNRESOLVED":
            raise ValueError("adjudicated binding requires resolved cardinality")
        if row.get("contradictions"):
            raise ValueError("adjudicated binding cannot retain open contradictions")
        if not row.get("source_record_ids"):
            raise ValueError("adjudicated binding requires source_record_ids")


def current_rule(rules: Iterable[RegulatoryRule], analyte: str, as_of: str) -> RegulatoryRule | None:
    candidates = [
        r for r in rules
        if r.analyte == analyte
        and (r.effective_from is None or r.effective_from <= as_of)
        and r.legal_state.startswith("IN_FORCE")
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: (r.effective_from or "", r.rule_id))[-1]


def compare_measurement_to_rule(
    measurement: dict[str, Any], rule: RegulatoryRule | None, *, as_of: str
) -> dict[str, Any]:
    """Return context only; never converts UCMR observations into compliance findings."""
    validate_measurement(measurement)
    if rule is None or rule.value is None:
        return {"state": "NO_APPLICABLE_NUMERIC_RULE", "compliance_finding": False}
    if measurement["result_sign"] == "<":
        return {"state": "NONDETECT_NOT_COMPARABLE", "compliance_finding": False}
    observed = normalize_ng_l(float(measurement["result_value"]), str(measurement["result_unit"]))
    threshold = normalize_ng_l(rule.value, rule.unit)
    return {
        "state": "ABOVE_REFERENCE" if observed > threshold else "AT_OR_BELOW_REFERENCE",
        "observed_ng_l": observed,
        "threshold_ng_l": threshold,
        "rule_id": rule.rule_id,
        "as_of": as_of,
        "compliance_finding": False,
        "note": "A single occurrence measurement is not an MCL compliance determination.",
    }


def certification_report(
    *, source_manifestations: Iterable[dict[str, Any]], measurements: Iterable[dict[str, Any]],
    bindings: Iterable[dict[str, Any]], unresolved_material: Iterable[str],
) -> dict[str, Any]:
    sources = list(source_manifestations)
    observations = list(measurements)
    binding_rows = list(bindings)
    unresolved = sorted(set(str(v) for v in unresolved_material if str(v)))

    errors: list[str] = []
    source_ids = [str(r.get("source_record_id") or "") for r in sources]
    if len(source_ids) != len(set(source_ids)):
        errors.append("duplicate source_record_id")
    for row in sources:
        if not row.get("source_record_id") or not row.get("url") or not row.get("retrieved_utc"):
            errors.append(f"incomplete source manifestation: {row.get('source_record_id')}")
        if row.get("byte_sha256") is None:
            unresolved.append(f"SOURCE_HASH_OPEN:{row.get('source_record_id')}")
    for row in observations:
        try:
            validate_measurement(row)
        except ValueError as exc:
            errors.append(str(exc))
    for row in binding_rows:
        try:
            validate_binding(row)
        except ValueError as exc:
            errors.append(str(exc))

    unresolved = sorted(set(unresolved))
    structural = "PASS" if not errors else "FAIL"
    cert = "PASS" if structural == "PASS" and not unresolved else "OPEN"
    return {
        "source_count": len(sources),
        "measurement_count": len(observations),
        "binding_count": len(binding_rows),
        "structural_state": structural,
        "error_count": len(errors),
        "errors": errors,
        "unresolved_material_count": len(unresolved),
        "unresolved_material": unresolved,
        "certification_state": cert,
    }
