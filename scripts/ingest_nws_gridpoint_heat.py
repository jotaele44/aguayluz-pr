#!/usr/bin/env python3
"""NWS gridded heat index at each municipio's internal point → outdoor-conditions layer.

For each of the 78 municipios, ``GET /gridpoints/{wfo}/{x},{y}`` for the grid cell frozen
in ``data/reference/outdoor_reference.v1.json`` (the cell holding the Census internal
point). Each response is SHA-256-frozen; :mod:`aguayluz.hazard_adapters.nws_heat` keeps
the maximum heat index, wet-bulb globe temperature and air temperature over the next 24
and 48 hours, in °F, banded on the NWS heat-index chart.

Arithmetic: SOURCE = municipios queried = RETAINED (a heat-index value in the window) +
UNRESOLVED. A municipio whose request fails keeps its previous summary, marked
``carried_forward``; every request failing fails the run.

State only: ``data/outdoor_heat_state.jsonl``. No alerts: WFO San Juan's Heat Advisories
arrive through ``scripts/ingest_nws_alerts.py``.

Usage:
    python scripts/ingest_nws_gridpoint_heat.py              # live, keyless (78 requests)
    python scripts/ingest_nws_gridpoint_heat.py --dry-run
    python scripts/ingest_nws_gridpoint_heat.py --src tests/fixtures/outdoor/nws_grid/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.hazard_adapters import nws_heat as adapter  # noqa: E402
from aguayluz.hazard_plane import EvidenceClass, source_arithmetic  # noqa: E402
from aguayluz.hydromet import store  # noqa: E402
from aguayluz.outdoor import state_path  # noqa: E402
from aguayluz.outdoor.runner import AcquisitionError, Built, RunContext, iso, run_ingest  # noqa: E402

SOURCE_ID = "nws_gridpoint_heat"
SOURCE_SYSTEM = "api.weather.gov gridpoints (forecastGridData)"


def _key(cell: dict) -> str:
    return f"grid_{cell['grid_id']}_{cell['grid_x']}_{cell['grid_y']}.json"


def _targets(ctx: RunContext) -> list[dict]:
    rows = [r for r in ctx.reference.get("gridpoints", []) if r.get("grid_id")]
    if ctx.offline and ctx.args.src.is_dir():
        rows = [r for r in rows if (ctx.args.src / _key(r)).is_file()]
    return rows


def acquire(ctx: RunContext) -> None:
    targets = _targets(ctx)
    if not targets:
        raise AcquisitionError("no municipio gridpoints in the reference file (or offline directory)")
    seen: set[str] = set()
    for cell in targets:
        key = _key(cell)
        if key in seen:
            continue
        seen.add(key)
        url = ctx.source["endpoints"]["grid"].format(grid_id=cell["grid_id"], x=cell["grid_x"],
                                                     y=cell["grid_y"])
        ctx.try_get(url, key=key, record_id=f"gridpoints/{cell['grid_id']}/{cell['grid_x']},{cell['grid_y']}",
                    headers={"Accept": "application/geo+json"})
    if not ctx.responses:
        first = next(iter(ctx.failures.values()), "no response")
        raise AcquisitionError(f"all {len(seen)} gridpoint requests failed; first: {first}")


def build(ctx: RunContext, responses: list) -> Built:
    by_key = {r.key: r for r in responses}
    previous = {r["geoid"]: r for r in store.read_jsonl(state_path(SOURCE_ID, ctx.paths.data_dir))}
    built = Built(arithmetic={})
    retained = unresolved = 0
    carried: list[str] = []
    bands: dict[str, int] = {}
    targets = _targets(ctx)
    for cell in targets:
        response = by_key.get(_key(cell))
        summary = None
        if response is not None:
            doc = json.loads(response.payload)
            summary = adapter.summarize((doc or {}).get("properties") or {}, ctx.now)
        if summary is None or summary["heat_index_max_f_24h"] is None:
            unresolved += 1
            prior = previous.get(cell["geoid"])
            if prior and prior.get("manifestation_id"):
                built.state_rows.append({**prior, "carried_forward": True})
                built.referenced.add(prior["manifestation_id"])
                carried.append(cell["name"])
            continue
        retained += 1
        bands[summary["heat_band_24h"]] = bands.get(summary["heat_band_24h"], 0) + 1
        built.state_rows.append({
            "geoid": cell["geoid"],
            "municipio": cell["name"],
            "grid_id": cell["grid_id"],
            "grid_x": cell["grid_x"],
            "grid_y": cell["grid_y"],
            "lat": cell["lat"],
            "lon": cell["lon"],
            **summary,
            "window_start": iso(ctx.now),
            "binding_evidence": EvidenceClass.POINT_IN_POLYGON.value,
            "binding_method": "ndfd_cell_holding_census_internal_point",
            "geometry_precision": "REPRESENTATIVE_POINT",
            "manifestation_id": response.manifestation.manifestation_id,
            "retrieved_at": iso(ctx.now),
            "carried_forward": False,
        })
        built.referenced.add(response.manifestation.manifestation_id)
    built.state_rows.sort(key=lambda r: r["geoid"])
    built.arithmetic = source_arithmetic(len(targets), retained, 0, unresolved)
    built.counts = {
        "municipios_queried": len(targets),
        "heat_bands_24h": dict(sorted(bands.items())),
        "carried_forward": carried,
    }
    peak = max((r["heat_index_max_f_24h"] for r in built.state_rows
                if r.get("heat_index_max_f_24h") is not None), default=None)
    built.message = (f"NWS heat: {retained}/{len(targets)} municipios, peak 24 h heat index "
                     f"{peak} °F, bands {dict(sorted(bands.items()))}, {unresolved} unresolved")
    return built


def main(argv: list[str] | None = None) -> int:
    return run_ingest(source_id=SOURCE_ID, authority=adapter.SOURCE_AUTHORITY,
                      system=SOURCE_SYSTEM, argv=argv, description=__doc__.split("\n\n")[0],
                      acquire=acquire, build=build)


if __name__ == "__main__":
    raise SystemExit(main())
