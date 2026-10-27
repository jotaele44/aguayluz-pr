#!/usr/bin/env python3
"""NDBC/CARICOOS buoy observations around Puerto Rico → outdoor-conditions layer.

One request per run: NDBC's ``latest_obs.txt`` (the newest report from every station it
distributes, ~100 KB), SHA-256-frozen before parsing, filtered to the Puerto Rico buoys
listed in the registry entry (``stations``). Arithmetic: SOURCE = every data row =
RETAINED (listed PR buoys) + EXCLUDED (all other stations) + UNRESOLVED (rows that do
not parse). A listed buoy missing from the file is reported, not invented.

State only: the current observation per buoy is rewritten into
``data/outdoor_buoy_state.jsonl``. An observation older than
``observation_stale_after_seconds`` is flagged ``stale`` rather than dropped.

Usage:
    python scripts/ingest_ndbc_buoys.py              # live, keyless
    python scripts/ingest_ndbc_buoys.py --dry-run
    python scripts/ingest_ndbc_buoys.py --src tests/fixtures/outdoor/ndbc_latest_obs.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.hazard_adapters import ndbc_buoys as adapter  # noqa: E402
from aguayluz.hazard_plane import source_arithmetic  # noqa: E402
from aguayluz.outdoor.runner import Built, RunContext, iso, run_ingest  # noqa: E402

SOURCE_ID = "ndbc_buoys"
SOURCE_SYSTEM = "NDBC latest_obs.txt"
KEY = "ndbc_latest_obs.txt"


def acquire(ctx: RunContext) -> None:
    ctx.get(ctx.source["endpoints"]["latest_obs"], key=KEY, record_id="data/latest_obs/latest_obs.txt",
            extension="txt")


def build(ctx: RunContext, responses: list) -> Built:
    response = responses[0]
    columns, rows, malformed = adapter.parse_latest_obs(response.payload.decode("utf-8", "replace"))
    wanted = [str(s) for s in ctx.source.get("stations") or adapter.STATIONS]
    stale_after = float(ctx.source.get("observation_stale_after_seconds") or 10800)
    manifestation_id = response.manifestation.manifestation_id

    built = Built(arithmetic={})
    found: set[str] = set()
    for parts in rows:
        row = dict(zip(columns, parts, strict=True))
        station = row["STN"].upper()
        if station not in wanted:
            continue
        found.add(station)
        when = adapter.observed_at(row)
        meta = adapter.STATIONS.get(station, {})
        age = (ctx.now - when).total_seconds() if when else None
        built.state_rows.append({
            "station": station,
            "name": meta.get("name"),
            "lat": float(row["LAT"]),
            "lon": float(row["LON"]),
            "observed_at": iso(when) if when else None,
            "observation_age_seconds": round(age) if age is not None else None,
            "stale": age is None or age > stale_after,
            "observed": adapter.normalize_row(row),
            "raw": {k: v for k, v in row.items() if k not in {"STN", "LAT", "LON"}},
            "binding_evidence": "UNRESOLVED",
            "binding_method": "offshore_point_not_bound_to_a_municipio",
            "manifestation_id": manifestation_id,
            "retrieved_at": iso(ctx.now),
        })
    retained = len(built.state_rows)
    built.state_rows.sort(key=lambda r: r["station"])
    built.referenced = {manifestation_id}
    built.arithmetic = source_arithmetic(len(rows) + len(malformed), retained,
                                         len(rows) - retained, len(malformed))
    missing = sorted(set(wanted) - found)
    with_waves = [r["station"] for r in built.state_rows if r["observed"]["wave_height_m"] is not None]
    built.counts = {
        "stations_wanted": wanted,
        "stations_missing": missing,
        "stations_with_wave_height": with_waves,
        "stations_stale": [r["station"] for r in built.state_rows if r["stale"]],
    }
    built.message = (f"NDBC: {retained}/{len(wanted)} PR buoys in latest_obs "
                     f"({len(rows)} stations), wave height from {with_waves or 'none'}"
                     + (f", missing {missing}" if missing else ""))
    return built


def main(argv: list[str] | None = None) -> int:
    return run_ingest(source_id=SOURCE_ID, authority=adapter.SOURCE_AUTHORITY,
                      system=SOURCE_SYSTEM, argv=argv, description=__doc__.split("\n\n")[0],
                      acquire=acquire, build=build)


if __name__ == "__main__":
    raise SystemExit(main())
