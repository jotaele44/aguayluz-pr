#!/usr/bin/env python3
"""S07 v0.3: corrected USGS observation acquisition.

Supersedes the v0.2 monolithic /daily bbox query that authoritative runtime
rejected with HTTP 400. NCEI and USGS metadata contracts are preserved; daily
observations are fetched by metadata-bound Daily time_series_id.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.drought_resilience import freeze_denominators as base


def freeze_usgs(root: Path) -> dict[str, Any]:
    objects: list[base.FrozenObject] = []
    closures: dict[str, Any] = {}

    reference_targets = {
        "USGS_TIME_SERIES_METADATA_SCHEMA": f"{base.USGS_BASE}/collections/time-series-metadata/schema?f=json",
        "USGS_TIME_SERIES_METADATA_QUERYABLES": f"{base.USGS_BASE}/collections/time-series-metadata/queryables?f=json",
        "USGS_DAILY_SCHEMA": f"{base.USGS_BASE}/collections/daily/schema?f=json",
        "USGS_DAILY_QUERYABLES": f"{base.USGS_BASE}/collections/daily/queryables?f=json",
        "USGS_FIELD_MEASUREMENTS_SCHEMA": f"{base.USGS_BASE}/collections/field-measurements/schema?f=json",
        "USGS_FIELD_MEASUREMENTS_QUERYABLES": f"{base.USGS_BASE}/collections/field-measurements/queryables?f=json",
        "USGS_FIELD_MEASUREMENTS_METADATA_SCHEMA": f"{base.USGS_BASE}/collections/field-measurements-metadata/schema?f=json",
    }
    for sid, url in reference_targets.items():
        obj, _ = base.fetch_bytes(root, sid, url, "schema_or_queryables")
        objects.append(obj)

    for collection in ("parameter-codes", "statistic-codes"):
        url = base._ogc_url(collection, f="json", limit="10000")
        page_objs, features, closure = base.fetch_ogc_pages(
            root,
            f"USGS_{collection.upper().replace('-', '_')}",
            url,
            "reference_dictionary",
        )
        objects.extend(page_objs)
        closures[collection] = closure
        if not features:
            raise ValueError(f"USGS reference dictionary unexpectedly empty: {collection}")

    metadata_url = base._ogc_url(
        "time-series-metadata", f="json", bbox=base.PR_BBOX, limit="10000"
    )
    page_objs, ts_features, closure = base.fetch_ogc_pages(
        root, "USGS_TIME_SERIES_METADATA_PR", metadata_url, "time_series_metadata"
    )
    objects.extend(page_objs)
    closures["time-series-metadata"] = closure
    if not ts_features:
        raise ValueError("USGS PR time-series metadata denominator unexpectedly empty")

    overlapping_ts: list[dict[str, Any]] = []
    semantics: dict[str, dict[str, set[str]]] = {}
    for feature in ts_features:
        p = base._properties(feature)
        begin = str(p.get("begin") or p.get("begin_utc") or "")[:10]
        end = str(p.get("end") or p.get("end_utc") or "")[:10]
        if begin and begin > base.WINDOW_END.isoformat():
            continue
        if end and end < base.WINDOW_START.isoformat():
            continue
        tsid = str(feature.get("id") or p.get("id") or "")
        if not tsid:
            continue
        code = str(p.get("parameter_code") or "")
        row = {
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
        }
        overlapping_ts.append(row)
        bucket = semantics.setdefault(code, {"units": set(), "statistics": set(), "names": set()})
        if p.get("unit_of_measure") is not None:
            bucket["units"].add(str(p["unit_of_measure"]))
        if p.get("statistic_id") is not None:
            bucket["statistics"].add(str(p["statistic_id"]))
        if p.get("parameter_name") is not None:
            bucket["names"].add(str(p["parameter_name"]))
    if not overlapping_ts:
        raise ValueError("USGS time-series metadata has zero series overlapping 2014-2016")

    daily_series = [
        row for row in overlapping_ts if row["computation_period_identifier"] == "Daily"
    ]
    if not daily_series:
        raise ValueError("USGS metadata has zero Daily series overlapping 2014-2016")

    interval = "2014-01-01/2016-12-31"
    daily_count = 0
    daily_series_closure: list[dict[str, Any]] = []
    for index, row in enumerate(daily_series, start=1):
        tsid = str(row["time_series_id"])
        url = base._ogc_url(
            "daily",
            f="json",
            time_series_id=tsid,
            datetime=interval,
            limit="10000",
        )
        page_objs, features, closure = base.fetch_ogc_pages(
            root,
            f"USGS_DAILY_TS_{index:04d}_{tsid}",
            url,
            "daily_observations",
        )
        objects.extend(page_objs)
        daily_count += len(features)
        daily_series_closure.append(
            {
                "time_series_id": tsid,
                "feature_count": len(features),
                "pages": closure["pages"],
                "number_matched": closure["number_matched"],
            }
        )
    closures["daily"] = {
        "series_count": len(daily_series),
        "feature_count": daily_count,
        "series": daily_series_closure,
        "selection": "metadata-bound computation_period_identifier=Daily and period overlap 2014-2016",
    }
    if daily_count == 0:
        raise ValueError("USGS Daily series returned zero observations for 2014-2016")

    fm_meta_url = base._ogc_url(
        "field-measurements-metadata", f="json", bbox=base.PR_BBOX, limit="10000"
    )
    page_objs, fm_meta_features, closure = base.fetch_ogc_pages(
        root,
        "USGS_FIELD_MEASUREMENTS_METADATA_PR",
        fm_meta_url,
        "field_measurements_metadata",
    )
    objects.extend(page_objs)
    closures["field-measurements-metadata"] = closure

    field_url = base._ogc_url(
        "field-measurements",
        f="json",
        bbox=base.PR_BBOX,
        datetime=interval,
        limit="10000",
    )
    page_objs, field_features, closure = base.fetch_ogc_pages(
        root,
        "USGS_FIELD_MEASUREMENTS_PR_2014_2016",
        field_url,
        "field_measurements",
    )
    objects.extend(page_objs)
    closures["field-measurements"] = closure

    vertical_datums = sorted(
        {
            str(base._properties(f).get("vertical_datum"))
            for f in field_features
            if base._properties(f).get("vertical_datum") is not None
        }
    )
    field_parameter_units: dict[str, set[str]] = {}
    for feature in field_features:
        p = base._properties(feature)
        code = str(p.get("parameter_code") or "")
        if not code:
            continue
        field_parameter_units.setdefault(code, set())
        if p.get("unit_of_measure") is not None:
            field_parameter_units[code].add(str(p["unit_of_measure"]))

    semantic_capture = {
        "time_series": {
            code: {
                "units": sorted(value["units"]),
                "statistics": sorted(value["statistics"]),
                "names": sorted(value["names"]),
            }
            for code, value in sorted(semantics.items())
        },
        "field_measurement_units": {
            code: sorted(units) for code, units in sorted(field_parameter_units.items())
        },
        "field_vertical_datums": vertical_datums,
        "drought_concerning_direction": None,
        "direction_status": "intentionally_unassigned_in_S07_requires_S08_parameter_adjudication",
    }
    denominator = {
        "bbox_epsg4326": [float(x) for x in base.PR_BBOX.split(",")],
        "research_window": [base.WINDOW_START.isoformat(), base.WINDOW_END.isoformat()],
        "time_series_metadata_feature_count": len(ts_features),
        "overlapping_time_series_count": len(overlapping_ts),
        "daily_time_series_count": len(daily_series),
        "daily_observation_count": daily_count,
        "field_measurement_count": len(field_features),
        "field_measurement_metadata_count": len(fm_meta_features),
        "closures": closures,
        "overlapping_time_series": overlapping_ts,
        "semantic_capture": semantic_capture,
        "s08_activation_ready": False,
        "s08_block_reason": "S07 freezes authoritative parameter/unit/statistic/datum metadata but does not assign drought-concerning direction",
    }
    derived = base.canonical_json_bytes(denominator)
    obj = base.store_bytes(
        root,
        "USGS_PR_2014_2016_DENOMINATOR",
        "derived://USGS_OGC_METADATA_BOUND_RAW",
        derived,
        object(),
        "derived_denominator",
    )
    objects.append(obj)
    return {"denominator": denominator, "objects": [asdict(item) for item in objects]}


def freeze(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    ncei = base.freeze_ncei(root)
    usgs = freeze_usgs(root)
    objects = ncei["objects"] + usgs["objects"]
    replay = base.verify_replay(root, objects)
    manifest = {
        "schema_version": "aguayluz.drought-s07-freeze/v0.3",
        "stage": "S07",
        "research_window": [base.WINDOW_START.isoformat(), base.WINDOW_END.isoformat()],
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
    payload = base.canonical_json_bytes(manifest)
    path = root / "manifests" / "s07_ncei_usgs_2014_2016.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    (root / "manifests" / "s07_ncei_usgs_2014_2016.sha256").write_text(
        base.sha256_bytes(payload) + "\n"
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = freeze(args.output.resolve())
    print(manifest)
    print(base.sha256_file(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
