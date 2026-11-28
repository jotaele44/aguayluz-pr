#!/usr/bin/env python3
"""USGS river stage rate of rise (Puerto Rico) → NWS hydromet plane.

Sudden river-level rise is the first observable sign of a flash flood at a gauge, and
it is visible at gauges NWS has never given flood thresholds. This ingest reads the last
few hours of USGS instantaneous values every refresh and grades how fast each stream is
rising (:mod:`aguayluz.hazard_adapters.river_rise`).

Per run:

1. ``GET /ogcapi/v0/collections/continuous/items`` for the PR bounding box, once for
   gage height (``00065``) and once for discharge (``00060``), over the last
   ``window_hours``. Each response is SHA-256-frozen before it is parsed; a page that
   names a ``next`` link is followed.
2. Arithmetic: SOURCE = RETAINED (instantaneous stage/discharge at a stream gauge) +
   EXCLUDED (reservoirs, lakes, canals, other statistics, withheld values, excluded
   qualifiers, duplicates, spikes, secondary series) + UNRESOLVED (no site, time or
   parseable value), or the run fails closed.
3. Per stream site: rise over 15 min / 1 h / 3 h, rate, discharge ratio, time to NWPS
   action/minor stage (same-datum gauges only) and a rise class, written to
   ``data/river_rise_state.jsonl`` with a 25-point 15-minute grid.
4. A RAPID or FLASH rise opens a ``USGS_RISE:`` episode; revisions only on escalation,
   the first projected minor-stage crossing, or closure.

Rise episodes promote to WEATHER_HAZARD alerts in
:mod:`aguayluz.alert_promotion.river_rise` once calibration enables promotion.

Usage:
    python scripts/ingest_usgs_river_rise.py              # live, keyless (USGS_API_KEY optional)
    python scripts/ingest_usgs_river_rise.py --dry-run
    python scripts/ingest_usgs_river_rise.py --src tests/fixtures/usgs_river_rise --now 2026-11-27T00:03:36Z
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.hazard_adapters import river_rise as adapter  # noqa: E402
from aguayluz.hazard_plane import (  # noqa: E402
    EntityKind,
    EvidenceClass,
    HazardRecord,
    HazardRelationship,
    RecordStatus,
    RelationshipType,
    source_arithmetic,
)
from aguayluz.hydromet import store  # noqa: E402
from aguayluz.outdoor.runner import Built, RunContext, base_parser, iso, run_ingest  # noqa: E402

SOURCE_ID = "usgs_river_rise"
SOURCE_SYSTEM = "USGS Water Data OGC API (continuous)"
STATE_FILE = "river_rise_state.jsonl"
MAX_PAGES = 20


def _key(pcode: str, page: int) -> str:
    return f"continuous_{pcode}.json" if page == 1 else f"continuous_{pcode}_p{page}.json"


def _next_link(payload: bytes) -> str | None:
    try:
        doc = json.loads(payload)
    except ValueError:
        return None
    for link in (doc.get("links") or []) if isinstance(doc, dict) else []:
        if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
            return str(link["href"])
    return None


def prune_snapshots(ctx: RunContext) -> int:
    """Delete this source's raw snapshots that no committed manifestation references."""
    folder = ctx.paths.snapshot_dir(SOURCE_ID)
    if ctx.args.dry_run or not folder.is_dir():
        return 0
    prefix = f"HYDROMET:{SOURCE_ID}:"
    kept = {m.byte_sha256 for m in store.load_manifestations(ctx.paths.data_dir)
            if m.manifestation_id.startswith(prefix)}
    removed = 0
    for path in folder.iterdir():
        if path.is_file() and path.name.split(".", 1)[0] not in kept:
            path.unlink()
            removed += 1
    return removed


def acquire(ctx: RunContext) -> None:
    from aguayluz.usgs_water_api import api_headers

    prune_snapshots(ctx)
    query = dict(ctx.source.get("query") or {})
    codes = query.pop("parameter_code", list(adapter.PARAMETER_CODES))
    hours = float(ctx.args.history_hours or ctx.source.get("window_hours") or 6)
    start = ctx.now - timedelta(hours=hours)
    url = ctx.source["endpoints"]["continuous"]
    headers = {"Accept": "application/geo+json", **api_headers()}
    for pcode in codes:
        params = {"f": "json", **query, "parameter_code": pcode,
                  "datetime": f"{iso(start)}/{iso(ctx.now)}"}
        page, next_url = 1, None
        while page <= MAX_PAGES:
            response = ctx.get(next_url or url, key=_key(pcode, page),
                               params=None if next_url else params, headers=headers,
                               record_id=f"continuous?parameter_code={pcode}&page={page}")
            next_url = None if ctx.offline else _next_link(response.payload)
            if ctx.offline:
                if not (ctx.args.src.is_dir() and (ctx.args.src / _key(pcode, page + 1)).is_file()):
                    break
            elif next_url is None:
                break
            page += 1


def load_assets(path: Path) -> dict[str, dict[str, Any]]:
    """USGS surface-water assets by bare site number."""
    assets: dict[str, dict[str, Any]] = {}
    for row in store.read_jsonl(path):
        asset_id = str(row.get("asset_id") or "")
        if asset_id.startswith("USGS_"):
            assets[asset_id[len("USGS_"):]] = row
    return assets


def _relationships(record: HazardRecord, asset_id: str | None, binding: Any,
                   manifestation_ids: list[str]) -> list[HazardRelationship]:
    rels: list[HazardRelationship] = []
    if asset_id:
        rels.append(HazardRelationship(
            relationship_id=store.relationship_id(record.record_id, "SAME_LOCATION", asset_id),
            subject_id=record.record_id,
            predicate=RelationshipType.SAME_LOCATION,
            object_id=asset_id,
            object_kind=EntityKind.FACILITY,
            evidence_class=EvidenceClass.STABLE_ID,
            source_manifestation_ids=manifestation_ids,
            effective_from=record.observed_from,
            method="usgs.monitoring_location_id == utility_assets.asset_id[USGS_]",
        ))
    target = (binding.geoid or binding.candidate_geoid) if binding is not None else None
    if target:
        rels.append(HazardRelationship(
            relationship_id=store.relationship_id(record.record_id, "SPATIALLY_INTERSECTS", target),
            subject_id=record.record_id,
            predicate=RelationshipType.SPATIALLY_INTERSECTS,
            object_id=target,
            object_kind=EntityKind.MUNICIPALITY,
            evidence_class=binding.evidence_class,
            source_manifestation_ids=manifestation_ids,
            effective_from=record.observed_from,
            distance_m=binding.distance_m,
            method=binding.method,
            spatial_state=binding.spatial_state,
        ))
    return rels


def _nwps_summary(nwps: dict[str, Any] | None) -> dict[str, Any] | None:
    if not nwps:
        return None
    return {
        "lid": nwps.get("lid"),
        "flood_category": nwps.get("flood_category"),
        "thresholds": {k: (v or {}).get("stage") for k, v in (nwps.get("thresholds") or {}).items()},
        "observed_stage": (nwps.get("observed") or {}).get("stage"),
        "observed_at": (nwps.get("observed") or {}).get("valid_time"),
    }


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 1)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1], 1)


def build(ctx: RunContext, responses: list) -> Built:
    from aguayluz.hydromet.spatial import MunicipioIndex

    config = adapter.load_thresholds(ctx.args.thresholds)
    classes = adapter.promotion_classes(config)
    defaults = config["defaults"]
    documents = [json.loads(r.payload) for r in responses]
    features = adapter.features_of(documents)
    assets = load_assets(ctx.args.assets or (ctx.paths.data_dir / "utility_assets.jsonl"))
    stream_sites = {site for site, row in assets.items() if row.get("asset_subtype") == "stream_gage"}
    collected = adapter.collect(features, stream_sites, defaults["excluded_qualifiers"],
                                float(defaults["spike_ft"]))
    nwps_by_site = {str(r["usgs_id"]): r for r in store.load_gauge_state(ctx.paths.data_dir)
                    if r.get("usgs_id")}
    previous = {str(r.get("site_no")): r for r in store.read_jsonl(ctx.paths.data_dir / STATE_FILE)}
    records = store.load_records(ctx.paths.data_dir)
    current = store.current_by_event(records, adapter.CANONICAL_PREFIX)
    open_heads: dict[str, HazardRecord] = {}
    closed_end: dict[str, datetime] = {}
    for record in current.values():
        site = record.source_record_id
        if record.status == RecordStatus.ACTIVE:
            open_heads[site] = record
        elif record.effective_to is not None and (site not in closed_end or record.effective_to > closed_end[site]):
            closed_end[site] = record.effective_to

    index = MunicipioIndex.from_geojson(ctx.args.municipios)
    manifestation_ids = [r.manifestation.manifestation_id for r in responses]
    stage_manifestation = next((r.manifestation.manifestation_id for r in responses
                                if r.key.startswith(f"continuous_{adapter.STAGE}")),
                               manifestation_ids[0] if manifestation_ids else "")
    built = Built(arithmetic={})
    built.referenced = set(manifestation_ids)
    actions: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    latencies: list[float] = []

    for site in sorted(set(collected.stage) | set(open_heads)):
        asset = assets.get(site) or {}
        settings = adapter.site_settings(config, site)
        nwps = nwps_by_site.get(site)
        context = adapter.SiteContext(
            site=site, asset_id=f"USGS_{site}" if asset else None,
            name=asset.get("asset_name") or (open_heads[site].title_raw if site in open_heads else None),
            latitude=asset.get("lat"), longitude=asset.get("lon"), nwps=nwps,
        )
        binding = index.bind_point(asset.get("lon"), asset.get("lat"), asset.get("municipality")) \
            if asset else None
        row: dict[str, Any] | None = None
        if site in collected.stage:
            row = adapter.analyse_site(context, collected.stage[site],
                                       collected.discharge.get(site, []), ctx.now, settings)
        prev = previous.get(site) or {}
        not_before = closed_end.get(site)
        step = adapter.advance_episode(
            open_heads.get(site), row, ctx.now, settings, classes,
            previous_quiet_since=prev.get("quiet_since"),
            not_before=not_before + timedelta(minutes=int(defaults["grid_minutes"])) if not_before else None,
        )
        actions[step.action] = actions.get(step.action, 0) + 1
        episode_head = open_heads.get(site)
        if step.action in {"open", "revise", "close"} and step.material and step.event_id:
            latest_time = adapter.parse_time(((row or {}).get("latest") or {}).get("time"))
            observed_to = latest_time or (episode_head.observed_to if episode_head else ctx.now) or ctx.now
            record = adapter.episode_record(
                step.event_id, step.material, row or {}, context, stage_manifestation,
                supersedes=episode_head.record_id if episode_head and step.action != "open" else None,
                observed_to=observed_to,
                effective_to=step.end if step.action == "close" else None,
                municipality_id=binding.geoid if binding else None,
                binding_evidence=binding.evidence_class.value if binding else None,
                closed_reason=step.closed_reason,
                include_series=step.action in {"open", "close"},
            )
            built.records.append(record)
            built.relationships.extend(_relationships(record, context.asset_id, binding,
                                                      [stage_manifestation]))
            episode_head = record
        if row is None:
            continue

        class_counts[row["rise_class"]] = class_counts.get(row["rise_class"], 0) + 1
        state_counts[row["data_state"]] = state_counts.get(row["data_state"], 0) + 1
        if row.get("latency_minutes") is not None:
            latencies.append(float(row["latency_minutes"]))
        episode = None
        if episode_head is not None:
            values = episode_head.normalized_values
            episode = {
                "canonical_event_id": episode_head.canonical_event_id,
                "record_id": episode_head.record_id,
                "onset": values.get("onset"),
                "peak_class": values.get("peak_class"),
                "minor_within_60m": values.get("minor_within_60m", False),
                "status": "closed" if episode_head.status == RecordStatus.TERMINATED else "open",
                "end": iso(episode_head.effective_to) if episode_head.effective_to else None,
            }
        built.state_rows.append({
            "site_no": site,
            "asset_id": context.asset_id,
            "name": context.name,
            "latitude": context.latitude,
            "longitude": context.longitude,
            "municipio": binding.municipio if binding else None,
            "geoid": binding.geoid if binding else None,
            "candidate_municipio": binding.candidate_municipio if binding else None,
            "binding_evidence": binding.evidence_class.value if binding else "UNRESOLVED",
            "binding_method": binding.method if binding else "no_utility_asset",
            "nwps": _nwps_summary(nwps),
            "time_series_ids": collected.time_series_ids.get(site, {}),
            "latest": row["latest"],
            "latency_minutes": row["latency_minutes"],
            "data_state": row["data_state"],
            "rise_class": row["rise_class"],
            "class_reasons": row["class_reasons"],
            "metrics": row["metrics"],
            "projection": row["projection"],
            "datum_check": row.get("datum_check"),
            "thresholds_applied": row["thresholds_applied"],
            "rising_since": row["rising_since"],
            "quiet_since": step.quiet_since if episode and episode["status"] == "open" else None,
            "episode": episode if episode and episode["status"] == "open" else None,
            "site_note": settings.get("note"),
            "series": row["series"],
            "manifestation_ids": manifestation_ids,
            "retrieved_at": iso(ctx.now),
        })

    cutoff = ctx.now - timedelta(days=float(ctx.source.get("retention_days")
                                            or defaults.get("retention_days", 35)))

    def retain(record: HazardRecord) -> bool:
        if record.status != RecordStatus.TERMINATED:
            return True
        return record.effective_to is None or record.effective_to >= cutoff

    built.retain_event = retain
    built.arithmetic = source_arithmetic(collected.source, collected.retained,
                                         collected.excluded, collected.unresolved)
    rising = sorted(f"{r['site_no']} {r['rise_class']}" for r in built.state_rows
                    if r["rise_class"] in {"RAPID_RISE", "FLASH_RISE"})
    built.counts = {
        "outcomes": dict(sorted(collected.outcomes.items())),
        "stream_sites": len(built.state_rows),
        "rise_classes": dict(sorted(class_counts.items())),
        "data_states": dict(sorted(state_counts.items())),
        "episode_actions": dict(sorted(actions.items())),
        "new_revisions": len(built.records),
        "latency_minutes_p50": _percentile(latencies, 50),
        "latency_minutes_p90": _percentile(latencies, 90),
        "promotion_enabled": bool((config.get("promotion") or {}).get("enabled")),
        "calibration_status": (config.get("calibration") or {}).get("status"),
    }
    built.message = (
        f"USGS river rise: {collected.source} feature(s), {len(built.state_rows)} stream site(s), "
        f"classes {built.counts['rise_classes']}, {len(built.records)} new revision(s), "
        f"latency p50 {built.counts['latency_minutes_p50']} min; rising: {rising or 'none'} "
        f"(run {iso(ctx.now)})"
    )
    return built


def _parser():
    ap = base_parser(__doc__.split("\n\n")[0])
    ap.add_argument("--assets", type=Path, default=None, help="default <data-dir>/utility_assets.jsonl")
    ap.add_argument("--thresholds", type=Path, default=None,
                    help="default config/river_rise_thresholds.v1.json")
    ap.add_argument("--municipios", type=Path, default=None)
    ap.add_argument("--history-hours", type=float, default=None,
                    help="window to read (default: the registry's window_hours)")
    return ap


def main(argv: list[str] | None = None) -> int:
    return run_ingest(source_id=SOURCE_ID, authority=adapter.SOURCE_AUTHORITY,
                      system=SOURCE_SYSTEM, argv=argv, description=__doc__.split("\n\n")[0],
                      acquire=acquire, build=build, parser=_parser(), state_file=STATE_FILE)


if __name__ == "__main__":
    raise SystemExit(main())
