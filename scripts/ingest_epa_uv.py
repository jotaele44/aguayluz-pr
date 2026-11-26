#!/usr/bin/env python3
"""EPA UV index forecast, one ZIP per municipio → outdoor-conditions layer.

EPA publishes the daily maximum UV index per ZIP code (``getEnvirofactsUVDAILY``),
computed from the NWS Climate Prediction Center forecast grid — so ZIPs across Puerto
Rico differ (Humacao 8, Adjuntas 9, Aguada 10 on the day this was written), and a
per-municipio value is real rather than one island-wide number.

Each municipio is queried by the ZIP frozen for it in
``data/reference/outdoor_reference.v1.json`` (the ZCTA with the largest land area in
the municipio, from the Census 2020 ZCTA–county relationship file). Every response is
SHA-256-frozen. Arithmetic: SOURCE = municipios queried = RETAINED (a PR row with an
index) + UNRESOLVED (no row, no index, or the request failed). One ZIP failing does not
fail the run — its previous forecast is carried forward, marked ``carried_forward`` —
and every request failing does.

State only: ``data/outdoor_uv_state.jsonl``, one row per municipio.

Usage:
    python scripts/ingest_epa_uv.py              # live, keyless (78 requests)
    python scripts/ingest_epa_uv.py --dry-run
    python scripts/ingest_epa_uv.py --src tests/fixtures/outdoor/epa_uv/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.hazard_adapters import epa_uv as adapter  # noqa: E402
from aguayluz.hazard_plane import EvidenceClass, source_arithmetic  # noqa: E402
from aguayluz.hydromet import store  # noqa: E402
from aguayluz.outdoor import municipio_key, state_path  # noqa: E402
from aguayluz.outdoor.runner import AcquisitionError, Built, RunContext, iso, run_ingest  # noqa: E402

SOURCE_ID = "epa_uv"
SOURCE_SYSTEM = "EPA Envirofacts UV (getEnvirofactsUVDAILY)"


def _key(zip_code: str) -> str:
    return f"uv_{zip_code}.json"


def _targets(ctx: RunContext) -> list[dict]:
    rows = [r for r in ctx.reference.get("uv_zips", []) if r.get("zip")]
    if ctx.offline and ctx.args.src.is_dir():
        rows = [r for r in rows if (ctx.args.src / _key(r["zip"])).is_file()]
    return rows


def acquire(ctx: RunContext) -> None:
    targets = _targets(ctx)
    if not targets:
        raise AcquisitionError("no municipio ZIPs in the reference file (or offline directory)")
    for row in targets:
        ctx.try_get(ctx.source["endpoints"]["daily"].format(zip=row["zip"]), key=_key(row["zip"]),
                    record_id=f"UVDAILY/ZIP/{row['zip']}")
    if not ctx.responses:
        first = next(iter(ctx.failures.values()), "no response")
        raise AcquisitionError(f"all {len(targets)} UV requests failed; first: {first}")


def build(ctx: RunContext, responses: list) -> Built:
    by_key = {r.key: r for r in responses}
    built = Built(arithmetic={})
    retained = unresolved = 0
    unbound: list[str] = []
    categories: dict[str, int] = {}
    targets = _targets(ctx)
    previous = {r["geoid"]: r for r in store.read_jsonl(state_path(SOURCE_ID, ctx.paths.data_dir))}
    carried: list[str] = []
    for target in targets:
        response = by_key.get(_key(target["zip"]))
        parsed = adapter.parse_daily(json.loads(response.payload)) if response else None
        if parsed is None or parsed["uv_index"] is None:
            unresolved += 1
            # EPA's service drops individual ZIPs intermittently (HTTP 500). Keep the last
            # good forecast, marked, rather than blanking the municipio for a day; the
            # composer judges it by its forecast_date.
            prior = previous.get(target["geoid"])
            if prior and prior.get("manifestation_id"):
                built.state_rows.append({**prior, "carried_forward": True})
                built.referenced.add(prior["manifestation_id"])
                carried.append(target["name"])
            continue
        retained += 1
        agrees = municipio_key(parsed["city"]) == municipio_key(target["name"])
        if not agrees:
            unbound.append(f"{target['name']}<-{parsed['city']}")
        if parsed["uv_category"]:
            categories[parsed["uv_category"]] = categories.get(parsed["uv_category"], 0) + 1
        built.state_rows.append({
            "geoid": target["geoid"],
            "municipio": target["name"],
            "zip": target["zip"],
            "city": parsed["city"],
            "uv_index": parsed["uv_index"],
            "uv_category": parsed["uv_category"],
            "uv_alert": parsed["uv_alert"],
            "forecast_date": parsed["forecast_date"],
            "binding_evidence": (EvidenceClass.AUTHORITATIVE_BINDING if agrees
                                 else EvidenceClass.UNRESOLVED).value,
            "binding_method": "epa.CITY == municipio" if agrees
                              else f"epa.CITY {parsed['city']!r} != municipio",
            "manifestation_id": response.manifestation.manifestation_id,
            "retrieved_at": iso(ctx.now),
            "carried_forward": False,
        })
        built.referenced.add(response.manifestation.manifestation_id)
    built.state_rows.sort(key=lambda r: r["geoid"])
    built.arithmetic = source_arithmetic(len(targets), retained, 0, unresolved)
    built.counts = {
        "municipios_queried": len(targets),
        "uv_categories": dict(sorted(categories.items())),
        "city_disagrees_with_municipio": unbound,
        "carried_forward": carried,
        "forecast_dates": sorted({r["forecast_date"] for r in built.state_rows if r["forecast_date"]}),
    }
    peak = max((r["uv_index"] for r in built.state_rows), default=None)
    built.message = (f"EPA UV: {retained}/{len(targets)} municipios, peak index {peak}, "
                     f"{len(unbound)} city/municipio disagreement(s), {unresolved} unresolved")
    return built


def main(argv: list[str] | None = None) -> int:
    return run_ingest(source_id=SOURCE_ID, authority=adapter.SOURCE_AUTHORITY,
                      system=SOURCE_SYSTEM, argv=argv, description=__doc__.split("\n\n")[0],
                      acquire=acquire, build=build)


if __name__ == "__main__":
    raise SystemExit(main())
