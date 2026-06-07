"""Per-municipality aggregation for the federation hub dashboard.

Pure transformation: takes the four entity streams that drive operational
decisions (assets, events, reconciliation findings, watersheds) and projects
them onto a list of per-municipality dossiers. Uses M8's normalization rule
(`_normalize_municipality` from `reconciliation.py`) so 'Bayamon' === 'BAYAMON'
=== 'bayamón' across all four sources.

Records whose municipality can't be recognized go to a single `unattributed`
bucket rather than being silently dropped.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any

from .reconciliation import _event_municipality
from .reconciliation import _normalize_muni as _base_normalize_muni


def _normalize_muni(value: str | None) -> str:
    """M8's casefold + NFKD diacritic strip so 'bayamón' === 'Bayamon'."""
    cased = _base_normalize_muni(value)
    if not cased:
        return ""
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", cased) if not unicodedata.combining(c)
    )
    return stripped


def _assets_by_muni(assets: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Bucket assets by normalized municipality. Returns (buckets, unattributed_count)."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    unattrib = 0
    for a in assets:
        if not isinstance(a, dict):
            continue
        muni = _normalize_muni(a.get("municipality"))
        if not muni:
            unattrib += 1
            continue
        buckets.setdefault(muni, []).append(a)
    return buckets, unattrib


def _events_by_muni(events: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    unattrib = 0
    for e in events:
        if not isinstance(e, dict):
            continue
        muni = _normalize_muni(_event_municipality(e))
        if not muni:
            unattrib += 1
            continue
        buckets.setdefault(muni, []).append(e)
    return buckets, unattrib


def _findings_by_muni(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        if not isinstance(f, dict):
            continue
        muni = _normalize_muni(f.get("municipality"))
        if not muni:
            continue
        buckets.setdefault(muni, []).append(f)
    return buckets


def _watersheds_by_asset(watersheds: list[dict[str, Any]]) -> dict[str, float]:
    """Map asset_id → watershed area, since watershed records don't carry the
    municipality themselves (they reference the asset_id)."""
    out: dict[str, float] = {}
    for w in watersheds:
        if not isinstance(w, dict):
            continue
        asset_id = w.get("asset_id")
        if asset_id:
            try:
                out[asset_id] = float(w.get("area_sqkm") or 0.0)
            except (TypeError, ValueError):
                continue
    return out


def _display_municipality(muni_key: str, sample_records: list[dict[str, Any]]) -> str:
    """Recover the original-cased municipality name from the first record that
    carries it. Falls back to title-casing the normalized key."""
    for record in sample_records:
        for field in ("municipality", "affected_area"):
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                # affected_area is shaped 'County, PR — Category'; trim suffixes.
                head = value.split(",", 1)[0].split(" — ", 1)[0].strip()
                if head:
                    return head
    return muni_key.title()


def _summarize_municipality(
    *,
    muni_key: str,
    muni_assets: list[dict[str, Any]],
    muni_events: list[dict[str, Any]],
    muni_findings: list[dict[str, Any]],
    watersheds_by_asset: dict[str, float],
) -> dict[str, Any]:
    by_type = Counter(a.get("asset_type", "unknown") for a in muni_assets)
    status_mix = Counter(a.get("status", "unknown") for a in muni_assets)
    partial = sum(1 for a in muni_assets if a.get("attribute_coverage") == "partial")
    contradictions_warn = sum(1 for f in muni_findings if f.get("severity") == "warn")
    contradictions_critical = sum(1 for f in muni_findings if f.get("severity") == "critical")

    watershed_total = round(
        sum(watersheds_by_asset.get(a["asset_id"], 0.0) for a in muni_assets if a.get("asset_id")),
        3,
    )

    # "Active" event = anything not closed-out. The FEMA adapter writes
    # `step=...` into ServiceEvent.notes; we read it back.
    active_events = 0
    for e in muni_events:
        notes = (e.get("notes") or "").lower()
        if "step=project closed out" not in notes:
            active_events += 1

    # Top findings: critical first, warn second; cap at 3 for the dashboard.
    sorted_findings = sorted(
        muni_findings,
        key=lambda f: {"critical": 0, "warn": 1, "info": 2}.get(f.get("severity"), 3),
    )
    top_findings = []
    for f in sorted_findings[:3]:
        details = f.get("details") or "(no details)"
        if len(details) > 200:
            # 199 chars + "…" = 200 total (ellipsis is one character in Python).
            details = details[:199] + "…"
        top_findings.append({
            "kind": f.get("kind", "unknown"),
            "details": details,
            "severity": f.get("severity", "info"),
        })

    return {
        "municipality": _display_municipality(muni_key, muni_assets + muni_events),
        "asset_counts": {
            "by_type": dict(by_type),
            "total": len(muni_assets),
        },
        "asset_status_mix": dict(status_mix),
        "watershed_area_sqkm_total": watershed_total,
        "service_events_total": len(muni_events),
        "active_events": active_events,
        "contradictions_summary": {
            "warn": contradictions_warn,
            "critical": contradictions_critical,
        },
        "partial_coverage_count": partial,
        "top_findings": top_findings,
    }


def aggregate_by_municipality(
    *,
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    watersheds: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build per-municipality summaries + the unattributed counts.

    Returns `(summaries, unattributed)`. `summaries` is sorted by total asset
    count descending then alphabetically — the federation hub renders this in
    order so the highest-asset municipality appears first.
    """
    assets_by, unattrib_assets = _assets_by_muni(assets)
    events_by, unattrib_events = _events_by_muni(events)
    findings_by = _findings_by_muni(findings or [])
    sheds_by_asset = _watersheds_by_asset(watersheds or [])

    all_keys = set(assets_by) | set(events_by)
    summaries: list[dict[str, Any]] = []
    for key in all_keys:
        summary = _summarize_municipality(
            muni_key=key,
            muni_assets=assets_by.get(key, []),
            muni_events=events_by.get(key, []),
            muni_findings=findings_by.get(key, []),
            watersheds_by_asset=sheds_by_asset,
        )
        summaries.append(summary)

    summaries.sort(key=lambda s: (-s["asset_counts"]["total"], s["municipality"].lower()))

    return summaries, {
        "asset_total": unattrib_assets,
        "event_total": unattrib_events,
    }
