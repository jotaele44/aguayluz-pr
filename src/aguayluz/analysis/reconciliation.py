"""Reconcile FEMA project status against utility asset operational status.

Three problem patterns and one positive pattern are surfaced as `findings`:

  - status_mismatch  : asset is `damaged`/`inactive` AND a FEMA project for
                       the same municipality is `Project Closed Out`
                       → the asset should be back online, but the record says
                       it isn't.
  - missing_coverage : a FEMA event references a municipality where we have
                       NO utility_asset record → either we're missing the
                       asset, or the event affects something we don't track.
  - stale_asset      : asset is `active` AND a FEMA project for the same
                       municipality is still in flight (Obligated / Drawdown
                       / Active steps) → the asset may have been fixed faster
                       than the recovery paperwork, or the asset record is
                       stale.
  - consistent       : assets in municipalities with no in-flight FEMA work,
                       or in municipalities where the FEMA project step
                       matches the asset status.

Findings flow into `outputs/reconciliation_report.json` and into the Base44
envelope's `contradictions` field — the federation hub can act on them
without re-deriving anything.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

FindingKind = Literal["status_mismatch", "missing_coverage", "stale_asset", "consistent"]
Severity = Literal["info", "warn", "critical"]


# Maps FEMA `notes` like "step=Project Closed Out" to logical state.
_CLOSED_STEPS = {"Project Closed Out"}
_IN_FLIGHT_STEPS = {
    "Project Obligated", "Project Drawdown", "Active",
    "Project Submitted", "Project Under Review",
}


@dataclass(frozen=True)
class Finding:
    finding_id: str
    kind: FindingKind
    severity: Severity
    municipality: str
    details: str
    confidence: int
    asset_id: str | None = None
    event_id: str | None = None
    fema_step: str | None = None
    asset_status: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "kind": self.kind,
            "severity": self.severity,
            "asset_id": self.asset_id,
            "event_id": self.event_id,
            "municipality": self.municipality,
            "details": self.details,
            "confidence": self.confidence,
            "fema_step": self.fema_step,
            "asset_status": self.asset_status,
        }


def _normalize_muni(value: str | None) -> str:
    return (value or "").strip().casefold()


def _event_municipality(event: dict[str, Any]) -> str | None:
    """FEMA `affected_area` is shaped `'<County>, PR — <damage category>'`."""
    area = event.get("affected_area") or ""
    if "," in area:
        return area.split(",", 1)[0].strip()
    return None


def _fema_step(event: dict[str, Any]) -> str | None:
    """Pull `step=...` out of the event's notes (set by the FEMA adapter)."""
    notes = event.get("notes") or ""
    for chunk in notes.split("|"):
        chunk = chunk.strip()
        if chunk.startswith("step="):
            return chunk[len("step="):].strip()
    return None


def _finding_id(seed: str) -> str:
    digest = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"AYL_FIND_{digest}"


def _assets_by_municipality(assets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        key = _normalize_muni(a.get("municipality"))
        if key:
            out.setdefault(key, []).append(a)
    return out


def _events_by_municipality(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        key = _normalize_muni(_event_municipality(e))
        if key:
            out.setdefault(key, []).append(e)
    return out


def reconcile(
    *,
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> tuple[list[Finding], dict[str, int]]:
    """Return `(findings, summary_counts)`."""
    findings: list[Finding] = []

    assets_by = _assets_by_municipality(assets)
    events_by = _events_by_municipality(events)

    # --- status_mismatch + stale_asset (asset side) ---
    for muni_key, muni_assets in assets_by.items():
        muni_events = events_by.get(muni_key, [])
        if not muni_events:
            # No FEMA project here — assets are consistent by default.
            for a in muni_assets:
                findings.append(Finding(
                    finding_id=_finding_id(f"consistent::{a['asset_id']}"),
                    kind="consistent",
                    severity="info",
                    municipality=a.get("municipality", muni_key),
                    details=(
                        f"asset {a['asset_id']} (status={a.get('status')}) has no FEMA "
                        f"recovery project in {a.get('municipality')}"
                    ),
                    confidence=60,
                    asset_id=a["asset_id"],
                    asset_status=a.get("status"),
                ))
            continue

        for a in muni_assets:
            for ev in muni_events:
                step = _fema_step(ev)
                status = a.get("status")
                if status in {"damaged", "inactive"} and step in _CLOSED_STEPS:
                    findings.append(Finding(
                        finding_id=_finding_id(f"sm::{a['asset_id']}::{ev['event_id']}"),
                        kind="status_mismatch",
                        severity="critical",
                        municipality=a.get("municipality", muni_key),
                        details=(
                            f"asset {a['asset_id']} is {status} but FEMA project "
                            f"{ev['event_id']} (step={step!r}) is closed — the asset "
                            f"should be back in service per FEMA records"
                        ),
                        confidence=80,
                        asset_id=a["asset_id"],
                        event_id=ev["event_id"],
                        fema_step=step,
                        asset_status=status,
                    ))
                elif status == "active" and step in _IN_FLIGHT_STEPS:
                    findings.append(Finding(
                        finding_id=_finding_id(f"sa::{a['asset_id']}::{ev['event_id']}"),
                        kind="stale_asset",
                        severity="warn",
                        municipality=a.get("municipality", muni_key),
                        details=(
                            f"asset {a['asset_id']} is active but FEMA project "
                            f"{ev['event_id']} (step={step!r}) is still in flight — "
                            f"the asset may have outpaced the recovery paperwork"
                        ),
                        confidence=55,
                        asset_id=a["asset_id"],
                        event_id=ev["event_id"],
                        fema_step=step,
                        asset_status=status,
                    ))
                else:
                    findings.append(Finding(
                        finding_id=_finding_id(f"ok::{a['asset_id']}::{ev['event_id']}"),
                        kind="consistent",
                        severity="info",
                        municipality=a.get("municipality", muni_key),
                        details=(
                            f"asset {a['asset_id']} status={status} matches FEMA "
                            f"step={step!r} for event {ev['event_id']}"
                        ),
                        confidence=50,
                        asset_id=a["asset_id"],
                        event_id=ev["event_id"],
                        fema_step=step,
                        asset_status=status,
                    ))

    # --- missing_coverage (event side) ---
    for muni_key, muni_events in events_by.items():
        if muni_key in assets_by:
            continue
        muni_label = _event_municipality(muni_events[0]) or muni_key
        for ev in muni_events:
            findings.append(Finding(
                finding_id=_finding_id(f"mc::{ev['event_id']}"),
                kind="missing_coverage",
                severity="warn",
                municipality=muni_label,
                details=(
                    f"FEMA project {ev['event_id']} affects {muni_label}, but no "
                    f"utility_asset record was ingested for that municipality"
                ),
                confidence=70,
                event_id=ev["event_id"],
                fema_step=_fema_step(ev),
            ))

    summary = {
        "consistent_count": sum(1 for f in findings if f.kind == "consistent"),
        "status_mismatches": sum(1 for f in findings if f.kind == "status_mismatch"),
        "missing_coverage": sum(1 for f in findings if f.kind == "missing_coverage"),
        "stale_assets": sum(1 for f in findings if f.kind == "stale_asset"),
    }
    return findings, summary
