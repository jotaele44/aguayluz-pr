#!/usr/bin/env python3
"""AirNow current air quality around Puerto Rico → outdoor-conditions layer.

Needs an AirNow API key in ``AIRNOW_API_KEY`` (free, https://docs.airnowapi.org/). With
no key and no ``--src``, the ingest prints why and exits 0 **without writing a
receipt**, so the source reads NEVER on the NWS Hydromet page rather than FAILED — the
same stance ``scripts/ingest_neon_products.py`` takes without ``NEON_API_TOKEN``. The
key is passed as a query parameter and is redacted from every manifestation, receipt
and log line.

Per run, one ``observation/latLong/current`` request per registry query point (San Juan,
Ponce, Mayagüez, Arecibo, Humacao, Guayama; ``distance_miles`` radius), each
SHA-256-frozen. Rows are de-duplicated by reporting area and pollutant. Arithmetic:
SOURCE = every row returned = RETAINED (PR, unique) + EXCLUDED (other states, repeats)
+ UNRESOLVED (no area, pollutant or AQI).

State only: ``data/outdoor_aqi_state.jsonl``.

NOTE: built and tested against a fixture constructed from AirNow's documented response
format; the live path has not run here, because no key was available when it was
written.

Usage:
    AIRNOW_API_KEY=... python scripts/ingest_airnow.py
    python scripts/ingest_airnow.py --src tests/fixtures/outdoor/airnow/
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.hazard_adapters import airnow as adapter  # noqa: E402
from aguayluz.hazard_plane import source_arithmetic  # noqa: E402
from aguayluz.outdoor.runner import AcquisitionError, Built, RunContext, iso, run_ingest  # noqa: E402

SOURCE_ID = "airnow"
SOURCE_SYSTEM = "AirNow API (observation/latLong/current)"
ENV_KEY = "AIRNOW_API_KEY"


def _key(index: int) -> str:
    return f"airnow_{index}.json"


def preflight(args) -> str | None:
    if args.src is None and not os.environ.get(ENV_KEY, "").strip():
        return (f"{ENV_KEY} not set. AirNow's API needs a (free) key: "
                "https://docs.airnowapi.org/ ; add it as the AIRNOW_API_KEY repository secret, "
                "or pass --src to run offline.")
    return None


def acquire(ctx: RunContext) -> None:
    points = ctx.source.get("query_points") or []
    if not points:
        raise AcquisitionError("registry entry lists no query_points")
    api_key = os.environ.get(ENV_KEY, "").strip()
    for index, point in enumerate(points):
        if ctx.offline and ctx.args.src.is_dir() and not (ctx.args.src / _key(index)).is_file():
            continue
        params = {"format": "application/json", "latitude": point["lat"],
                  "longitude": point["lon"], "distance": ctx.source.get("distance_miles", 50),
                  "API_KEY": api_key}
        ctx.try_get(ctx.source["endpoints"]["current"], key=_key(index), params=params,
                    record_id=f"observation/latLong/current@{point['label']}",
                    redact_query=("API_KEY",))
    if not ctx.responses:
        first = next(iter(ctx.failures.values()), "no response")
        raise AcquisitionError(f"every AirNow request failed; first: {first}")


def build(ctx: RunContext, responses: list) -> Built:
    built = Built(arithmetic={})
    total = retained = excluded = unresolved = 0
    outcomes: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for response in responses:
        rows = json.loads(response.payload)
        if not isinstance(rows, list):
            raise ValueError(f"{response.key}: AirNow response is not a list")
        for row in rows:
            total += 1
            outcome = adapter.classify(row)
            if outcome == "retained":
                key = (str(row["ReportingArea"]), str(row["ParameterName"]))
                if key in seen:
                    outcome = "excluded:repeat_from_another_query_point"
                else:
                    seen.add(key)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if outcome.startswith("excluded"):
                excluded += 1
                continue
            if outcome.startswith("unresolved"):
                unresolved += 1
                continue
            retained += 1
            when = adapter.observed_at(row)
            built.state_rows.append({
                "reporting_area": row["ReportingArea"],
                "parameter": row["ParameterName"],
                "aqi": row["AQI"],
                "category": adapter.category(row),
                "category_raw": row.get("Category"),
                "lat": row.get("Latitude"),
                "lon": row.get("Longitude"),
                "observed_at": iso(when) if when else None,
                "binding_evidence": "UNRESOLVED",
                "binding_method": "reporting_area_point_not_bound_to_a_municipio",
                "manifestation_id": response.manifestation.manifestation_id,
                "retrieved_at": iso(ctx.now),
            })
            built.referenced.add(response.manifestation.manifestation_id)
    built.state_rows.sort(key=lambda r: (r["reporting_area"], r["parameter"]))
    built.arithmetic = source_arithmetic(total, retained, excluded, unresolved)
    worst = max(built.state_rows, key=lambda r: r["aqi"], default=None)
    built.counts = {
        "outcomes": dict(sorted(outcomes.items())),
        "reporting_areas": sorted({r["reporting_area"] for r in built.state_rows}),
        "worst": {k: worst[k] for k in ("reporting_area", "parameter", "aqi", "category")} if worst else None,
    }
    built.message = (f"AirNow: {retained} PR area/pollutant row(s) from {len(responses)} request(s); "
                     f"worst {built.counts['worst']}")
    return built


def main(argv: list[str] | None = None) -> int:
    return run_ingest(source_id=SOURCE_ID, authority=adapter.SOURCE_AUTHORITY,
                      system=SOURCE_SYSTEM, argv=argv, description=__doc__.split("\n\n")[0],
                      acquire=acquire, build=build, preflight=preflight)


if __name__ == "__main__":
    raise SystemExit(main())
