#!/usr/bin/env python3
"""Build data-driven AlertEvents across all domains and merge into data/alert_events.jsonl.

Generalises scripts/build_water_alerts.py: runs the full promoter registry
(:mod:`aguayluz.alert_promotion`) over the already-ingested signals, turning real
events into operational alerts —

  * CONTAMINATION / HYDRO_OPS  — water (EPA SDWIS + USGS reservoir levels)
  * SEISMIC_GEO                — USGS FDSN earthquakes (data/service_events.jsonl)
  * WEATHER_HAZARD             — NWS active hazard alerts (data/service_events.jsonl)
  * CONTAMINATION / HYDRO_OPS / WEATHER_HAZARD / TELECOM_SCADA
                               — NEON publication events (data/neon_publication_events.jsonl)

Idempotent merge: hand-authored seed alerts and any non-generated rows are kept;
previously-generated rows (alert_id containing any GENERATED_MARKERS substring —
_sdwis_ / _resvlow_ / _seismic_ / _weather_ / _osha_ / _neonpub_) are replaced on every run. Output is
sorted by alert_id for a stable diff.

The exporter (scripts/federation_export.py) projects data/alert_events.jsonl into the
canonical `alerts` stream, so no exporter change is needed for these to reach the Hub.

Offline-safe: reservoir input is optional; stdlib only + the local aguayluz package.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.alert_promotion import (  # noqa: E402
    GENERATED_MARKERS,
    build_all_alerts,
    load_geo,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _is_generated(alert_id: str) -> bool:
    return any(m in alert_id for m in GENERATED_MARKERS)


def merge(existing: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep seeds + any non-generated rows; replace previously-generated rows."""
    kept = [r for r in existing if not _is_generated(str(r.get("alert_id", "")))]
    by_id: dict[str, dict[str, Any]] = {r["alert_id"]: r for r in kept}
    for r in generated:
        by_id[r["alert_id"]] = r
    return sorted(by_id.values(), key=lambda r: r["alert_id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default="data/service_events.jsonl",
                    help="service events (source of CONTAMINATION/SEISMIC_GEO/WEATHER_HAZARD alerts)")
    ap.add_argument("--reservoir", default="data/reservoir_levels.jsonl",
                    help="USGS reservoir/river readings (HYDRO_OPS reservoir-low proxy); optional")
    ap.add_argument("--groundwater", default="data/groundwater_levels.jsonl",
                    help="USGS groundwater readings (HYDRO_OPS aquifer-drawdown proxy); optional")
    ap.add_argument("--coastal", default="data/coastal_levels.jsonl",
                    help="NOAA tide-gauge readings (HYDRO_OPS coastal high-water proxy); optional")
    ap.add_argument("--neon-events", default="data/neon_publication_events.jsonl",
                    help="NEON publication events (scripts/ingest_neon.py); optional")
    ap.add_argument("--geo", default="data/geo/pr_municipios.json",
                    help="municipio centroids for alert coordinates")
    ap.add_argument("--assets", default="data/utility_assets.jsonl",
                    help="utility assets (linked to each alert via sectors_impacted/linked_asset_ids)")
    ap.add_argument("--out", default="data/alert_events.jsonl")
    ap.add_argument("--percentile", type=float, default=10.0,
                    help="tail percentile for the level proxies (reservoir/aquifer/coastal)")
    args = ap.parse_args()

    events = _read_jsonl(REPO_ROOT / args.events)
    # One combined readings list across every water time-series; each HYDRO_OPS proxy
    # filters to the metrics it owns (reservoir/river, groundwater, coastal).
    readings = (
        _read_jsonl(REPO_ROOT / args.reservoir)
        + _read_jsonl(REPO_ROOT / args.groundwater)
        + _read_jsonl(REPO_ROOT / args.coastal)
    )
    assets = _read_jsonl(REPO_ROOT / args.assets)
    neon_events = _read_jsonl(REPO_ROOT / args.neon_events)
    geo_path = REPO_ROOT / args.geo
    geo_doc = json.loads(geo_path.read_text()) if geo_path.is_file() else {}
    geo = load_geo(geo_doc.get("municipios", []) if isinstance(geo_doc, dict) else geo_doc)

    alerts = build_all_alerts(
        events, readings, geo, assets,
        reservoir_percentile=args.percentile,
        neon_events=neon_events,
    )
    generated = [a.model_dump() for a in alerts]

    out = REPO_ROOT / args.out
    combined = merge(_read_jsonl(out), generated)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined))

    by_module: dict[str, int] = {}
    for a in generated:
        by_module[a["module_id"]] = by_module.get(a["module_id"], 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_module.items())) or "none"
    linked = sum(1 for a in generated if a.get("linked_asset_ids"))
    sectored = sum(1 for a in generated if a.get("sectors_impacted"))
    print(f"generated {len(generated)} alerts ({breakdown}); {len(combined)} total -> {out}")
    print(f"  linked to assets: {linked}/{len(generated)}; with sectors: {sectored}/{len(generated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
