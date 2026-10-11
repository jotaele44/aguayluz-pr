#!/usr/bin/env python3
"""NWS Stage IV Puerto Rico rainfall (QPE) → NWS hydromet plane.

Successor of the "River Forecast Centers Daily Quantitative Precipitation Estimates"
entry on the legacy IDP-GIS catalog. The CloudGIS ``obs/rfc_qpe`` mosaic does not cover
Puerto Rico; NWPS publishes a dedicated PR grid as dated GeoTIFFs:

    https://water.noaa.gov/resources/downloads/precip/stageIV/YYYY/MM/DD/
        nws_precip_{1day,last7days,last30days}_YYYYMMDD_pr.tif

Each file is a 205×205 HRAP grid (4.76 km) with four float32 bands — observation,
PRISM normal, departure, percent of normal — in inches, for the 12Z-12Z window ending
on the file date.

Per run:

1. Find the latest data day with a 1-day file (looking back ``--lookback-days``), fetch
   its three windows, and back-fill missing 1-day files for the previous
   ``--backfill-days`` days. Bytes are hashed before they are opened.
2. Summarise each window per municipio over the HRAP cells whose centres fall inside the
   Census polygon (aguayluz.hydromet.spatial.raster_cells_by_municipio).
3. Arithmetic per file: 78 municipio zones = RETAINED (valid cells) + UNRESOLVED.
4. One record per municipio × window × day; a re-processed file supersedes it.
   1-day history is kept 30 days, 7- and 30-day windows only for the latest day.

Usage:
    python scripts/ingest_stage_iv_pr.py                     # live
    python scripts/ingest_stage_iv_pr.py --dry-run
    python scripts/ingest_stage_iv_pr.py --src-dir DIR --date 20261009   # offline
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz.hazard_adapters import stage_iv_qpe as adapter  # noqa: E402
from aguayluz.hazard_plane import (  # noqa: E402
    EntityKind,
    EvidenceClass,
    HazardRecord,
    HazardRelationship,
    Manifestation,
    RelationshipType,
    SpatialState,
    source_arithmetic,
)
from aguayluz.hydromet import USER_AGENT, store  # noqa: E402

SOURCE_ID = "stage_iv_pr"
SOURCE_SYSTEM = "NWPS Stage IV downloads (PR GeoTIFF)"
ONE_DAY_RETENTION = timedelta(days=30)


@dataclass
class GridFile:
    window: str
    data_date: date
    url: str
    payload: bytes
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class BuildResult:
    records: list[HazardRecord] = field(default_factory=list)
    relationships: list[HazardRelationship] = field(default_factory=list)
    manifestations: list[Manifestation] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    zones: int = 0
    retained: int = 0
    unresolved: int = 0


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def grid_url(template: str, window: str, day: date) -> str:
    return template.format(yyyy=f"{day:%Y}", mm=f"{day:%m}", dd=f"{day:%d}",
                           window=window, yyyymmdd=f"{day:%Y%m%d}")


def file_name(window: str, day: date) -> str:
    return f"nws_precip_{window}_{day:%Y%m%d}_pr.tif"


def summarise_grid(payload: bytes, selections_cache: dict[Any, Any], index: Any) -> dict[str, Any]:
    """Open one GeoTIFF from bytes and summarise it per municipio."""
    from rasterio.io import MemoryFile

    from aguayluz.hydromet.spatial import raster_cells_by_municipio

    with MemoryFile(payload) as memfile, memfile.open() as src:
        if src.count < 2:
            raise ValueError(f"expected observation + normal bands, found {src.count}")
        data_time = adapter.parse_data_time(src.tags().get("data_time"))
        key = (src.crs.to_wkt(), tuple(src.transform), src.height, src.width)
        if key not in selections_cache:
            selections_cache[key] = raster_cells_by_municipio(index, src.crs, src.transform,
                                                              (src.height, src.width))
        obs = src.read(1, masked=True)
        normal = src.read(2, masked=True)
    zones = []
    for sel in selections_cache[key]:
        obs_cells = obs[sel.mask].compressed() if sel.cell_count else obs[:0].compressed()
        normal_cells = normal[sel.mask].compressed() if sel.cell_count else normal[:0].compressed()
        values = adapter.zone_values(
            obs_mean=float(obs_cells.mean()) if obs_cells.size else None,
            obs_max=float(obs_cells.max()) if obs_cells.size else None,
            normal_mean=float(normal_cells.mean()) if normal_cells.size else None,
            cell_count=int(obs_cells.size),
            normal_cell_count=int(normal_cells.size),
        )
        zones.append({"selection": sel, "values": values})
    return {"data_time": data_time, "zones": zones}


def build_run(
    files: list[GridFile],
    current: dict[str, HazardRecord],
    index: Any,
    retrieved_at: datetime,
    snapshot_dir: Path | None,
) -> BuildResult:
    """Freeze, summarise and normalize every fetched grid file."""
    result = BuildResult()
    cache: dict[Any, Any] = {}
    for grid in files:
        man = store.freeze_bytes(
            SOURCE_ID, grid.payload,
            source_authority=adapter.SOURCE_AUTHORITY,
            source_system=SOURCE_SYSTEM,
            source_record_id=file_name(grid.window, grid.data_date),
            source_url=grid.url,
            retrieved_at=retrieved_at,
            schema_signature="stageiv.pr.geotiff[observation,normal,departure_from_normal,percent_of_normal]",
            headers=grid.headers,
            snapshot_dir=snapshot_dir,
            extension="tif",
        )
        summary = summarise_grid(grid.payload, cache, index)
        data_time = summary["data_time"]
        if data_time is None or data_time.date() != grid.data_date:
            raise ValueError(
                f"{file_name(grid.window, grid.data_date)}: data_time tag {data_time} does not "
                f"match the file date"
            )
        man = man.model_copy(update={"record_count": len(summary["zones"])})
        result.manifestations.append(man)
        retained = 0
        for zone in summary["zones"]:
            sel, values = zone["selection"], zone["values"]
            result.zones += 1
            event_id = adapter.canonical_event_id(grid.window, sel.geoid, grid.data_date)
            head = current.get(event_id)
            if values["obs_mean_in"] is None:
                result.unresolved += 1
            else:
                result.retained += 1
                retained += 1
            if head is not None and head.normalized_values.get("values_digest") == adapter.values_digest(values):
                continue
            record = adapter.normalize(
                values, man.manifestation_id,
                window=grid.window, geoid=sel.geoid, municipio=sel.municipio,
                data_time=data_time, source_file=file_name(grid.window, grid.data_date),
                method=sel.method, source_url=grid.url,
                supersedes_record_id=head.record_id if head else None,
            )
            result.records.append(record)
            if record.municipality_id:
                result.relationships.append(HazardRelationship(
                    relationship_id=store.relationship_id(record.record_id, "SPATIALLY_INTERSECTS", sel.geoid),
                    subject_id=record.record_id,
                    predicate=RelationshipType.SPATIALLY_INTERSECTS,
                    object_id=sel.geoid,
                    object_kind=EntityKind.MUNICIPALITY,
                    # Cell centres inside the polygon are point-in-polygon evidence; the
                    # touching-cells fallback is only proximity.
                    evidence_class=(EvidenceClass.POINT_IN_POLYGON
                                    if sel.spatial_state == SpatialState.FULLY_WITHIN
                                    else EvidenceClass.PROXIMITY),
                    source_manifestation_ids=[man.manifestation_id],
                    effective_from=record.observed_from,
                    effective_to=record.observed_to,
                    method=f"{sel.method}; cells={values['cell_count']}",
                    spatial_state=sel.spatial_state if sel.spatial_state != SpatialState.NULL_EMPTY else None,
                ))
        result.files.append({
            "window": grid.window,
            "data_date": f"{grid.data_date:%Y-%m-%d}",
            "url": grid.url,
            "byte_sha256": man.byte_sha256,
            "manifestation_id": man.manifestation_id,
            "zones": len(summary["zones"]),
            "retained": retained,
        })
    return result


def retention_policy(records: list[HazardRecord]):
    """1-day kept 30 days behind the newest 1-day; longer windows only at their newest day."""
    newest: dict[str, date] = {}
    for record in records:
        window = record.normalized_values.get("window")
        day = record.observed_to.date() if record.observed_to else None
        if window and day and (window not in newest or day > newest[window]):
            newest[window] = day

    def keep(current: HazardRecord) -> bool:
        window = current.normalized_values.get("window")
        day = current.observed_to.date() if current.observed_to else None
        if not window or day is None or window not in newest:
            return True
        if window == "1day":
            return newest[window] - day <= ONE_DAY_RETENTION
        return day == newest[window]

    return keep


# ---------------------------------------------------------------- acquisition


def _fetch(client: Any, url: str) -> tuple[bytes, dict[str, str]] | None:
    """Bytes for ``url``; None when NWPS has not published it (404)."""
    from aguayluz.http_retry import get_with_retry

    response = get_with_retry(url, client=client)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content, dict(response.headers)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-dir", type=Path, help="offline directory of nws_precip_*_pr.tif files")
    ap.add_argument("--date", help="data day YYYYMMDD (required with --src-dir; default: latest)")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--municipios", type=Path, default=None)
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--lookback-days", type=int, default=4)
    ap.add_argument("--backfill-days", type=int, default=3)
    ap.add_argument("--now", help="override the run clock (ISO 8601), for reproducible tests")
    ap.add_argument("--dry-run", action="store_true", help="fetch and build; write nothing")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from aguayluz.hydromet.spatial import MunicipioIndex

    try:
        now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
               else datetime.now(timezone.utc))
        requested = datetime.strptime(args.date, "%Y%m%d").date() if args.date else None
    except ValueError as exc:
        print(f"bad --now/--date: {exc}", file=sys.stderr)
        return 2
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if args.src_dir and requested is None:
        print("--src-dir needs --date", file=sys.stderr)
        return 2
    source = store.registry_source(SOURCE_ID, store.load_source_registry(args.registry))
    if source is None:
        print(f"{SOURCE_ID} missing from config/hydromet_sources.v1.json", file=sys.stderr)
        return 2
    template = source["endpoints"]["grid"]
    windows = list(source["windows"])
    paths = store.hydromet_paths(args.data_dir)

    def fail(message: str) -> int:
        print(f"ingest_stage_iv_pr: FAIL — {message}", file=sys.stderr)
        if not args.dry_run:
            store.record_receipt(SOURCE_ID, status="FAIL", attempted_at=now,
                                 data_dir=paths.data_dir, error=message)
        return 1

    existing = store.load_records(paths.data_dir)
    have_1day = {
        r.observed_to.date() for r in existing
        if r.canonical_event_id.startswith(adapter.CANONICAL_PREFIX)
        and r.normalized_values.get("window") == "1day" and r.observed_to
    }

    files: list[GridFile] = []
    missing: list[str] = []
    client = None
    try:
        if args.src_dir:
            for window in windows:
                path = args.src_dir / file_name(window, requested)
                if path.is_file():
                    files.append(GridFile(window, requested, grid_url(template, window, requested),
                                          path.read_bytes()))
                else:
                    missing.append(file_name(window, requested))
        else:
            import httpx

            client = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": USER_AGENT})
            candidates = [requested] if requested else [
                now.date() - timedelta(days=i) for i in range(max(args.lookback_days, 1))
            ]
            latest = None
            for day in candidates:
                got = _fetch(client, grid_url(template, "1day", day))
                if got is not None:
                    latest = day
                    files.append(GridFile("1day", day, grid_url(template, "1day", day), *got))
                    break
            if latest is None:
                return fail(f"no 1-day Stage IV PR file published for {candidates}")
            for window in windows:
                if window == "1day":
                    continue
                got = _fetch(client, grid_url(template, window, latest))
                if got is None:
                    missing.append(file_name(window, latest))
                else:
                    files.append(GridFile(window, latest, grid_url(template, window, latest), *got))
            for back in range(1, max(args.backfill_days, 0) + 1):
                day = latest - timedelta(days=back)
                if day in have_1day:
                    continue
                got = _fetch(client, grid_url(template, "1day", day))
                if got is None:
                    missing.append(file_name("1day", day))
                else:
                    files.append(GridFile("1day", day, grid_url(template, "1day", day), *got))
    except Exception as exc:  # noqa: BLE001 - any acquisition failure is a FAIL receipt
        return fail(f"fetch failed: {exc}")
    finally:
        if client is not None:
            client.close()
    if not files:
        return fail(f"no Stage IV PR files found ({missing})")

    index = MunicipioIndex.from_geojson(args.municipios)
    current = store.current_by_event(existing, adapter.CANONICAL_PREFIX)
    try:
        built = build_run(files, current, index, now,
                          None if args.dry_run else paths.snapshot_dir(SOURCE_ID))
    except Exception as exc:  # noqa: BLE001 - unreadable raster or mismatched tag
        return fail(f"grid unreadable: {exc}")
    arithmetic = source_arithmetic(built.zones, built.retained, 0, built.unresolved)
    if arithmetic["state"] != "PASS":
        return fail(f"source arithmetic does not close: {arithmetic}")

    latest_day = max(f.data_date for f in files)
    summary = {
        "data_date": f"{latest_day:%Y-%m-%d}",
        "files": built.files,
        "windows_missing": sorted(missing),
        "arithmetic": arithmetic,
        "new_revisions": len(built.records),
        "byte_sha256": next((f["byte_sha256"] for f in built.files
                             if f["window"] == "1day" and f["data_date"] == f"{latest_day:%Y-%m-%d}"), None),
        "source_url": grid_url(template, "1day", latest_day),
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, **summary}, indent=2, sort_keys=True))
        return 0
    try:
        applied = store.apply_source_run(
            store.SourceRun(SOURCE_ID, manifestations=built.manifestations, records=built.records,
                            relationships=built.relationships,
                            retain_event=retention_policy(existing + built.records)),
            paths.data_dir,
        )
    except ValueError as exc:
        return fail(str(exc))
    summary.update(applied)
    store.record_receipt(SOURCE_ID, status="PASS", attempted_at=now, data_dir=paths.data_dir,
                         summary=summary)
    store.append_accounting({"source_id": SOURCE_ID, "run_utc": _iso(now), "arithmetic": arithmetic,
                             "files": built.files}, paths.data_dir)
    print(f"Stage IV PR: data day {latest_day:%Y-%m-%d}, {len(built.files)} file(s), "
          f"{arithmetic['retained']}/{arithmetic['source']} municipio zones retained, "
          f"{len(built.records)} new revision(s), missing: {missing or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
