"""Build per-receiver federation handoff payloads.

Each linked module in `config/federation_manifest.yaml` declares a concern
(funding, subsurface, dashboard…). We project AguaYLuz records into a payload
tailored to that concern so the receiver can join on cross-module keys
without re-deriving anything.

Tailoring rules (per the skill spec's 'Does Not Own' table):
  - moneysweep-pr   : FEMA disaster numbers + dollar fields from event notes
  - spiderweb-pr    : NHDPlus COMIDs/reachcodes + watershed bounds
  - thehub-pr       : sanitized summary + warn+critical contradictions
  - skywatcher-pr   : asset count + municipalities (airspace correlation only)
  - ovnis-pr        : asset count + municipalities (sighting correlation only)
  - default         : minimum viable join_keys (municipality + asset_id)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

DEFAULT_CONFIDENCE_FLOOR = 50
HANDOFF_VECTOR = "AGUAYLUZ_EMIT_FEDERATION_HANDOFFS"


_DISASTER_RE = re.compile(r"fema_(\d+)_pw")


def _disaster_number(event_id: str) -> str | None:
    m = _DISASTER_RE.search(event_id or "")
    return m.group(1) if m else None


def _time_window(events: list[dict[str, Any]]) -> dict[str, str] | None:
    times = [e.get("start_time") for e in events if e.get("start_time")]
    times = [t for t in times if isinstance(t, str) and len(t) >= 10]
    if not times:
        return None
    earliest = min(t[:10] for t in times)
    latest = max(t[:10] for t in times)
    return {"from": earliest, "to": latest}


def _join_keys_for(
    target: str,
    *,
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    keys: list[dict[str, Any]] = []
    if target == "moneysweep-pr":
        for ev in events:
            d = _disaster_number(ev.get("event_id", ""))
            if d:
                keys.append({
                    "key_type": "fema_disaster_number",
                    "value": d,
                    "asset_id": None,
                    "event_id": ev["event_id"],
                })
    elif target == "spiderweb-pr":
        for a in assets:
            if a.get("comid") is not None:
                keys.append({
                    "key_type": "comid",
                    "value": str(a["comid"]),
                    "asset_id": a["asset_id"],
                    "event_id": None,
                })
            if a.get("reachcode"):
                keys.append({
                    "key_type": "reachcode",
                    "value": str(a["reachcode"]),
                    "asset_id": a["asset_id"],
                    "event_id": None,
                })
    else:
        # Default: municipality joins keep the receiver honest about geography
        # without requiring NHDPlus knowledge.
        seen: set[tuple[str, str]] = set()
        for a in assets:
            muni = a.get("municipality")
            if muni and (muni, a["asset_id"]) not in seen:
                keys.append({
                    "key_type": "municipality",
                    "value": muni,
                    "asset_id": a["asset_id"],
                    "event_id": None,
                })
                seen.add((muni, a["asset_id"]))
    return keys


def _payload_for(
    target: str,
    *,
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    watersheds: list[dict[str, Any]] | None,
    bridge_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    if target == "moneysweep-pr":
        # Pull FEMA dollar amounts out of the event notes when present.
        events_with_money: list[dict[str, Any]] = []
        for ev in events:
            disaster = _disaster_number(ev.get("event_id", ""))
            if not disaster:
                continue
            events_with_money.append({
                "event_id": ev["event_id"],
                "affected_area": ev.get("affected_area"),
                "fema_disaster_number": disaster,
                "review_status": ev.get("review_status"),
                "notes": ev.get("notes"),
            })
        return {"fema_events": events_with_money}

    if target == "spiderweb-pr":
        watershed_summaries = [
            {
                "asset_id": w["asset_id"],
                "nhdplus_id": w.get("nhdplus_id"),
                "area_sqkm": w.get("area_sqkm"),
                "bounds_bbox": w.get("bounds_bbox"),
            }
            for w in (watersheds or [])
        ]
        return {
            "nhdplus_assets": [
                {
                    "asset_id": a["asset_id"],
                    "comid": a.get("comid"),
                    "reachcode": a.get("reachcode"),
                    "vpuid": a.get("vpuid"),
                    "attribute_coverage": a.get("attribute_coverage"),
                }
                for a in assets
                if a.get("comid") is not None or a.get("reachcode")
            ],
            "watersheds": watershed_summaries,
        }

    if target == "thehub-pr":
        critical_or_warn = [
            f for f in findings
            if f.get("severity") in ("warn", "critical")
        ]
        return {
            "bridge_summary": bridge_summary or {},
            "contradictions": [
                {
                    "finding_id": f["finding_id"],
                    "kind": f["kind"],
                    "severity": f["severity"],
                    "municipality": f.get("municipality"),
                    "details": f.get("details"),
                }
                for f in critical_or_warn
            ],
        }

    # Default lightweight payload — just enough for correlation.
    municipalities = sorted({a["municipality"] for a in assets if a.get("municipality")})
    return {
        "asset_count": len(assets),
        "event_count": len(events),
        "municipalities": municipalities,
    }


def build_handoff_payload(
    target: str,
    *,
    run_id: str,
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    watersheds: list[dict[str, Any]] | None = None,
    bridge_summary: dict[str, Any] | None = None,
    confidence_floor: int = DEFAULT_CONFIDENCE_FLOOR,
    vector: str = HANDOFF_VECTOR,
) -> dict[str, Any]:
    """Build a FederationHandoff dict for `target` from the current outputs."""
    keys = _join_keys_for(target, assets=assets, events=events)
    payload = _payload_for(
        target,
        assets=assets,
        events=events,
        findings=findings or [],
        watersheds=watersheds,
        bridge_summary=bridge_summary,
    )
    return {
        "module_id": "aguayluz-pr",
        "target_module_id": target,
        "run_id": run_id,
        "vector": vector,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_window": _time_window(events),
        "confidence_floor": confidence_floor,
        "join_keys": keys,
        "payload": payload,
    }
