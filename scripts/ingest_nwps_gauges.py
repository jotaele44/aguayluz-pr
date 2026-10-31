#!/usr/bin/env python3
"""NWS NWPS river gauges (Puerto Rico) → NWS hydromet plane.

Successor of the "AHPS River Gauge Current and Forecast Flood Stages" entry on the
legacy IDP-GIS catalog (https://www.weather.gov/gis/IDP-GISRestMetadata). AHPS moved
into the National Water Prediction Service in 2024; its JSON API is the authoritative
source, and the CloudGIS ``water/riv_gauges`` map layer is a rendering of it.

Per run:

1. ``GET /nwps/v1/gauges?bbox=<PR>`` — current observed stage + NWS flood category for
   every PR gauge. The exact response bytes are hashed (and kept under
   ``data/hydromet_snapshots/nwps_gauges/``) before anything is parsed.
2. ``GET /nwps/v1/gauges/{lid}`` for gauges whose detail is missing or older than
   ``detail_max_age_hours`` — flood thresholds, ``usgsId`` and the NWPS county name.
3. Arithmetic: SOURCE = RETAINED + EXCLUDED + UNRESOLVED over the bulk response, or the
   run fails closed and writes nothing but a FAIL receipt.
4. Binding: ``usgsId`` → existing ``USGS_<id>`` asset (STABLE_ID); point-in-polygon →
   municipio, corroborated by the NWPS county name (see aguayluz.hydromet.spatial).
5. A record revision only when the material state (category, thresholds, service,
   usgsId) changes; the per-gauge current stage is rewritten into
   ``data/nwps_gauge_state.jsonl`` every run.

NWS issues no stage forecasts for Puerto Rico points (every ``forecast`` block is
``fcst_not_current``), so only observations are carried.

Usage:
    python scripts/ingest_nwps_gauges.py                 # live
    python scripts/ingest_nwps_gauges.py --dry-run       # live fetch, write nothing
    python scripts/ingest_nwps_gauges.py --src bulk.json --details-src details/
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz.hazard_adapters import nwps_gauges as adapter  # noqa: E402
from aguayluz.hazard_plane import (  # noqa: E402
    EntityKind,
    EvidenceClass,
    HazardRecord,
    HazardRelationship,
    Manifestation,
    RelationshipType,
    source_arithmetic,
)
from aguayluz.hydromet import PR_ENVELOPE, USER_AGENT, store  # noqa: E402

SOURCE_ID = "nwps_gauges"
SOURCE_SYSTEM = "NWPS API v1"


@dataclass
class DetailResult:
    """One gauge's compact detail and where it came from."""

    detail: dict[str, Any] | None
    manifestation_id: str | None
    retrieved_at: str | None
    error: str | None = None
    fresh: bool = False


@dataclass
class BuildResult:
    records: list[HazardRecord] = field(default_factory=list)
    relationships: list[HazardRelationship] = field(default_factory=list)
    state_rows: list[dict[str, Any]] = field(default_factory=list)
    arithmetic: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_usgs_asset_ids(path: Path) -> set[str]:
    """``USGS_<site>`` ids already in the asset registry (the STABLE_ID join target)."""
    ids: set[str] = set()
    for row in store.read_jsonl(path):
        asset_id = str(row.get("asset_id") or "")
        if asset_id.startswith("USGS_"):
            ids.add(asset_id)
    return ids


def schema_signature(gauges: list[dict[str, Any]]) -> str:
    keys = sorted({key for g in gauges if isinstance(g, dict) for key in g})
    return "nwps.gauges[" + ",".join(keys) + "]"


def needs_detail(previous: dict[str, Any] | None, now: datetime, max_age_hours: float) -> bool:
    if not previous or not previous.get("detail") or previous.get("detail_error"):
        return True
    fetched = adapter.parse_time(previous.get("detail_retrieved_at"))
    return fetched is None or now - fetched > timedelta(hours=max_age_hours)


def classify(entry: Any) -> str:
    """retained | excluded:<reason> | unresolved:<reason> for one bulk entry."""
    if not isinstance(entry, dict) or not str(entry.get("lid") or "").strip():
        return "unresolved:missing_lid"
    lat, lon = entry.get("latitude"), entry.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return "unresolved:missing_coordinates"
    state = ((entry.get("state") or {}).get("abbreviation") or "").upper()
    if state != "PR":
        return f"excluded:state_{state or 'blank'}"
    xmin, ymin, xmax, ymax = PR_ENVELOPE
    if not (xmin <= lon <= xmax and ymin <= lat <= ymax):
        return "excluded:outside_pr_envelope"
    return "retained"


def build_run(
    gauges: list[Any],
    bulk: Manifestation,
    details: dict[str, DetailResult],
    previous_state: dict[str, dict[str, Any]],
    current: dict[str, HazardRecord],
    index: Any,
    usgs_assets: set[str],
    retrieved_at: datetime,
) -> BuildResult:
    """Pure: bulk entries + details + prior state → records, bindings, state rows."""
    result = BuildResult()
    outcomes: dict[str, int] = {}
    retained = excluded = unresolved = 0
    revisions = usgs_matched = usgs_unmatched = 0
    bindings: dict[str, int] = {}
    for entry in gauges:
        outcome = classify(entry)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome.startswith("excluded"):
            excluded += 1
            continue
        if outcome.startswith("unresolved"):
            unresolved += 1
            continue
        retained += 1
        lid = str(entry["lid"]).upper()
        detail_result = details.get(lid)
        prev = previous_state.get(lid) or {}
        if detail_result is None and prev.get("detail"):
            detail_result = DetailResult(
                prev["detail"], prev.get("detail_manifestation_id"), prev.get("detail_retrieved_at")
            )
        detail = detail_result.detail if detail_result else None

        binding = index.bind_point(entry.get("longitude"), entry.get("latitude"),
                                   (detail or {}).get("county"))
        bindings[binding.evidence_class.value] = bindings.get(binding.evidence_class.value, 0) + 1
        usgs_id = (detail or {}).get("usgsId")
        asset_id = f"USGS_{usgs_id}" if usgs_id and f"USGS_{usgs_id}" in usgs_assets else None
        if usgs_id and asset_id:
            usgs_matched += 1
        elif usgs_id:
            usgs_unmatched += 1

        material = adapter.material_state(entry, detail)
        digest = adapter.material_digest(material)
        event_id = adapter.canonical_event_id(lid)
        head = current.get(event_id)
        record_id = head.record_id if head else None
        if head is None or head.normalized_values.get("material_digest") != digest:
            record = adapter.normalize(
                entry, detail, bulk.manifestation_id,
                municipality_id=binding.geoid,
                geography_basis=f"NWPS_GAUGE_POINT:{binding.evidence_class.value}",
                facility_id=asset_id,
                supersedes_record_id=head.record_id if head else None,
            )
            result.records.append(record)
            record_id = record.record_id
            revisions += 1
            sources = [bulk.manifestation_id]
            if detail_result and detail_result.manifestation_id:
                sources.append(detail_result.manifestation_id)
            if asset_id:
                result.relationships.append(HazardRelationship(
                    relationship_id=store.relationship_id(record.record_id, "SAME_LOCATION", asset_id),
                    subject_id=record.record_id,
                    predicate=RelationshipType.SAME_LOCATION,
                    object_id=asset_id,
                    object_kind=EntityKind.FACILITY,
                    evidence_class=EvidenceClass.STABLE_ID,
                    source_manifestation_ids=sources,
                    effective_from=record.observed_from,
                    method="nwps.usgsId == utility_assets.asset_id[USGS_]",
                ))
            target = binding.geoid or binding.candidate_geoid
            if target:
                result.relationships.append(HazardRelationship(
                    relationship_id=store.relationship_id(record.record_id, "SPATIALLY_INTERSECTS", target),
                    subject_id=record.record_id,
                    predicate=RelationshipType.SPATIALLY_INTERSECTS,
                    object_id=target,
                    object_kind=EntityKind.MUNICIPALITY,
                    evidence_class=binding.evidence_class,
                    source_manifestation_ids=sources,
                    effective_from=record.observed_from,
                    distance_m=binding.distance_m,
                    method=binding.method,
                    spatial_state=binding.spatial_state,
                ))

        observed = ((entry.get("status") or {}).get("observed")) or {}
        result.state_rows.append({
            "lid": lid,
            "name": entry.get("name"),
            "latitude": entry.get("latitude"),
            "longitude": entry.get("longitude"),
            "wfo": (entry.get("wfo") or {}).get("abbreviation") or None,
            "rfc": (entry.get("rfc") or {}).get("abbreviation") or None,
            "pedts_observed": (entry.get("pedts") or {}).get("observed") or None,
            "flood_category": material["flood_category"],
            "observed": {
                "stage": adapter.clean_number(observed.get("primary")),
                "stage_unit": observed.get("primaryUnit") or None,
                "flow": adapter.clean_number(observed.get("secondary")),
                "flow_unit": observed.get("secondaryUnit") or None,
                "valid_time": observed.get("validTime") or None,
            },
            "thresholds": material["thresholds"],
            "threshold_stage_unit": (detail or {}).get("stageUnits"),
            "in_service": material["in_service"],
            "usgs_id": usgs_id or None,
            "asset_id": asset_id,
            "reach_id": (detail or {}).get("reachId"),
            "county_raw": (detail or {}).get("county"),
            "municipio": binding.municipio,
            "geoid": binding.geoid,
            "candidate_geoid": binding.candidate_geoid,
            "candidate_municipio": binding.candidate_municipio,
            "binding_evidence": binding.evidence_class.value,
            "binding_method": binding.method,
            "record_id": record_id,
            "bulk_manifestation_id": bulk.manifestation_id,
            "detail": detail,
            "detail_manifestation_id": detail_result.manifestation_id if detail_result else None,
            "detail_retrieved_at": detail_result.retrieved_at if detail_result else None,
            "detail_error": detail_result.error if detail_result else "NO_DETAIL",
            "retrieved_at": _iso(retrieved_at),
        })

    result.state_rows.sort(key=lambda r: r["lid"])
    result.arithmetic = source_arithmetic(len(gauges), retained, excluded, unresolved)
    result.counts = {
        "outcomes": dict(sorted(outcomes.items())),
        "new_revisions": revisions,
        "usgs_matched": usgs_matched,
        "usgs_unmatched": usgs_unmatched,
        "bindings": dict(sorted(bindings.items())),
        "flood_categories": _category_counts(result.state_rows),
    }
    return result


def _category_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["flood_category"] or "blank"] = counts.get(row["flood_category"] or "blank", 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------- acquisition


def _client() -> Any:
    import httpx

    return httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def _fetch(client: Any, url: str, params: dict[str, Any] | None = None) -> tuple[bytes, dict[str, str]]:
    from aguayluz.http_retry import get_with_retry

    response = get_with_retry(url, params=params, client=client)
    response.raise_for_status()
    return response.content, dict(response.headers)


def _freeze(payload: bytes, *, record_id: str, url: str, query: str | None, at: datetime,
            count: int | None, signature: str | None, headers: dict[str, str] | None,
            snapshot_dir: Path | None) -> Manifestation:
    return store.freeze_bytes(
        SOURCE_ID, payload,
        source_authority=adapter.SOURCE_AUTHORITY,
        source_system=SOURCE_SYSTEM,
        source_record_id=record_id,
        source_url=url,
        retrieval_query=query,
        retrieved_at=at,
        record_count=count,
        schema_signature=signature,
        headers=headers,
        snapshot_dir=snapshot_dir,
        extension="json",
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", type=Path, help="offline bulk /gauges JSON (no network at all)")
    ap.add_argument("--details-src", type=Path, help="offline directory of <LID>.json details")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--assets", type=Path, default=None, help="default <data-dir>/utility_assets.jsonl")
    ap.add_argument("--municipios", type=Path, default=None)
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--max-details", type=int, default=150)
    ap.add_argument("--now", help="override the run clock (ISO 8601), for reproducible tests")
    ap.add_argument("--dry-run", action="store_true", help="fetch and build; write nothing")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from aguayluz.hydromet.spatial import MunicipioIndex

    now = adapter.parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print("--now is not a valid ISO 8601 timestamp", file=sys.stderr)
        return 2
    source = store.registry_source(SOURCE_ID, store.load_source_registry(args.registry))
    if source is None:
        print(f"{SOURCE_ID} missing from config/hydromet_sources.v1.json", file=sys.stderr)
        return 2
    paths = store.hydromet_paths(args.data_dir)
    snapshot_dir = None if args.dry_run else paths.snapshot_dir(SOURCE_ID)
    bulk_url = source["endpoints"]["gauges"]
    query = dict(source["query"])
    query_text = urlencode(query)

    def fail(message: str) -> int:
        print(f"ingest_nwps_gauges: FAIL — {message}", file=sys.stderr)
        if not args.dry_run:
            store.record_receipt(SOURCE_ID, status="FAIL", attempted_at=now,
                                 data_dir=paths.data_dir, error=message)
        return 1

    client = None
    try:
        if args.src:
            payload, headers = args.src.read_bytes(), {}
        else:
            client = _client()
            payload, headers = _fetch(client, bulk_url, query)
    except Exception as exc:  # noqa: BLE001 - any acquisition failure is a FAIL receipt
        return fail(f"bulk fetch failed: {exc}")

    try:
        doc = json.loads(payload)
        gauges = doc.get("gauges") if isinstance(doc, dict) else None
        if not isinstance(gauges, list):
            raise ValueError("response has no 'gauges' list")
    except (ValueError, json.JSONDecodeError) as exc:
        return fail(f"bulk response unparseable: {exc}")

    bulk = _freeze(payload, record_id=f"gauges?{query_text}", url=bulk_url, query=query_text,
                   at=now, count=len(gauges), signature=schema_signature(gauges),
                   headers=headers, snapshot_dir=snapshot_dir)

    previous_state = {row["lid"]: row for row in store.load_gauge_state(paths.data_dir) if row.get("lid")}
    details: dict[str, DetailResult] = {}
    detail_manifestations: list[Manifestation] = []
    detail_failures: list[str] = []
    wanted = [
        str(g["lid"]).upper() for g in gauges
        if classify(g) == "retained"
        and needs_detail(previous_state.get(str(g["lid"]).upper()), now, float(source["detail_max_age_hours"]))
    ][: max(args.max_details, 0)]
    for lid in wanted:
        detail_url = source["endpoints"]["gauge_detail"].format(lid=lid)
        try:
            if args.src:
                if not args.details_src or not (args.details_src / f"{lid}.json").is_file():
                    continue
                raw, raw_headers = (args.details_src / f"{lid}.json").read_bytes(), {}
            else:
                raw, raw_headers = _fetch(client, detail_url)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("detail is not an object")
        except Exception as exc:  # noqa: BLE001 - one gauge's detail failing is not fatal
            detail_failures.append(lid)
            prev = previous_state.get(lid) or {}
            details[lid] = DetailResult(prev.get("detail"), prev.get("detail_manifestation_id"),
                                        prev.get("detail_retrieved_at"), error=str(exc)[:200])
            continue
        man = _freeze(raw, record_id=f"gauges/{lid}", url=detail_url, query=None, at=now,
                      count=1, signature="nwps.gauge[" + ",".join(sorted(parsed)) + "]",
                      headers=raw_headers, snapshot_dir=snapshot_dir)
        detail_manifestations.append(man)
        details[lid] = DetailResult(adapter.compact_detail(parsed), man.manifestation_id,
                                    _iso(now), fresh=True)
    if client is not None:
        client.close()

    index = MunicipioIndex.from_geojson(args.municipios)
    assets_path = args.assets or (paths.data_dir / "utility_assets.jsonl")
    current = store.current_by_event(store.load_records(paths.data_dir), adapter.CANONICAL_PREFIX)
    built = build_run(gauges, bulk, details, previous_state, current, index,
                      load_usgs_asset_ids(assets_path), now)
    if built.arithmetic["state"] != "PASS":
        return fail(f"source arithmetic does not close: {built.arithmetic}")

    summary = {
        "source_url": bulk_url,
        "retrieval_query": query_text,
        "byte_sha256": bulk.byte_sha256,
        "bulk_manifestation_id": bulk.manifestation_id,
        "arithmetic": built.arithmetic,
        "details_fetched": len(detail_manifestations),
        "detail_failures": sorted(detail_failures),
        **built.counts,
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, **summary}, indent=2, sort_keys=True))
        return 0

    referenced = {bulk.manifestation_id}
    referenced.update(r["detail_manifestation_id"] for r in built.state_rows if r.get("detail_manifestation_id"))
    try:
        applied = store.apply_source_run(
            store.SourceRun(SOURCE_ID, manifestations=[bulk, *detail_manifestations],
                            records=built.records, relationships=built.relationships),
            paths.data_dir,
            referenced_manifestation_ids=referenced,
        )
    except ValueError as exc:
        return fail(str(exc))
    store.write_jsonl(paths.gauge_state, built.state_rows)
    summary.update(applied)
    store.record_receipt(SOURCE_ID, status="PASS", attempted_at=now, data_dir=paths.data_dir,
                         summary=summary, referenced_manifestation_ids=referenced)
    store.append_accounting({"source_id": SOURCE_ID, "run_utc": _iso(now),
                             "arithmetic": built.arithmetic,
                             "byte_sha256": bulk.byte_sha256}, paths.data_dir)
    flooding = [r["lid"] for r in built.state_rows if r["flood_category"] in adapter.FLOOD_CATEGORIES]
    print(f"NWPS: {built.arithmetic['retained']}/{built.arithmetic['source']} PR gauges retained, "
          f"{built.counts['new_revisions']} new revision(s), {len(detail_manifestations)} detail(s) "
          f"refreshed, {len(detail_failures)} detail failure(s), in flood: {flooding or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
