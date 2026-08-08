"""Design-only water-crisis assessment bridge.

This module is pure and performs no I/O. It accepts already-normalized candidate
assessments and maps them to the existing AlertEvent vocabulary. It never marks a
record accepted or verified, never writes to the alert corpus, and never contacts
AAA, ChatGPT, or any live provider.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

ASSESSMENT_TO_ALERT = {
    "CARRAIZO_RATIONING_RISK": ("HYDRO_OPS", "hazard"),
    "CUPEY_DISTRIBUTION_RECOVERY_FAILURE": ("HYDRO_OPS", "failure"),
    "ISLANDWIDE_RESERVOIR_DECLINE": ("HYDRO_OPS", "hazard"),
    "LOCO_RESERVOIR_OBSERVATION": ("HYDRO_OPS", "hazard"),
    "CONTAMINATION_EVENT": ("CONTAMINATION", "quality"),
}

STATE_TO_ALERT_STATUS = {
    "closed": "closed",
    "stable": "validated",
    "watch": "validated",
    "observation": "validated",
    "adjustment": "validated",
    "control": "validated",
    "rationing": "validated",
    "restoring": "validated",
    "unknown": "draft",
}


def map_candidate_to_alert(assessment: dict[str, Any]) -> dict[str, Any]:
    """Return a non-promoted AlertEvent-shaped candidate projection.

    Hard gates:
    - input promotion_status must be ``candidate``;
    - output review_status is never ``accepted``;
    - output status is never ``active``;
    - missing or expired evidence is blocked rather than promoted.
    """
    row = deepcopy(assessment)
    if row.get("promotion_status") != "candidate":
        raise ValueError("water-crisis bridge accepts candidate records only")

    code = row.get("assessment_code")
    if code not in ASSESSMENT_TO_ALERT:
        raise ValueError(f"unsupported assessment_code: {code}")
    module_id, event_type = ASSESSMENT_TO_ALERT[code]

    blocked = row.get("review_status") in {"blocked", "rejected"} or not row.get("source_receipts")
    review_status = "blocked" if blocked else "needs_review"
    status = "draft" if blocked else STATE_TO_ALERT_STATUS.get(row.get("operational_state"), "draft")

    causes = [c.get("cause") for c in row.get("likely_causes", []) if c.get("cause")]
    contradictions = [
        f"{c.get('claim_a')} <> {c.get('claim_b')} [{c.get('status')}]"
        for c in row.get("contradictions", [])
    ]
    mitigation = row.get("recommended_immediate_mitigation", [])
    notes = {
        "assessment_code": code,
        "official_vs_derived": row.get("official_vs_derived"),
        "likely_causes": causes,
        "contradictions": contradictions,
        "restoration_criteria": row.get("restoration_criteria", []),
        "recommended_immediate_mitigation": mitigation,
        "promotion_guard": "candidate-only; no automatic verified promotion",
    }

    return {
        "alert_id": row["assessment_id"].replace("AYL_WCA_", "AYL_ALR_", 1),
        "module_id": module_id,
        "event_type": event_type,
        "status": status,
        "source_title": code.replace("_", " ").title(),
        "source_ref": row["source_receipts"][0]["source_ref"] if row.get("source_receipts") else "unavailable",
        "source_hash": row["source_receipts"][0]["sha256"] if row.get("source_receipts") else None,
        "published_at": row["source_receipts"][0].get("published_at") if row.get("source_receipts") else None,
        "start_at": row["observed_at"],
        "end_at": row["valid_until"],
        "asset_name": code,
        "asset_id": None,
        "operator": None,
        "municipalities": row["affected_municipalities"],
        "sectors_impacted": ["water"],
        "latitude": None,
        "longitude": None,
        "coord_confidence": "unknown",
        "severity": 4 if code in {"CUPEY_DISTRIBUTION_RECOVERY_FAILURE", "CONTAMINATION_EVENT"} else 3,
        "confidence": int(row["confidence"]),
        "ilap_score": None,
        "covert_flags": [],
        "gap_status": "blocking" if blocked else ("major" if row.get("contradictions") else "minor"),
        "review_status": review_status,
        "evidence_tier": row["evidence_tier"],
        "linked_asset_ids": row.get("affected_asset_ids", []),
        "validation_notes": str(notes),
        "water_crisis_extension": row,
    }
