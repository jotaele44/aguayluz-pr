#!/usr/bin/env python3
"""Build local AguaYLuz water relationship graph and continuity risk records.

Inputs are already-normalized AguaYLuz JSONL streams. Output is intentionally
JSONL and additive; federation_export.py can continue exporting canonical streams,
while Hub consumers can ingest these water-specific edges as a typed extension.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def fid(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()[:16]}"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def norm(s: Any) -> str:
    return " ".join(str(s or "").strip().upper().split())


def edge(src: str, pred: str, dst: str, evidence: str, confidence: int = 75) -> dict[str, Any]:
    return {
        "relationship_id": fid("AYL_REL", src, pred, dst),
        "subject_id": src,
        "predicate": pred,
        "object_id": dst,
        "source_ref": evidence,
        "evidence_tier": "T2",
        "confidence": confidence,
    }


def build_graph(assets: list[dict[str, Any]], events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_muni: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_type = defaultdict(list)
    for a in assets:
        by_muni[norm(a.get("municipality"))].append(a)
        by_type[a.get("asset_subtype", "unknown")].append(a)
    edges: dict[str, dict[str, Any]] = {}
    for muni, rows in by_muni.items():
        if not muni:
            continue
        treatments = [a for a in rows if a.get("asset_subtype") in {"treatment_plant", "waterworks"}]
        wastewater = [a for a in rows if a.get("asset_subtype") == "wastewater_plant"]
        pumps = [a for a in rows if a.get("asset_subtype") == "pump_station"]
        dams = [a for a in rows if a.get("asset_subtype") in {"dam", "reservoir"}]
        canals = [a for a in rows if "canal" in str(a.get("asset_subtype"))]
        for p in pumps:
            for t in treatments[:8]:
                e = edge(p["asset_id"], "feeds_or_supports", t["asset_id"], "municipality_proximity")
                edges[e["relationship_id"]] = e
        for d in dams:
            for t in treatments[:8]:
                e = edge(d["asset_id"], "upstream_supply_context_for", t["asset_id"], "municipality_hydrologic_context")
                edges[e["relationship_id"]] = e
        for c in canals:
            for t in treatments[:8] + pumps[:8]:
                e = edge(c["asset_id"], "hydraulic_corridor_context_for", t["asset_id"], "canal_registry")
                edges[e["relationship_id"]] = e
        for ww in wastewater:
            for t in treatments[:8]:
                e = edge(ww["asset_id"], "shared_municipal_service_area", t["asset_id"], "municipality_proximity", 65)
                edges[e["relationship_id"]] = e
    water_events = [e for e in events if e.get("event_type") in {"water_quality_violation", "boil_water", "service_interruption", "outage"}]
    for ev in water_events:
        muni = norm(ev.get("municipality") or ev.get("affected_area"))
        for a in by_muni.get(muni, [])[:25]:
            if a.get("asset_type") in {"water", "wastewater"}:
                rel = edge(ev["event_id"], "affects_or_contextualizes", a["asset_id"], ev.get("source_ref", "service_events"), 70)
                edges[rel["relationship_id"]] = rel

    risks: list[dict[str, Any]] = []
    event_counts = Counter(norm(e.get("municipality") or e.get("affected_area")) for e in water_events)
    for muni, rows in by_muni.items():
        if not muni or muni == "PUERTO RICO":
            continue
        asset_counts = Counter(a.get("asset_subtype") for a in rows)
        score = min(100, event_counts[muni] * 3 + asset_counts["dam"] * 8 + asset_counts["pump_station"] * 4 + asset_counts["wastewater_plant"] * 5)
        if score <= 0:
            continue
        risks.append({
            "risk_id": fid("AYL_RISK", muni),
            "municipality": muni.title(),
            "risk_type": "water_continuity",
            "risk_score": score,
            "drivers": {
                "water_events": event_counts[muni],
                "dams": asset_counts["dam"],
                "pump_stations": asset_counts["pump_station"],
                "wastewater_plants": asset_counts["wastewater_plant"],
                "treatment_or_waterworks": asset_counts["treatment_plant"] + asset_counts["waterworks"],
            },
            "evidence_tier": "T2",
            "confidence": 70 if event_counts[muni] else 55,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        })
    return sorted(edges.values(), key=lambda r: r["relationship_id"]), sorted(risks, key=lambda r: (-r["risk_score"], r["municipality"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", type=Path, default=DATA / "utility_assets.jsonl")
    ap.add_argument("--events", type=Path, default=DATA / "service_events.jsonl")
    ap.add_argument("--relationships-out", type=Path, default=DATA / "water_relationships.jsonl")
    ap.add_argument("--risks-out", type=Path, default=DATA / "continuity_risks.jsonl")
    args = ap.parse_args()
    relationships, risks = build_graph(load_jsonl(args.assets), load_jsonl(args.events))
    write_jsonl(args.relationships_out, relationships)
    write_jsonl(args.risks_out, risks)
    print(f"wrote {len(relationships)} water relationships -> {args.relationships_out}")
    print(f"wrote {len(risks)} continuity risks -> {args.risks_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
