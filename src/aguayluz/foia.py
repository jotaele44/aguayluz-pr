"""FOIA roster generator.

Converts producer-observed data gaps into structured public-records request
targets. Three input streams produce three target kinds, but they share the
same agency-routing logic:

  - review_queue items with reason "missing coordinates" / "no flowlines" /
    "outside PR bbox"             → agency derived from the source provenance
                                    (PRASA/AAA for water, PREPA/LUMA for power,
                                    FEMA for recovery, EPA fallback)
  - reconciliation_report findings with kind="missing_coverage"
                                  → FEMA (FEMA is the source of the event but
                                    the gap is "we don't have an asset record")
  - utility_assets with attribute_coverage="partial"
                                  → EPA (Vogel/VPUAttribute/NLCD on VPU 21)

Deduplicates by `(agency, frozenset(missing_fields))` so two assets in the
same municipality missing the same field merge into one target.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

_REQUEST_BODY_PREAMBLE = (
    "Pursuant to the Puerto Rico Public Records Law / U.S. Freedom of "
    "Information Act, aguayluz-pr (a public-data federation module producing "
    "Puerto Rico utility infrastructure intelligence) requests the records "
    "described below. The request originates from a data gap detected by the "
    "module's validation gates; supporting evidence is attached."
)


def _agency_for_asset_type(asset_type: str | None) -> str:
    if asset_type in ("water", "wastewater"):
        return "PRASA"
    if asset_type == "power":
        return "LUMA"
    return "EPA"  # generic fallback


def _target_id(*, agency: str, missing_fields: frozenset[str], record_ref: str) -> str:
    """Stable target_id derived from (agency, missing_fields, record_ref)."""
    seed = f"{agency}|{','.join(sorted(missing_fields))}|{record_ref}"
    digest = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"AYL_FOIA_TGT_{digest}"


def _classify_review_item(item: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (agency, missing_fields) for a review_queue item."""
    reason = (item.get("reason") or "").lower()
    record_ref = item.get("record_ref") or ""
    if "missing coordinates" in reason or "missing snap" in reason:
        # Source from the asset's adapter prefix (FRS/HIFLD).
        if "EVT" in record_ref:
            return "FEMA", ["start_time", "end_time", "coordinates"]
        if "_LUMA_" in record_ref or "_PREPA_" in record_ref:
            return "LUMA", ["latitude", "longitude"]
        return "PRASA", ["latitude", "longitude"]
    if "outside pr bbox" in reason:
        return "EPA", ["geographic_correction"]
    if "no flowlines" in reason or "no result_delineated_area" in reason:
        return "EPA", ["nhdplus_v2_1_reach"]
    if "validation failed" in reason:
        return "FEMA", ["projectProcessStep", "applicationTitle"]
    return "EPA", ["records_inquiry"]


def _request_body(*, agency_full: str, missing_fields: list[str], evidence: dict[str, Any]) -> str:
    fields_block = "\n".join(f"  - {f}" for f in sorted(missing_fields))
    return (
        f"{_REQUEST_BODY_PREAMBLE}\n\n"
        f"Addressed to: {agency_full}\n\n"
        f"Records requested: data fields necessary to complete the asset / event "
        f"record identified by {evidence['record_ref']}.\n\n"
        f"Specifically, the following fields are missing or incomplete in the "
        f"public dataset currently available to the producer:\n{fields_block}\n\n"
        f"Reason the gap was surfaced: {evidence['reason']}\n"
    )


def load_agencies(config_path: Path) -> dict[str, dict[str, Any]]:
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("agencies", {}) or {}


def generate_targets(
    *,
    review_items: list[dict[str, Any]],
    reconciliation_findings: list[dict[str, Any]],
    partial_assets: list[dict[str, Any]],
    agencies: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Walk every gap stream and return deduplicated FOIA targets."""
    targets: dict[tuple[str, frozenset[str]], dict[str, Any]] = {}

    def _emit(*, agency: str, missing_fields: list[str], evidence: dict[str, Any]) -> None:
        key = (agency, frozenset(missing_fields))
        if key in targets:
            return  # dedup by agency + field-set
        agency_meta = agencies.get(agency, {})
        agency_full = agency_meta.get("full_name", agency)
        # The schema's `supporting_evidence` block rejects extra fields, so we
        # pull `confidence` out into the target-level field and strip it from
        # the evidence dict before storing.
        confidence = int(evidence.get("confidence", 60) or 60)
        clean_evidence = {
            k: v for k, v in evidence.items()
            if k in ("record_ref", "reason", "severity", "municipality")
        }
        target = {
            "target_id": _target_id(
                agency=agency, missing_fields=frozenset(missing_fields),
                record_ref=evidence["record_ref"],
            ),
            "agency": agency,
            "agency_contact_url": agency_meta.get("contact_url"),
            "agency_contact_email": agency_meta.get("contact_email"),
            "missing_fields": sorted(missing_fields),
            "supporting_evidence": clean_evidence,
            "request_body": _request_body(
                agency_full=agency_full,
                missing_fields=missing_fields,
                evidence=evidence,
            ),
            "status": "queued",
            "confidence": confidence,
            "sla_business_days": agency_meta.get("default_sla_business_days"),
        }
        targets[key] = target

    # 1. review_queue items
    for item in review_items:
        if not isinstance(item, dict):
            continue
        agency, missing = _classify_review_item(item)
        evidence = {
            "record_ref": item.get("record_ref") or "unknown",
            "reason": item.get("reason") or "(no reason recorded)",
            "severity": item.get("severity", "warn"),
            "municipality": item.get("municipality"),
        }
        _emit(agency=agency, missing_fields=missing, evidence=evidence)

    # 2. reconciliation_report missing_coverage findings
    for finding in reconciliation_findings:
        if not isinstance(finding, dict) or finding.get("kind") != "missing_coverage":
            continue
        evidence = {
            "record_ref": finding.get("event_id") or finding.get("finding_id") or "unknown",
            "reason": finding.get("details") or "missing asset coverage for FEMA event",
            "severity": finding.get("severity", "warn"),
            "municipality": finding.get("municipality"),
            "confidence": finding.get("confidence", 70),
        }
        _emit(
            agency="FEMA",
            missing_fields=["asset_record_for_municipality", "facility_inventory"],
            evidence=evidence,
        )

    # 3. partial-coverage assets (VPU 21 EPA inventory gap)
    for asset in partial_assets:
        if not isinstance(asset, dict) or asset.get("attribute_coverage") != "partial":
            continue
        evidence = {
            "record_ref": asset.get("asset_id") or "unknown",
            "reason": "VPU 21 NHDPlus extensions (Vogel/VPUAttribute/NLCD) unavailable per EPA inventory",
            "severity": "warn",
            "municipality": asset.get("municipality"),
            "confidence": 75,
        }
        _emit(
            agency="EPA",
            missing_fields=["VogelExtension_VPU21", "VPUAttributeExtension_VPU21", "VPUAttributeExtensionNLCD_VPU21"],
            evidence=evidence,
        )

    # Stable order so re-runs produce identical files.
    return sorted(targets.values(), key=lambda t: t["target_id"])
