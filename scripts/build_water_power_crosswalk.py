#!/usr/bin/env python3
"""Build the water<->power dependency crosswalk (closes GAP-003).

The alert framework's dependency graph shipped a null placeholder
(``EDGE-POWER-PUMP-SEED``: ``from_node_id=null``, ``to_node_id=null``) and
``data/alert_gaps.jsonl`` flagged GAP-003 (blocking): "Pump/WTP power feed mapping
absent." Power-drawing water assets — pumping stations, water/wastewater treatment
plants — depend on a nearby power feed, so a LUMA/PREPA outage there is a water
service risk. The authoritative feeder-to-asset map is a non-public utility dataset,
so this builds a **spatial proxy**: each power-drawing water asset is linked to its
nearest power asset (``energizes`` edge), with confidence scaled by distance and
``evidence_required=True`` so a reviewer can confirm the feed.

Provenance honesty: these are proximity inferences, not confirmed electrical
connections. Confidence tops out below the T1 band and every edge carries
``evidence_required``. The T1 unblock (a real feeder map) is recorded in
docs/ROAD_TO_100.md.

Reads/writes ``data/utility_assets.jsonl`` (assets) and
``data/alert_dependency_edges.jsonl`` (edges); flips GAP-003 to ``closed`` in
``data/alert_gaps.jsonl``. Deterministic, idempotent, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Water/wastewater subtypes that draw electrical power (substring match, lowercased).
_POWER_DRAWING = ("pumping_station", "pump", "treatment", "wtp")

# Distance model: within NEAR_KM confidence is highest; beyond FAR_KM an asset is
# considered to have no credible nearby feed and no edge is emitted.
_NEAR_KM = 2.0
_FAR_KM = 15.0
_CONF_NEAR = 55  # proxy ceiling — stays below the T1 (>=80) band on purpose
_CONF_FAR = 20

# Marker identifying edges produced by this generator (idempotent re-runs).
_EDGE_PREFIX = "EDGE-WP-"
_GAP_ID = "GAP-003"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _has_coords(a: dict[str, Any]) -> bool:
    return isinstance(a.get("lat"), (int, float)) and isinstance(a.get("lon"), (int, float))


def _is_power_drawing(a: dict[str, Any]) -> bool:
    if a.get("asset_type") not in ("water", "wastewater"):
        return False
    sub = (a.get("asset_subtype") or "").lower()
    return any(k in sub for k in _POWER_DRAWING)


def _confidence_for(dist_km: float) -> int:
    """Linearly fade proxy confidence from _CONF_NEAR (<=_NEAR_KM) to _CONF_FAR (>=_FAR_KM)."""
    if dist_km <= _NEAR_KM:
        return _CONF_NEAR
    if dist_km >= _FAR_KM:
        return _CONF_FAR
    frac = (dist_km - _NEAR_KM) / (_FAR_KM - _NEAR_KM)
    return int(round(_CONF_NEAR - frac * (_CONF_NEAR - _CONF_FAR)))


def build_edges(assets: list[dict[str, Any]], far_km: float = _FAR_KM) -> list[dict[str, Any]]:
    """One `energizes` edge per power-drawing water asset -> its nearest power asset."""
    powers = [a for a in assets if a.get("asset_type") == "power" and _has_coords(a)]
    if not powers:
        return []
    edges: list[dict[str, Any]] = []
    for w in assets:
        if not _is_power_drawing(w) or not _has_coords(w):
            continue
        wlat, wlon = float(w["lat"]), float(w["lon"])
        nearest = min(powers, key=lambda p: haversine_km(wlat, wlon, float(p["lat"]), float(p["lon"])))
        dist = haversine_km(wlat, wlon, float(nearest["lat"]), float(nearest["lon"]))
        if dist > far_km:
            continue  # no credible nearby feed
        edges.append({
            "edge_id": f"{_EDGE_PREFIX}{w['asset_id']}",
            "from_node_type": "power_node",
            "from_node_id": nearest["asset_id"],
            "to_node_type": "hydro_asset",
            "to_node_id": w["asset_id"],
            "dependency_type": "energizes",
            "confidence": _confidence_for(dist),
            "evidence_required": True,
            "notes": (
                f"Spatial proxy: nearest power asset '{nearest.get('asset_name', nearest['asset_id'])}' "
                f"is {dist:.2f} km from '{w.get('asset_name', w['asset_id'])}' "
                f"({w.get('asset_subtype')}). Confirm feeder assignment — proximity, not a verified circuit."
            ),
        })
    return sorted(edges, key=lambda e: e["edge_id"])


def merge_edges(existing: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the null EDGE-POWER-PUMP-SEED placeholder + prior generated edges; keep the rest."""
    kept = [
        e for e in existing
        if not str(e.get("edge_id", "")).startswith(_EDGE_PREFIX)
        and e.get("edge_id") != "EDGE-POWER-PUMP-SEED"
    ]
    return kept + generated


def _close_gap(gaps: list[dict[str, Any]], n_edges: int) -> list[dict[str, Any]]:
    for g in gaps:
        if g.get("gap_id") == _GAP_ID:
            g["status"] = "closed"
            g["next_action"] = (
                f"Crosswalk built: {n_edges} spatial power_feed edges "
                "(scripts/build_water_power_crosswalk.py). T1 unblock: real utility feeder map."
            )
    return gaps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", default="data/utility_assets.jsonl")
    ap.add_argument("--edges", default="data/alert_dependency_edges.jsonl")
    ap.add_argument("--gaps", default="data/alert_gaps.jsonl")
    ap.add_argument("--far-km", type=float, default=_FAR_KM)
    args = ap.parse_args()

    assets = _read_jsonl(REPO_ROOT / args.assets)
    generated = build_edges(assets, far_km=args.far_km)

    edges_path = REPO_ROOT / args.edges
    combined = merge_edges(_read_jsonl(edges_path), generated)
    _write_jsonl(edges_path, combined)

    gaps_path = REPO_ROOT / args.gaps
    gaps = _read_jsonl(gaps_path)
    if gaps:
        _write_jsonl(gaps_path, _close_gap(gaps, len(generated)))

    print(
        f"generated {len(generated)} water<->power `energizes` edges "
        f"({len(combined)} total) -> {edges_path}; GAP-003 -> closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
