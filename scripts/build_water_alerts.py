#!/usr/bin/env python3
"""Build data-driven water AlertEvents and merge them into data/alert_events.jsonl.

Projects the producer's real, already-ingested water signals into the operational
alert layer (see :mod:`aguayluz.water_alerts`):

  * EPA SDWIS boil-water advisories + health-based water-quality violations
    (data/service_events.jsonl, T1) -> CONTAMINATION alerts.
  * USGS daily reservoir readings (data/reservoir_levels.jsonl, T1) -> HYDRO_OPS
    reservoir-low alerts (statistical proxy, T2/needs_review).

Idempotent merge: hand-authored seed alerts and any non-generated rows are kept;
previously-generated rows (alert_id containing ``_sdwis_`` or ``_resvlow_``) are
replaced on every run. Output is sorted by alert_id for a stable diff.

The exporter (scripts/federation_export.py) already projects data/alert_events.jsonl
into the canonical ``alerts`` stream, so no exporter change is needed for these to
reach the Hub.

Offline-safe: reservoir input is optional (it is a network-derived, uncommitted
file); when absent, only CONTAMINATION alerts are produced. Stdlib only + the local
aguayluz package.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python scripts/build_water_alerts.py` from a fresh clone without an
# editable install (mirrors scripts/federation_export.py).
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.water_alerts import build_water_alerts, load_geo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# Markers identifying alert rows produced by this generator (so re-runs are clean).
_GENERATED_MARKERS = ("_sdwis_", "_resvlow_")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _is_generated(alert_id: str) -> bool:
    return any(m in alert_id for m in _GENERATED_MARKERS)


def merge(existing: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep seeds + any non-generated rows; replace previously-generated rows."""
    kept = [r for r in existing if not _is_generated(str(r.get("alert_id", "")))]
    by_id: dict[str, dict[str, Any]] = {r["alert_id"]: r for r in kept}
    for r in generated:
        by_id[r["alert_id"]] = r
    return sorted(by_id.values(), key=lambda r: r["alert_id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", default="data/service_events.jsonl",
                    help="SDWIS/PREPS service events (source of CONTAMINATION alerts)")
    ap.add_argument("--reservoir", default="data/reservoir_levels.jsonl",
                    help="USGS reservoir readings (source of HYDRO_OPS proxy alerts); optional")
    ap.add_argument("--geo", default="data/geo/pr_municipios.json",
                    help="municipio centroids for alert coordinates")
    ap.add_argument("--out", default="data/alert_events.jsonl")
    ap.add_argument("--percentile", type=float, default=10.0,
                    help="lower-tail percentile for the reservoir-low proxy")
    args = ap.parse_args()

    events = _read_jsonl(REPO_ROOT / args.events)
    readings = _read_jsonl(REPO_ROOT / args.reservoir)
    geo_doc = json.loads((REPO_ROOT / args.geo).read_text()) if (REPO_ROOT / args.geo).is_file() else {}
    geo = load_geo(geo_doc.get("municipios", []) if isinstance(geo_doc, dict) else geo_doc)

    alerts = build_water_alerts(events, readings, geo, reservoir_percentile=args.percentile)
    generated = [a.model_dump() for a in alerts]

    out = REPO_ROOT / args.out
    combined = merge(_read_jsonl(out), generated)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined))

    contam = sum(1 for a in generated if "_sdwis_" in a["alert_id"])
    resv = sum(1 for a in generated if "_resvlow_" in a["alert_id"])
    print(
        f"generated {len(generated)} water alerts "
        f"(CONTAMINATION={contam}, HYDRO_OPS reservoir-low={resv}); "
        f"{len(combined)} total -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
