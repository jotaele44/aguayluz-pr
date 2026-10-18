#!/usr/bin/env python3
"""NWS marine-zone alerts for Puerto Rico waters → outdoor-conditions layer.

``scripts/ingest_nws_alerts.py`` reads ``alerts/active?area=PR``, which covers the
island's *land* zones — so a High Surf Advisory or Rip Current Statement arrives there,
but a Small Craft Advisory or Gale Warning for the waters around the island never does:
those are issued for marine zones (``AMZ7xx``), which belong to the western-Atlantic
marine area ``AM``. This ingest reads that area and keeps the San Juan zones.

Per run:

1. ``GET /alerts/active?area=AM`` — every active alert in the area, SHA-256-frozen
   before parsing.
2. Arithmetic: SOURCE = RETAINED (Actual alerts naming a PR marine zone) + EXCLUDED
   (other zones, non-Actual status) + UNRESOLVED (no id).
3. One canonical event per VTEC event (:mod:`aguayluz.hazard_adapters.nws_marine`); a
   revision only when its material state changes; an event no longer active is closed
   with a TERMINATED revision; closed events older than ``retention_days`` are pruned.
4. Each record is bound to the coastal municipios of its zones (frozen in
   ``data/reference/outdoor_reference.v1.json``; PROXIMITY, ``marine_zone_within_2km``).

Active alerts promote to WEATHER_HAZARD AlertEvents in
:mod:`aguayluz.alert_promotion.outdoor`.

Usage:
    python scripts/ingest_nws_marine_alerts.py           # live, keyless
    python scripts/ingest_nws_marine_alerts.py --dry-run
    python scripts/ingest_nws_marine_alerts.py --src tests/fixtures/outdoor/nws_marine_alerts.json
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

from aguayluz.hazard_adapters import nws_marine as adapter  # noqa: E402
from aguayluz.hazard_plane import (  # noqa: E402
    EntityKind,
    EvidenceClass,
    HazardRelationship,
    RecordStatus,
    RelationshipType,
    source_arithmetic,
)
from aguayluz.hydromet import store  # noqa: E402
from aguayluz.outdoor.runner import Built, RunContext, iso, run_ingest  # noqa: E402

SOURCE_ID = "nws_marine_alerts"
SOURCE_SYSTEM = "api.weather.gov alerts (area=AM)"
KEY = "nws_marine_alerts.json"


def acquire(ctx: RunContext) -> None:
    ctx.get(ctx.source["endpoints"]["alerts"], key=KEY, record_id="alerts/active?area=AM",
            headers={"Accept": "application/geo+json"})


def _relationships(record, zones: list[str], zone_index: dict[str, dict], manifestation_id: str):
    seen: dict[str, float] = {}
    for zone in zones:
        for municipio in (zone_index.get(zone) or {}).get("municipios", []):
            gap = float(municipio.get("distance_m") or 0.0)
            if municipio["geoid"] not in seen or gap < seen[municipio["geoid"]]:
                seen[municipio["geoid"]] = gap
    for geoid, gap in sorted(seen.items()):
        yield HazardRelationship(
            relationship_id=store.relationship_id(record.record_id, "SPATIALLY_INTERSECTS", geoid),
            subject_id=record.record_id,
            predicate=RelationshipType.SPATIALLY_INTERSECTS,
            object_id=geoid,
            object_kind=EntityKind.MUNICIPALITY,
            evidence_class=EvidenceClass.PROXIMITY,
            source_manifestation_ids=[manifestation_id],
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            distance_m=gap,
            method="marine_zone_within_2km",
        )


def build(ctx: RunContext, responses: list) -> Built:
    response = responses[0]
    doc = json.loads(response.payload)
    features = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(features, list):
        raise ValueError("response has no 'features' list")
    zone_index = {z["zone_id"]: z for z in ctx.reference.get("marine_zones", [])}
    pr_zones = set(zone_index)
    if not pr_zones:
        raise ValueError("reference file lists no PR marine zones; run scripts/freeze_outdoor_reference.py")
    manifestation_id = response.manifestation.manifestation_id
    current = store.current_by_event(store.load_records(ctx.paths.data_dir), adapter.CANONICAL_PREFIX)

    built = Built(arithmetic={})
    outcomes: dict[str, int] = {}
    retained = excluded = unresolved = 0
    active_keys: set[str] = set()
    for feature in features:
        outcome = adapter.classify(feature, pr_zones)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome.startswith("excluded"):
            excluded += 1
            continue
        if outcome.startswith("unresolved"):
            unresolved += 1
            continue
        retained += 1
        props = feature["properties"]
        material = adapter.material_state(props, pr_zones)
        event_id = adapter.canonical_event_id(material["event_key"])
        if not material["closed"]:
            active_keys.add(event_id)
        head = current.get(event_id)
        if head is not None and head.normalized_values.get("material_digest") == adapter.material_digest(material):
            continue
        record = adapter.normalize(props, pr_zones, manifestation_id,
                                   supersedes_record_id=head.record_id if head else None,
                                   closed_at=ctx.now)
        built.records.append(record)
        built.relationships.extend(_relationships(record, material["zones"], zone_index, manifestation_id))
        current[event_id] = record

    closed = 0
    for event_id, head in sorted(current.items()):
        if head.status == RecordStatus.ACTIVE and event_id not in active_keys:
            record = adapter.close_record(head, manifestation_id, ctx.now)
            built.records.append(record)
            built.relationships.extend(_relationships(
                record, list(head.normalized_values.get("zones") or []), zone_index, manifestation_id))
            current[event_id] = record
            closed += 1

    cutoff = ctx.now - timedelta(days=float(ctx.source.get("retention_days", 14)))

    def retain(record) -> bool:
        if record.status != RecordStatus.TERMINATED:
            return True
        return record.effective_to is None or record.effective_to >= cutoff

    built.retain_event = retain
    built.arithmetic = source_arithmetic(len(features), retained, excluded, unresolved)
    active = sorted(
        f"{r.title_raw} ({', '.join(r.normalized_values.get('zones') or [])})"
        for r in current.values() if r.status == RecordStatus.ACTIVE
    )
    built.counts = {
        "outcomes": dict(sorted(outcomes.items())),
        "new_revisions": len(built.records),
        "closed": closed,
        "active_pr_marine_events": len(active),
        "updated": doc.get("updated"),
    }
    built.message = (f"NWS marine: {len(features)} AM alert(s), {retained} for PR waters, "
                     f"{len(built.records)} new revision(s), {closed} closed; active: {active or 'none'} "
                     f"(run {iso(ctx.now)})")
    return built


def main(argv: list[str] | None = None) -> int:
    return run_ingest(source_id=SOURCE_ID, authority=adapter.SOURCE_AUTHORITY,
                      system=SOURCE_SYSTEM, argv=argv, description=__doc__.split("\n\n")[0],
                      acquire=acquire, build=build)


if __name__ == "__main__":
    raise SystemExit(main())
