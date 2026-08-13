#!/usr/bin/env python3
"""S07: freeze authoritative NCEI + USGS 2014-2016 raw denominators.

Research-only evidence acquisition.  This stage is deliberately non-interpretive:
it freezes source bytes, closes pagination, records parameter/unit/datum metadata,
and emits a replayable content-addressed manifest.  It does not assign drought-
concerning direction and therefore cannot itself activate S08.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

WINDOW_START = date(2014, 1, 1)
WINDOW_END = date(2016, 12, 31)
NCEI_STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
NCEI_INVENTORY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt"
NCEI_BY_STATION_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station"
USGS_BASE = "https://api.waterdata.usgs.gov/ogcapi/v0"
PR_BBOX = "-67.95,17.7,-65.2,18.7"
USER_AGENT = "aguayluz-pr-drought-s07/0.2"


@dataclass(frozen=True)
class FrozenObject:
    source_id: str
    source_url: str
    bytes: int
    sha256: str
    object_path: str
    retrieved_utc: str
    http_status: int | None
    etag: str | None
    last_modified: str | None
    content_type: str | None
    role: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def store_bytes(root: Path, source_id: str, url: str, data: bytes, headers: Any, role: str) -> FrozenObject:
    digest = sha256_bytes(data)
    path = root / "objects" / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha256_file(path) != digest:
        raise ValueError(f"content-address collision: {digest}")
    if not path.exists():
        path.write_bytes(data)
    return FrozenObject(
        source_id=source_id,
        source_url=url,
        bytes=len(data),
        sha256=digest,
        object_path=str(path.relative_to(root)),
        retrieved_utc=datetime.now(timezone.utc).isoformat(),
        http_status=getattr(headers, "status", None),
        etag=headers.headers.get("ETag") if hasattr(headers, "headers") else None,
        last_modified=headers.headers.get("Last-Modified") if hasattr(headers, "headers") else None,
        content_type=headers.headers.get("Content-Type") if hasattr(headers, "headers") else None,
        role=role,
    )


def fetch_bytes(root: Path, source_id: str, url: str, role: str, timeout: int = 180) -> tuple[FrozenObject, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        data = response.read()
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {url}")
        obj = store_bytes(root, source_id, url, data, response, role)
    return obj, data


def parse_ghcnd_pr_station_ids(text: str) -> set[str]:
    ids: set[str] = set()
    for line in text.splitlines():
        if len(line) >= 40 and line[38:40].strip() == "PR":
            station_id = line[0:11].strip()
            if station_id:
                ids.add(station_id)
    return ids


def parse_ghcnd_prcp_inventory(text: str, station_ids: set[str]) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        if len(line) < 45:
            continue
        sid = line[0:11].strip()
        if sid not in station_ids or line[31:35].strip() != "PRCP":
            continue
        try:
            first, last = int(line[36:40]), int(line[41:45])
        except ValueError:
            continue
        if first <= WINDOW_END.year and last >= WINDOW_START.year:
            result[sid] = (first, last)
    return result


def freeze_ncei(root: Path) -> dict[str, Any]:
    objects: list[FrozenObject] = []
    stations_obj, stations_raw = fetch_bytes(root, "NCEI_GHCND_STATIONS", NCEI_STATIONS_URL, "master_station_catalog")
    inventory_obj, inventory_raw = fetch_bytes(root, "NCEI_GHCND_INVENTORY", NCEI_INVENTORY_URL, "master_element_inventory")
    objects.extend([stations_obj, inventory_obj])
    station_ids = parse_ghcnd_pr_station_ids(stations_raw.decode("ascii", errors="replace"))
    prcp = parse_ghcnd_prcp_inventory(inventory_raw.decode("ascii", errors="replace"), station_ids)
    if not station_ids:
        raise ValueError("NCEI PR master-station denominator is empty")
    if not prcp:
        raise ValueError("NCEI PRCP 2014-2016 overlap denominator is empty")

    series: list[dict[str, Any]] = []
    for sid, years in sorted(prcp.items()):
        url = f"{NCEI_BY_STATION_BASE}/{sid}.csv.gz"
        obj, _ = fetch_bytes(root, f"NCEI_GHCND_BY_STATION_{sid}", url, "station_observations")
        objects.append(obj)
        series.append({"station_id": sid, "inventory_first_year": years[0], "inventory_last_year": years[1], "object_sha256": obj.sha256})

    denominator = {
        "state_code": "PR",
        "research_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "master_station_count": len(station_ids),
        "prcp_overlap_station_count": len(prcp),
        "station_ids": sorted(station_ids),
        "prcp_series": series,
        "selection_rule": "complete ghcnd-stations state=PR intersect complete ghcnd-inventory element=PRCP with period overlap 2014-2016",
        "qc_semantics": "raw GHCN-D by-station CSV retains MFLAG/QFLAG/SFLAG/OBS-TIME; no rejected value is silently repaired by S07",
    }
    derived = canonical_json_bytes(denominator)
    obj = store_bytes(root, "NCEI_PRCP_DENOMINATOR", "derived://NCEI_GHCND_STATIONS+INVENTORY", derived, object(), "derived_denominator")
    objects.append(obj)
    return {"denominator": denominator, "objects": [asdict(x) for x in objects]}


def _next_href(doc: dict[str, Any]) -> str | None:
    for link in doc.get("links", []):
        if link.get("rel") == "next" and link.get("href"):
            return str(link["href"])
    return None


def fetch_ogc_pages(root: Path, source_id: str, url: str, role: str) -> tuple[list[FrozenObject], list[dict[str, Any]], dict[str, Any]]:
    objects: list[FrozenObject] = []
    features: list[dict[str, Any]] = []
    page = 0
    current: str | None = url
    number_matched: int | None = None
    seen_urls: set[str] = set()
    while current:
        if current in seen_urls:
            raise ValueError(f"OGC pagination loop for {source_id}: {current}")
        seen_urls.add(current)
        page += 1
        obj, raw = fetch_bytes(root, f"{source_id}_PAGE_{page:04d}", current, role)
        objects.append(obj)
        doc = json.loads(raw)
        batch = doc.get("features")
        if not isinstance(batch, list):
            raise ValueError(f"OGC response lacks features list: {source_id} page {page}")
        features.extend(batch)
        nm = doc.get("numberMatched")
        if isinstance(nm, int):
            if number_matched is None:
                number_matched = nm
            elif nm != number_matched:
                raise ValueError(f"numberMatched drift for {source_id}: {number_matched}->{nm}")
        current = _next_href(doc)
    if number_matched is not None and len(features) != number_matched:
        raise ValueError(f"OGC pagination incomplete for {source_id}: observed={len(features)} matched={number_matched}")
    return objects, features, {"pages": page, "feature_count": len(features), "number_matched": number_matched}


def _ogc_url(collection: str, **params: str) -> str:
    return f"{USGS_BASE}/collections/{collection}/items?{urllib.parse.urlencode(params)}"


def _properties(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    return props if isinstance(props, dict) else {}


def freeze_usgs(root: Path) -> dict[str, Any]:
    objects: list[FrozenObject] = []
    closures: dict[str, Any] = {}

    # Freeze machine-readable schemas/queryables/reference dictionaries first.
    reference_targets = {
        "USGS_TIME_SERIES_METADATA_SCHEMA": f"{USGS_BASE}/collections/time-series-metadata/schema?f=json",
        "USGS_TIME_SERIES_METADATA_QUERYABLES": f"{USGS_BASE}/collections/time-series-metadata/queryables?f=json",
        "USGS_DAILY_SCHEMA": f"{USGS_BASE}/collections/daily/schema?f=json",
        "USGS_FIELD_MEASUREMENTS_SCHEMA": f"{USGS_BASE}/collections/field-measurements/schema?f=json",
        "USGS_FIELD_MEASUREMENTS_METADATA_SCHEMA": f"{USGS_BASE}/collections/field-measurements-metadata/schema?f=json",
    }
    for sid, url in reference_targets.items():
        obj, _ = fetch_bytes(root, sid, url, "schema_or_queryables")
        objects.append(obj)

    for collection in ("parameter-codes", "statistic-codes"):
        url = _ogc_url(collection, f="json", limit="10000")
        page_objs, features, closure = fetch_ogc_pages(root, f"USGS_{collection.upper().replace('-', '_')}", url, "reference_dictionary")
        objects.extend(page_objs)
        closures[collection] = closure
        if not features:
            raise ValueError(f"USGS reference dictionary unexpectedly empty: {collection}")

    metadata_url = _ogc_url("time-series-metadata", f="json", bbox=PR_BBOX, limit="10000")
    page_objs, ts_features, closure = fetch_ogc_pages(root, "USGS_TIME_SERIES_METADATA_PR", metadata_url, "time_series_metadata")
    objects.extend(page_objs)
    closures["time-series-metadata"] = closure
    if not ts_features:
        raise ValueError("USGS PR time-series metadata denominator unexpectedly empty")

    overlapping_ts: list[dict[str, Any]] = []
    semantics: dict[str, dict[str, set[str]]] = {}
    for feature in ts_features:
        p = _properties(feature)
        begin = str(p.get("begin") or p.get("begin_utc") or "")[:10]
        end = str(p.get("end") or p.get("end_utc") or "")[:10]
        if begin and begin > WINDOW_END.isoformat():
            continue
        if end and end < WINDOW_START.isoformat():
            continue
        tsid = str(feature.get("id") or p.get("id") or "")
        if not tsid:
            continue
        code = str(p.get("parameter_code") or "")
        overlapping_ts.append({
            "time_series_id": tsid,
            "monitoring_location_id": p.get("monitoring_location_id"),
            "parameter_code": code,
            "parameter_name": p.get("parameter_name"),
            "parameter_description": p.get("parameter_description"),
            "statistic_id": p.get("statistic_id"),
            "unit_of_measure": p.get("unit_of_measure"),
            "begin": begin or None,
            "end": end or None,
            "computation_period_identifier": p.get("computation_period_identifier"),
            "computation_identifier": p.get("computation_identifier"),
        })
        bucket = semantics.setdefault(code, {"units": set(), "statistics": set(), "names": set()})
        if p.get("unit_of_measure") is not None:
            bucket["units"].add(str(p["unit_of_measure"]))
        if p.get("statistic_id") is not None:
            bucket["statistics"].add(str(p["statistic_id"]))
        if p.get("parameter_name") is not None:
            bucket["names"].add(str(p["parameter_name"]))
    if not overlapping_ts:
        raise ValueError("USGS time-series metadata has zero series overlapping 2014-2016")

    interval = "2014-01-01T00:00:00Z/2016-12-31T23:59:59Z"
    daily_url = _ogc_url("daily", f="json", bbox=PR_BBOX, datetime=interval, limit="10000")
    page_objs, daily_features, closure = fetch_ogc_pages(root, "USGS_DAILY_PR_2014_2016", daily_url, "daily_observations")
    objects.extend(page_objs)
    closures["daily"] = closure
    if not daily_features:
        raise ValueError("USGS daily PR 2014-2016 denominator unexpectedly empty")

    field_url = _ogc_url("field-measurements", f="json", bbox=PR_BBOX, datetime=interval, limit="10000")
    page_objs, field_features, closure = fetch_ogc_pages(root, "USGS_FIELD_MEASUREMENTS_PR_2014_2016", field_url, "field_measurements")
    objects.extend(page_objs)
    closures["field-measurements"] = closure

    fm_meta_url = _ogc_url("field-measurements-metadata", f="json", bbox=PR_BBOX, limit="10000")
    page_objs, fm_meta_features, closure = fetch_ogc_pages(root, "USGS_FIELD_MEASUREMENTS_METADATA_PR", fm_meta_url, "field_measurements_metadata")
    objects.extend(page_objs)
    closures["field-measurements-metadata"] = closure

    vertical_datums = sorted({str(_properties(f).get("vertical_datum")) for f in field_features if _properties(f).get("vertical_datum") is not None})
    field_parameter_units: dict[str, set[str]] = {}
    for f in field_features:
        p = _properties(f)
        code = str(p.get("parameter_code") or "")
        if not code:
            continue
        field_parameter_units.setdefault(code, set())
        if p.get("unit_of_measure") is not None:
            field_parameter_units[code].add(str(p["unit_of_measure"]))

    semantic_capture = {
        "time_series": {
            code: {"units": sorted(v["units"]), "statistics": sorted(v["statistics"]), "names": sorted(v["names"])}
            for code, v in sorted(semantics.items())
        },
        "field_measurement_units": {k: sorted(v) for k, v in sorted(field_parameter_units.items())},
        "field_vertical_datums": vertical_datums,
        "drought_concerning_direction": None,
        "direction_status": "intentionally_unassigned_in_S07_requires_S08_parameter_adjudication",
    }
    denominator = {
        "bbox_epsg4326": [float(x) for x in PR_BBOX.split(",")],
        "research_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "time_series_metadata_feature_count": len(ts_features),
        "overlapping_time_series_count": len(overlapping_ts),
        "daily_observation_count": len(daily_features),
        "field_measurement_count": len(field_features),
        "field_measurement_metadata_count": len(fm_meta_features),
        "closures": closures,
        "overlapping_time_series": overlapping_ts,
        "semantic_capture": semantic_capture,
        "s08_activation_ready": False,
        "s08_block_reason": "S07 freezes authoritative parameter/unit/statistic/datum metadata but does not assign drought-concerning direction",
    }
    derived = canonical_json_bytes(denominator)
    obj = store_bytes(root, "USGS_PR_2014_2016_DENOMINATOR", "derived://USGS_OGC_PAGINATED_RAW", derived, object(), "derived_denominator")
    objects.append(obj)
    return {"denominator": denominator, "objects": [asdict(x) for x in objects]}


def verify_replay(root: Path, objects: list[dict[str, Any]]) -> dict[str, Any]:
    for obj in objects:
        path = root / obj["object_path"]
        if not path.is_file():
            raise ValueError(f"replay missing object: {obj['sha256']}")
        if path.stat().st_size != obj["bytes"] or sha256_file(path) != obj["sha256"]:
            raise ValueError(f"replay identity mismatch: {obj['source_id']}")
    return {"status": "replay_pass", "network_required": False, "verified_objects": len(objects)}


def freeze(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    ncei = freeze_ncei(root)
    usgs = freeze_usgs(root)
    objects = ncei["objects"] + usgs["objects"]
    replay = verify_replay(root, objects)
    manifest = {
        "schema_version": "aguayluz.drought-s07-freeze/v0.2",
        "stage": "S07",
        "research_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "ncei": ncei["denominator"],
        "usgs": usgs["denominator"],
        "objects": objects,
        "replay": replay,
        "certification": {
            "ncei_raw_denominator": "certified",
            "usgs_raw_metadata_and_observations": "certified",
            "s07": "certified",
            "s08": "blocked_pending_direction_semantics",
        },
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path = root / "manifests" / "s07_ncei_usgs_2014_2016.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    (root / "manifests" / "s07_ncei_usgs_2014_2016.sha256").write_text(sha256_bytes(manifest_bytes) + "\n")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = freeze(args.output.resolve())
    print(manifest)
    print(sha256_file(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
