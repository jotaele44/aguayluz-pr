#!/usr/bin/env python3
"""Ingest the authoritative weekly USDM vector footprint and Puerto Rico statistics.

The existing ``ingest_drought_usdm.py`` intentionally reduces each municipio to one
category.  This producer keeps a second, display-oriented lane with the official
weekly vector geometry and Puerto Rico-wide cumulative area percentages.

Source geometry is the NDMC/USDM date-specific GeoJSON.  The source file is national;
only polygon components whose coordinates intersect Puerto Rico's bounded extent are
retained.  No interpolation, smoothing or inferred drought boundary is performed.

The statistics source is the USDM StateStatistics REST service with Puerto Rico state
FIPS 72.  Its D0..D4 percentages are cumulative "at least this category" values and
are stored as such.

    python scripts/ingest_drought_usdm_footprint.py
    python scripts/ingest_drought_usdm_footprint.py --src-geo tests/fixtures/usdm.geojson \
        --src-stats tests/fixtures/usdm_pr_state_stats.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "drought_usdm_footprint.json"

STATS_URL = (
    "https://usdmdataservices.unl.edu/api/StateStatistics/"
    "GetDroughtSeverityStatisticsByAreaPercent"
)
GEO_BASE = "https://droughtmonitor.unl.edu/Data/json"
PR_STATE_FIPS = "72"
# Deliberately generous around Puerto Rico and its nearby islands, but excludes CONUS,
# Alaska and Hawaii.  This is a selection envelope, not a clipping or drought boundary.
PR_BOUNDS = (-67.6, 17.5, -65.0, 18.8)
CATEGORIES = ("D0", "D1", "D2", "D3", "D4")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_mapdate(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) != 8:
        return None
    try:
        parsed = datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return None
    return parsed.isoformat()


def _mapdate_token(value: str) -> str:
    return value.replace("-", "")


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def fetch_stats(today: date, *, weeks: int = 12) -> tuple[bytes, str]:
    start = today - timedelta(days=max(14, weeks * 7 + 7))
    params = {
        "aoi": PR_STATE_FIPS,
        "startdate": f"{start.month}/{start.day}/{start.year}",
        "enddate": f"{today.month}/{today.day}/{today.year}",
        "statisticsType": "1",
    }
    response = httpx.get(
        STATS_URL,
        params=params,
        headers={"Accept": "text/csv", "User-Agent": "AguaYLuz-PR/1.0"},
        timeout=120,
    )
    response.raise_for_status()
    return response.content, str(response.url)


def parse_stats(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8-sig")
    rows = []
    for source in csv.DictReader(io.StringIO(text)):
        map_date = _parse_mapdate(source.get("MapDate"))
        if map_date is None:
            continue
        stats: dict[str, float] = {}
        for key in ("None", *CATEGORIES):
            value = _number(source.get(key))
            if value is not None:
                stats[key] = value
        if not all(key in stats for key in CATEGORIES):
            continue
        rows.append({
            "map_date": map_date,
            "valid_start": str(source.get("ValidStart") or "")[:10] or None,
            "valid_end": str(source.get("ValidEnd") or "")[:10] or None,
            "none_pct": stats.get("None"),
            "D0": stats["D0"],
            "D1": stats["D1"],
            "D2": stats["D2"],
            "D3": stats["D3"],
            "D4": stats["D4"],
            "semantics": "cumulative_percent_area_at_or_above_category",
        })
    rows.sort(key=lambda row: row["map_date"])
    return rows


def fetch_geo(map_date: str) -> tuple[bytes, str]:
    url = f"{GEO_BASE}/USDM_{_mapdate_token(map_date)}.json"
    response = httpx.get(
        url,
        headers={"Accept": "application/json", "User-Agent": "AguaYLuz-PR/1.0"},
        timeout=180,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.content, str(response.url)


def _iter_points(coords: Any) -> Iterable[tuple[float, float]]:
    if (
        isinstance(coords, list)
        and len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
    ):
        yield float(coords[0]), float(coords[1])
        return
    if isinstance(coords, list):
        for child in coords:
            yield from _iter_points(child)


def _bounds(coords: Any) -> tuple[float, float, float, float] | None:
    points = list(_iter_points(coords))
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _intersects_pr(coords: Any) -> bool:
    bounds = _bounds(coords)
    if bounds is None:
        return False
    minx, miny, maxx, maxy = bounds
    pminx, pminy, pmaxx, pmaxy = PR_BOUNDS
    return not (maxx < pminx or minx > pmaxx or maxy < pminy or miny > pmaxy)


def _entirely_in_pr(coords: Any) -> bool:
    bounds = _bounds(coords)
    if bounds is None:
        return False
    minx, miny, maxx, maxy = bounds
    pminx, pminy, pmaxx, pmaxy = PR_BOUNDS
    return minx >= pminx and maxx <= pmaxx and miny >= pminy and maxy <= pmaxy


def _category(properties: dict[str, Any]) -> str | None:
    for key in ("DM", "dm", "DROUGHT", "drought", "category", "Category"):
        raw = properties.get(key)
        if raw is None:
            continue
        text = str(raw).strip().upper()
        if text in CATEGORIES:
            return text
        if text in {"0", "1", "2", "3", "4"}:
            return f"D{text}"
    return None


def _extract_geometry(geometry: dict[str, Any]) -> dict[str, Any] | None:
    """Return only PR multipart components; never construct/interpolate boundaries."""
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "MultiPolygon" and isinstance(coords, list):
        polygons = [polygon for polygon in coords if _intersects_pr(polygon)]
        if not polygons:
            return None
        # A component that merely touches the selection envelope but extends far outside
        # it indicates an unexpected source topology.  Fail closed instead of clipping it.
        if any(not _entirely_in_pr(polygon) for polygon in polygons):
            raise ValueError("USDM polygon component crosses the Puerto Rico selection envelope")
        return {"type": "MultiPolygon", "coordinates": polygons}
    if kind == "Polygon" and isinstance(coords, list):
        if not _intersects_pr(coords):
            return None
        if not _entirely_in_pr(coords):
            raise ValueError("USDM Polygon crosses the Puerto Rico selection envelope")
        return {"type": "Polygon", "coordinates": coords}
    return None


def extract_pr_footprint(raw: bytes) -> tuple[dict[str, Any], dict[str, int]]:
    document = json.loads(raw)
    if document.get("type") != "FeatureCollection":
        raise ValueError("USDM GeoJSON must be a FeatureCollection")
    output = []
    source_features = document.get("features")
    if not isinstance(source_features, list):
        raise ValueError("USDM GeoJSON features must be a list")
    category_counts = {category: 0 for category in CATEGORIES}
    for index, feature in enumerate(source_features):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        category = _category(props)
        if category is None:
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        selected = _extract_geometry(geometry)
        if selected is None:
            continue
        category_counts[category] += 1
        output.append({
            "type": "Feature",
            "id": f"{category}-{index}",
            "properties": {
                "category": category,
                "source_category": props.get("DM", props.get("dm", category)),
                "derived": False,
                "selection_method": "official_vector_component_pr_bbox_selection",
            },
            "geometry": selected,
        })
    if not output:
        raise ValueError("No Puerto Rico USDM vector components found")
    return {"type": "FeatureCollection", "features": output}, category_counts


def build_document(
    *,
    stats_raw: bytes,
    stats_url: str,
    geo_raw: bytes,
    geo_url: str,
    retrieved_at: str,
) -> dict[str, Any]:
    history = parse_stats(stats_raw)
    if not history:
        raise ValueError("USDM Puerto Rico statistics returned no usable rows")
    current = history[-1]
    expected_token = _mapdate_token(current["map_date"])
    if expected_token not in geo_url:
        raise ValueError("USDM geometry URL does not match latest statistics map date")
    footprint, counts = extract_pr_footprint(geo_raw)
    return {
        "schema_version": "aguayluz.usdm-drought-operations/v0.1",
        "map_date": current["map_date"],
        "retrieved_at": retrieved_at,
        "authority": "NDMC/USDM (USDA/NOAA/NASA partnership)",
        "evidence_tier": "T1",
        "scope": "Puerto Rico",
        "statistics": current,
        "history": history,
        "footprint": footprint,
        "source_manifestations": {
            "statistics": {
                "url": stats_url,
                "sha256": _sha256(stats_raw),
                "byte_count": len(stats_raw),
                "content_semantics": "official cumulative Puerto Rico area statistics",
            },
            "geometry": {
                "url": geo_url,
                "sha256": _sha256(geo_raw),
                "byte_count": len(geo_raw),
                "content_semantics": "official date-specific USDM vector GeoJSON",
                "pr_selection_bounds": list(PR_BOUNDS),
                "selection_method": "multipart component selection only; no interpolation or clipping",
                "retained_feature_counts": counts,
            },
        },
        "limitations": [
            "USDM is a weekly broad-scale analysis, not a real-time sensor feed.",
            "Local conditions can vary within a drought polygon.",
            "D0-D4 percentages are cumulative and must not be summed as exclusive bins.",
        ],
    }


def write_document(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--src-geo", type=Path)
    parser.add_argument("--src-stats", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--weeks", type=int, default=12)
    args = parser.parse_args()

    retrieved_at = _utc_now()
    if args.src_stats:
        stats_raw = _read_bytes(args.src_stats)
        stats_url = args.src_stats.resolve().as_uri()
    else:
        stats_raw, stats_url = fetch_stats(args.today, weeks=args.weeks)

    history = parse_stats(stats_raw)
    if not history:
        raise SystemExit("USDM statistics returned no usable Puerto Rico rows")
    map_date = history[-1]["map_date"]

    if args.src_geo:
        geo_raw = _read_bytes(args.src_geo)
        # Keep the date token in the synthetic URL so build_document applies the
        # exact same map-date binding gate to offline fixtures.
        geo_url = f"{args.src_geo.resolve().as_uri()}?map_date={_mapdate_token(map_date)}"
    else:
        geo_raw, geo_url = fetch_geo(map_date)

    document = build_document(
        stats_raw=stats_raw,
        stats_url=stats_url,
        geo_raw=geo_raw,
        geo_url=geo_url,
        retrieved_at=retrieved_at,
    )
    write_document(document, args.out)
    print(json.dumps({
        "map_date": document["map_date"],
        "features": len(document["footprint"]["features"]),
        "statistics_sha256": document["source_manifestations"]["statistics"]["sha256"],
        "geometry_sha256": document["source_manifestations"]["geometry"]["sha256"],
        "out": str(args.out),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
