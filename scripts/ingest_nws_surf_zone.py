#!/usr/bin/env python3
"""NWS San Juan Surf Zone Forecast → outdoor-conditions layer (hydromet plane).

Per run:

1. ``GET /products/types/SRF/locations/SJU`` — the product listing; the newest product
   issued by TJSJ is selected.
2. ``GET /products/{id}`` — the product. Both responses are SHA-256-frozen before the
   text is parsed (:mod:`aguayluz.hazard_adapters.nws_surf_zone`).
3. Arithmetic over the product's segments: SOURCE = RETAINED (PR zones with a parsed
   forecast and at least one bound municipio) + EXCLUDED (USVI zones) + UNRESOLVED.
4. A record revision per zone-day only when the rip current risk or surf height changes;
   the current forecast per zone is rewritten into ``data/outdoor_surf_state.jsonl``.
   Zone-days older than ``retention_days`` are pruned whole.

Rip current risk **High** is promoted to a WEATHER_HAZARD alert by
:mod:`aguayluz.alert_promotion.outdoor`.

Usage:
    python scripts/ingest_nws_surf_zone.py              # live, keyless
    python scripts/ingest_nws_surf_zone.py --dry-run
    python scripts/ingest_nws_surf_zone.py --src tests/fixtures/outdoor/srf/
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.hazard_adapters import nws_surf_zone as adapter  # noqa: E402
from aguayluz.hazard_plane import (  # noqa: E402
    EntityKind,
    EvidenceClass,
    HazardRelationship,
    RelationshipType,
    source_arithmetic,
)
from aguayluz.hydromet import store  # noqa: E402
from aguayluz.outdoor import load_municipios, municipio_key  # noqa: E402
from aguayluz.outdoor.runner import (  # noqa: E402
    AcquisitionError,
    Built,
    RunContext,
    iso,
    parse_iso,
    run_ingest,
)

SOURCE_ID = "nws_surf_zone"
SOURCE_SYSTEM = "api.weather.gov products (SRF)"
LISTING_KEY = "srf_listing.json"
PRODUCT_KEY = "srf_product.json"


def acquire(ctx: RunContext) -> None:
    endpoints = ctx.source["endpoints"]
    listing = ctx.get(endpoints["listing"], key=LISTING_KEY,
                      record_id="products/types/SRF/locations/SJU",
                      headers={"Accept": "application/ld+json"})
    try:
        graph = json.loads(listing.payload).get("@graph") or []
    except (ValueError, AttributeError) as exc:
        raise AcquisitionError(f"listing unparseable: {exc}") from exc
    candidates = [g for g in graph if isinstance(g, dict)
                  and g.get("issuingOffice") == adapter.ISSUING_OFFICE and g.get("id")]
    if not candidates:
        raise AcquisitionError("listing holds no TJSJ SRF product")
    newest = max(candidates, key=lambda g: str(g.get("issuanceTime") or ""))
    ctx.get(endpoints["product"].format(id=newest["id"]), key=PRODUCT_KEY,
            record_id=f"products/{newest['id']}", headers={"Accept": "application/ld+json"})


def build(ctx: RunContext, responses: list) -> Built:
    product_response = next(r for r in responses if r.key == PRODUCT_KEY)
    product = json.loads(product_response.payload)
    text = product.get("productText")
    issued_at = parse_iso(product.get("issuanceTime"))
    if not isinstance(text, str) or issued_at is None:
        raise ValueError("product has no productText/issuanceTime")
    if product.get("productCode") != "SRF" or product.get("issuingOffice") != adapter.ISSUING_OFFICE:
        raise ValueError(f"not a TJSJ SRF product: {product.get('productCode')}/"
                         f"{product.get('issuingOffice')}")
    product_id = str(product.get("id") or "")
    manifestation_id = product_response.manifestation.manifestation_id

    municipios = {municipio_key(m["name"]): m for m in load_municipios()}
    current = store.current_by_event(store.load_records(ctx.paths.data_dir), adapter.CANONICAL_PREFIX)
    issued_local = issued_at.astimezone(adapter.AST).date()

    built = Built(arithmetic={})
    retained = excluded = unresolved = 0
    outcomes: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for segment in adapter.parse_product(text):
        if segment.is_usvi:
            outcome = "excluded:usvi"
        elif not segment.is_pr:
            outcome = "excluded:not_puerto_rico"
        elif not segment.periods:
            outcome = "unresolved:no_forecast_periods"
        else:
            outcome = "retained"
        names = segment.beaches if segment.beaches else [segment.name.removesuffix(" PR")]
        method = "srf.including_beaches" if segment.beaches else "srf.zone_name"
        bound = [municipios[municipio_key(n)] for n in names if municipio_key(n) in municipios]
        unbound = [n for n in names if municipio_key(n) not in municipios]
        if outcome == "retained" and not bound:
            outcome = "unresolved:no_municipio_binding"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome.startswith("excluded"):
            excluded += 1
            continue
        if outcome.startswith("unresolved"):
            unresolved += 1
            continue
        retained += 1

        dates = adapter.period_dates([p.label for p in segment.periods], issued_local)
        periods_out = []
        record_ids = []
        for period, day in zip(segment.periods, dates, strict=True):
            lo, hi = adapter.surf_height_ft(period.surf_height_text)
            periods_out.append({
                "label": period.label,
                "date": day.isoformat() if day else None,
                "detailed": period.detailed,
                "rip_current_risk": period.rip_current_risk,
                "rip_current_risk_raw": period.rip_current_risk_raw,
                "surf_height_text": period.surf_height_text,
                "surf_min_ft": lo,
                "surf_max_ft": hi,
            })
            if period.rip_current_risk:
                risk_counts[period.rip_current_risk] = risk_counts.get(period.rip_current_risk, 0) + 1
            if not period.detailed or day is None:
                continue
            for zone in segment.zones:
                material = adapter.material_state(zone, day, period)
                digest = adapter.material_digest(material)
                event_id = adapter.canonical_event_id(zone, day)
                head = current.get(event_id)
                if head is not None and head.normalized_values.get("material_digest") == digest:
                    record_ids.append(head.record_id)
                    continue
                record = adapter.normalize(
                    segment, zone, day, period, manifestation_id,
                    issued_at=issued_at, product_id=product_id,
                    municipality_id=bound[0]["geoid"] if len(bound) == 1 else None,
                    supersedes_record_id=head.record_id if head else None,
                )
                built.records.append(record)
                current[event_id] = record
                record_ids.append(record.record_id)
                for municipio in bound:
                    built.relationships.append(HazardRelationship(
                        relationship_id=store.relationship_id(
                            record.record_id, "SPATIALLY_INTERSECTS", municipio["geoid"]),
                        subject_id=record.record_id,
                        predicate=RelationshipType.SPATIALLY_INTERSECTS,
                        object_id=municipio["geoid"],
                        object_kind=EntityKind.MUNICIPALITY,
                        evidence_class=EvidenceClass.AUTHORITATIVE_BINDING,
                        source_manifestation_ids=[manifestation_id],
                        effective_from=record.effective_from,
                        effective_to=record.effective_to,
                        method=method,
                    ))
        for zone in segment.zones:
            built.state_rows.append({
                "zone": zone,
                "zone_name": segment.name,
                "ugc": segment.ugc,
                "municipios": [{"geoid": m["geoid"], "name": m["name"]} for m in bound],
                "unbound_names": unbound,
                "binding_evidence": EvidenceClass.AUTHORITATIVE_BINDING.value,
                "binding_method": method,
                "issued_at": iso(issued_at),
                "product_id": product_id,
                "periods": periods_out,
                "record_ids": sorted(set(record_ids)),
                "manifestation_id": manifestation_id,
                "retrieved_at": iso(ctx.now),
            })

    retention = timedelta(days=float(ctx.source.get("retention_days", 7)))
    cutoff = (ctx.now.astimezone(adapter.AST) - retention).date().isoformat()

    def retain(record) -> bool:
        return str(record.normalized_values.get("date") or "") >= cutoff

    built.state_rows.sort(key=lambda r: r["zone"])
    built.retain_event = retain
    built.referenced = {manifestation_id}
    built.arithmetic = source_arithmetic(retained + excluded + unresolved, retained, excluded, unresolved)
    built.counts = {
        "product_id": product_id,
        "issued_at": iso(issued_at),
        "outcomes": dict(sorted(outcomes.items())),
        "new_revisions": len(built.records),
        "rip_current_risk_periods": dict(sorted(risk_counts.items())),
    }
    high = sorted({r["zone"] for r in built.state_rows
                   for p in r["periods"] if p["rip_current_risk"] == "HIGH"})
    built.message = (f"SRF {product_id[:8]} issued {iso(issued_at)}: {retained} PR zone(s), "
                     f"{len(built.records)} new revision(s), high rip current risk: {high or 'none'}")
    return built


def main(argv: list[str] | None = None) -> int:
    return run_ingest(source_id=SOURCE_ID, authority=adapter.SOURCE_AUTHORITY,
                      system=SOURCE_SYSTEM, argv=argv, description=__doc__.split("\n\n")[0],
                      acquire=acquire, build=build)


if __name__ == "__main__":
    raise SystemExit(main())
