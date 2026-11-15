"""Read-only API for the Puerto Rico hydrologic feature inventory.

Serves the committed inventory written by ``scripts/build_hydro_inventory.py``: aquifers and
wells reconciled across USGS, the Water Quality Portal, EPA SDWIS and DRNA, with every
source claim kept, candidate matches listed rather than merged, and source disagreements
shown. Each well's monitoring state is computed per request from whatever reading files
the server holds; a server without them says so instead of reporting "no data".

Stdlib + FastAPI only (the GUI-parity CI job boots this backend without the geospatial
stack). No write path: the ingests are run by a maintainer, never from the page.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from aguayluz import DATA_DIR as _DEFAULT_DATA_DIR
from aguayluz import hydro_inventory as hi

router = APIRouter(tags=["hydro-inventory"])

#: Resolved per request so tests (and AGUAYLUZ_DATA_HOME) can redirect it.
DATA_DIR: Path = _DEFAULT_DATA_DIR
_STORE = hi.InventoryStore()
_CLAIMS: dict[str, Any] = {"key": None, "by_id": {}}

SCOPE_STATEMENT = (
    "Every aquifer, well, spring, stream reach, watercourse, waterbody, reservoir, intake, gauge and watershed that the enumerated public sources describe for Puerto Rico, Vieques, Culebra and "
    "Mona, reconciled across sources. Claims are merged only when a source publishes another source's "
    "identifier; name or distance matches are listed as candidates, so counts are a range. Source "
    "disagreements are shown, not resolved. This inventory makes no claim of completeness beyond its sources."
)
ROW_FIELDS = ("feature_id", "feature_type", "display_name", "sources", "lat", "lon", "site_no", "site_type_code",
              "aquifer_code", "national_aquifer_code", "municipio", "island", "area_km2", "municipios",
              "authority", "aq_code", "system", "member_wells", "located", "well_depth_ft", "activity",
              "name_is_source_class_only", "utility_asset_ids", "member_springs", "flow_type", "lengthkm",
              "huc8", "huc10", "gnis_id", "reaches", "water_type", "areasqkm", "nhd_polygons", "nws_lid", "level",
              "huc", "gnis_class")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _data() -> dict[str, Any]:
    return _STORE.load(DATA_DIR)


def _claims() -> dict[str, dict[str, Any]]:
    hydro = DATA_DIR / hi.HYDRO_DIR
    paths = sorted(hydro.glob("claims_*.jsonl"))
    key = tuple((str(p), p.stat().st_mtime_ns) for p in paths)
    if key != _CLAIMS["key"]:
        by_id: dict[str, dict[str, Any]] = {}
        for p in paths:
            for c in hi.read_claims(p):
                by_id[c["claim_id"]] = c
        _CLAIMS.update(key=key, by_id=by_id)
    return _CLAIMS["by_id"]


def _row(feature: dict[str, Any], last_obs: dict[str, str] | None) -> dict[str, Any]:
    row = {k: feature.get(k) for k in ROW_FIELDS if feature.get(k) is not None}
    if feature["feature_type"] == "well":
        row["monitoring"] = hi.monitoring_state(feature, last_obs, _now().date())
    return row


@router.get("/hydro/inventory/summary")
def hydro_summary() -> JSONResponse:
    data = _data()
    receipt = data["receipt"]
    last_obs = _STORE.last_observations(DATA_DIR)
    states: dict[str, int] = {}
    for f in data["features"]:
        if f["feature_type"] == "well":
            s = hi.monitoring_state(f, last_obs, _now().date())["state"]
            states[s] = states.get(s, 0) + 1
    sources: dict[str, dict[str, Any]] = {}
    for m in (receipt or {}).get("manifestations", []):
        entry = sources.setdefault(m["source_key"], {"source_key": m["source_key"], "url": m["url"], "pages": 0,
                                                     "first_sha256": m["byte_sha256"], "pin_matches": m.get("pin_matches")})
        entry["pages"] += 1
    return JSONResponse({
        "scope": {"statement": SCOPE_STATEMENT, "completeness_claimed": False, "alerting": "not_applicable",
                  "monitored_now_days": hi.MONITORED_NOW_DAYS, "proximity_m": hi.WELL_PROXIMITY_M},
        "generated_at": (receipt or {}).get("generated_at"),
        "phase_scope": (receipt or {}).get("phase_scope"),
        "coverage": (receipt or {}).get("coverage"),
        "source_ledgers": (receipt or {}).get("source_ledgers"),
        "spatial": (receipt or {}).get("spatial"),
        "open_residue": (receipt or {}).get("open_residue", []),
        "datum": ((receipt or {}).get("stage_receipts", {}).get("aquifers") or {}).get("datum"),
        "monitoring": {"readings_present": last_obs is not None, "wells_by_state": states},
        "conflicts": len(data["conflicts"]),
        "sources": sorted(sources.values(), key=lambda s: s["source_key"]),
        "related": {"aquifer_bands": "/aquifer-bands", "water_use": "/water-use", "monitoring": "/monitoring"},
    })


@router.get("/hydro/features")
def hydro_features(
    type: str | None = Query(None, alias="type"),  # noqa: A002 - the public query name
    aquifer: str | None = None,
    include_polygon: bool = False,
    state: str | None = None,
    q: str | None = None,
    source: str | None = None,
    limit: int = Query(200, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    data = _data()
    if type and type not in hi.FEATURE_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {', '.join(hi.FEATURE_TYPES)}")
    items = data["features"]
    if type:
        items = [f for f in items if f["feature_type"] == type]
    if aquifer:
        if aquifer not in data["by_id"]:
            raise HTTPException(status_code=404, detail=f"unknown aquifer {aquifer}")
        members = set(hi.wells_in_aquifer(data, aquifer, include_polygon))
        items = [f for f in items if f["feature_id"] in members]
    if source:
        items = [f for f in items if source in f["sources"]]
    if q:
        needle = hi.normalize_name(q)
        items = [f for f in items if needle in hi.normalize_name(f.get("display_name"))
                 or needle in hi.normalize_name(f["feature_id"])]
    last_obs = _STORE.last_observations(DATA_DIR)
    rows = [_row(f, last_obs) for f in items]
    if state:
        if state not in hi.MONITORING_STATES:
            raise HTTPException(status_code=422, detail=f"state must be one of {', '.join(hi.MONITORING_STATES)}")
        rows = [r for r in rows if (r.get("monitoring") or {}).get("state") == state]
    return JSONResponse({"total": len(rows), "offset": offset, "limit": limit, "items": rows[offset:offset + limit]})


@router.get("/hydro/aquifer-wells")
def hydro_aquifer_wells(aquifer: str, include_polygon: bool = False) -> JSONResponse:
    """USGS site numbers of the wells in one aquifer, for filtering monitoring series."""
    data = _data()
    if aquifer not in data["by_id"]:
        raise HTTPException(status_code=404, detail=f"unknown aquifer {aquifer}")
    members = hi.wells_in_aquifer(data, aquifer, include_polygon)
    authoritative = set(hi.wells_in_aquifer(data, aquifer, False))
    sites = sorted({data["by_id"][m].get("site_no") for m in members if data["by_id"][m].get("site_no")})
    return JSONResponse({"aquifer": aquifer, "include_polygon": include_polygon, "site_nos": sites,
                         "wells": len(members), "authoritative": len(authoritative),
                         "polygon_only": len(set(members) - authoritative)})


@router.get("/hydro/aquifer-series")
def hydro_aquifer_series(aquifer: str, include_polygon: bool = False) -> JSONResponse:
    """Median per-well monthly depth anomaly for one aquifer, from the reading files on this server."""
    data = _data()
    feature = data["by_id"].get(aquifer)
    if feature is None or feature["feature_type"] != "aquifer":
        raise HTTPException(status_code=404, detail=f"unknown aquifer {aquifer}")
    members, excluded = hi.series_members(data, aquifer, include_polygon)
    readings_present = _STORE.last_observations(DATA_DIR) is not None
    monthly, skipped = hi.monthly_by_well(hi.iter_groundwater_rows(DATA_DIR) if readings_present else [], set(members))
    series = hi.aquifer_series(monthly, members)
    return JSONResponse({"aquifer": aquifer, "aquifer_name": feature.get("display_name"), "include_polygon": include_polygon,
                         "readings_present": readings_present, "excluded_wells": excluded, "skipped_rows": skipped,
                         **series})


@router.get("/hydro/features/{feature_id:path}")
def hydro_feature(feature_id: str) -> JSONResponse:
    data = _data()
    feature = data["by_id"].get(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"unknown feature {feature_id}")
    claims = _claims()
    links = data["links_by_feature"].get(feature_id, [])
    wells = [lk for lk in links if lk["link_type"] == "WELL_IN_AQUIFER" and lk["to"] == feature_id]
    springs = [lk for lk in links if lk["link_type"] == "SPRING_IN_AQUIFER" and lk["to"] == feature_id]
    return JSONResponse({
        "feature": {**feature, **({"monitoring": hi.monitoring_state(feature, _STORE.last_observations(DATA_DIR), _now().date())}
                                  if feature["feature_type"] == "well" else {})},
        "claims": [claims[c] for c in feature["claim_ids"] if c in claims],
        "links": [lk for lk in links if not (lk["link_type"] in ("WELL_IN_AQUIFER", "SPRING_IN_AQUIFER")
                                             and lk["to"] == feature_id)],
        "member_wells": {"authoritative": sum(1 for lk in wells if lk["edge_class"] == "AUTHORITATIVE"),
                         "polygon_only": sum(1 for lk in wells if lk["edge_class"] == "DERIVED_TOPOLOGICAL")},
        "member_springs": len(springs),
        "conflicts": [c for c in data["conflicts"] if feature_id in c["feature_ids"]],
    })


@router.get("/hydro/conflicts")
def hydro_conflicts(kind: str | None = None) -> JSONResponse:
    items = [c for c in _data()["conflicts"] if not kind or c["kind"] == kind]
    return JSONResponse({"total": len(items), "items": items})


@router.get("/hydro/candidates")
def hydro_candidates(type: str | None = Query(None, alias="type"), tier: str | None = None) -> JSONResponse:  # noqa: A002
    data = _data()
    items = [lk for lk in data["links"] if lk["link_type"] == "CANDIDATE_SAME_FEATURE"
             and (not tier or lk.get("identity_tier") == tier)
             and (not type or data["by_id"].get(lk["from"], {}).get("feature_type") == type)]
    named = [{**lk, "from_name": data["by_id"][lk["from"]].get("display_name"),
              "to_name": data["by_id"][lk["to"]].get("display_name")} for lk in items]
    return JSONResponse({"total": len(named), "items": named})


_GEO_FILES = {"waterbodies": "pr_waterbodies.geojson", "watersheds": "pr_watersheds.geojson"}
_POINT_TYPES = ("well", "spring", "gauge", "reservoir", "waterfall")


@router.get("/hydro/geo/{name}.geojson")
def hydro_geo(name: str) -> Response:
    """Committed surface-water geometry: ``waterbodies``, ``watersheds`` or ``streams-<HUC8>``."""
    if name.startswith("streams-") and name[8:].isdigit():
        path = DATA_DIR / "geo" / "streams" / f"{name[8:]}.geojson"
    elif name in _GEO_FILES:
        path = DATA_DIR / "geo" / _GEO_FILES[name]
    else:
        raise HTTPException(status_code=404, detail=f"unknown geometry {name}")
    if not path.is_file():
        return JSONResponse({"type": "FeatureCollection", "features": []})
    return Response(content=path.read_bytes(), media_type="application/geo+json")


@router.get("/hydro/stream-tiles")
def hydro_stream_tiles() -> JSONResponse:
    folder = DATA_DIR / "geo" / "streams"
    tiles = sorted(p.stem for p in folder.glob("*.geojson")) if folder.is_dir() else []
    return JSONResponse({"tiles": tiles})


@router.get("/hydro/points.geojson")
def hydro_points(type: str = Query(..., alias="type")) -> JSONResponse:  # noqa: A002
    """Placed features of one point type, with monitoring state for wells. Unplaced features are never drawn."""
    if type not in _POINT_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {', '.join(_POINT_TYPES)}")
    data = _data()
    last_obs = _STORE.last_observations(DATA_DIR) if type == "well" else None
    today = _now().date()
    features = []
    for f in data["features"]:
        if f["feature_type"] != type or f.get("lat") is None:
            continue
        props = {"id": f["feature_id"], "name": f.get("display_name"), "sources": len(f["sources"])}
        if type == "well":
            props["state"] = hi.monitoring_state(f, last_obs, today)["state"]
            props["coded"] = bool(f.get("aquifer_code"))
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": "Point", "coordinates": [f["lon"], f["lat"]]}})
    return JSONResponse({"type": "FeatureCollection", "features": features})


@router.get("/hydro/aquifers.geojson")
def hydro_aquifers_geojson() -> Response:
    path = DATA_DIR / "geo" / hi.AQUIFER_GEOJSON
    if not path.is_file():
        return JSONResponse({"type": "FeatureCollection", "features": []})
    return Response(content=path.read_bytes(), media_type="application/geo+json")


