"""Typed wrappers for the 8 modern WATERS API paths.

Defaults to the highest API version where multiple exist (v3 delineation,
v4 upstream/downstream). Each function builds the `p`-prefixed query string
exactly as the OAS declares (see https://api.epa.gov/waters/oas30) and returns
the parsed response dict — top-level keys differ per endpoint, so each helper
documents the expected envelope.

Response envelopes (locked from the OAS components):
  - point_indexing → `{"output": {"feature_id", "ary_flowlines": [...], ...}}`
  - upstream_downstream_v4 → `{"network_flowlines": {GeoJSON FC}, "catchments": ...}`
  - drainage_area_delineation_v3 → `{"Result_Delineated_Area": {GeoJSON FC}}`
  - gnis_name_lookup → list of GNIS feature dicts (no envelope)
  - event_indexing → `{"output": {...}}`
  - owld_locator → `{"output": {...}}`

Out-of-scope endpoints (exist on the gateway but not wrapped here): v2/navigation*,
v2/watershedsp, v2_5/nhdplus_*, v2/random*, v1/visualization.
"""

from __future__ import annotations

from typing import Any

from .client import WatersClient


def _point_wkt(lon: float, lat: float) -> str:
    """Return WATERS-style WKT POINT, lon then lat."""
    return f"POINT({lon} {lat})"


# ---------------------------------------------------------------------------
# /v1/pointindexing — snap a lat/lon to the nearest NHDPlus reach.
# ---------------------------------------------------------------------------

def point_indexing(
    client: WatersClient,
    *,
    lon: float,
    lat: float,
    method: str = "DISTANCE",
    max_distance_km: float = 5.0,
    raindrop_distance_km: float | None = None,
    fcode_allow: str | None = None,
    fcode_deny: str | None = None,
    return_path_geometry: bool = False,
    return_flowline_geometry: bool = False,
) -> dict[str, Any]:
    """Call /v1/pointindexing GET.

    Returns the raw envelope. To pull the canonical fields:
      out = resp["output"]
      flowline = out["ary_flowlines"][0]
      comid = flowline["comid"]
      reachcode = flowline["reachcode"]
      nhdplus_region = flowline["nhdplus_region"]  # VPU id; "21" for PR
    """
    params: dict[str, Any] = {
        "pgeometry": _point_wkt(lon, lat),
        "ppointindexingmethod": method,
        "ppointindexingmaxdist": max_distance_km,
        "poutputpathflag": "TRUE" if return_path_geometry else "FALSE",
        "preturnflowlinegeomflag": "TRUE" if return_flowline_geometry else "FALSE",
    }
    if raindrop_distance_km is not None:
        params["ppointindexingraindropdist"] = raindrop_distance_km
    if fcode_allow is not None:
        params["ppointindexingfcodeallow"] = fcode_allow
    if fcode_deny is not None:
        params["ppointindexingfcodedeny"] = fcode_deny
    return client.get("/v1/pointindexing", params=params)


# ---------------------------------------------------------------------------
# /v4/upstreamdownstream — trace flow upstream or downstream from a COMID.
# ---------------------------------------------------------------------------

def upstream_downstream(
    client: WatersClient,
    *,
    comid: int,
    distance_km: float,
    direction: str = "DD",   # DD=downstream main, UM=upstream main, UT=upstream tributaries, DM=downstream tributaries
    network_distance_km: float | None = None,
    return_catchments: bool = False,
    return_flowlines: bool = True,
) -> dict[str, Any]:
    """Call /v4/upstreamdownstream GET.

    Returns `{network_flowlines, catchments}` GeoJSON-style envelope.
    `direction` codes:
      - DD: downstream main stem
      - DM: downstream main + tributaries
      - UM: upstream main stem
      - UT: upstream main + tributaries
    """
    params: dict[str, Any] = {
        "pnavigationid": direction,
        "pstartcomid": comid,
        "pmaxdistancekm": distance_km,
        "preturnflowlines": "TRUE" if return_flowlines else "FALSE",
        "preturncatchments": "TRUE" if return_catchments else "FALSE",
    }
    if network_distance_km is not None:
        params["pmaxnetworkdistancekm"] = network_distance_km
    return client.get("/v4/upstreamdownstream", params=params)


# ---------------------------------------------------------------------------
# /v3/drainageareadelineation — delineate the upstream watershed of a point.
# ---------------------------------------------------------------------------

def drainage_area_delineation(
    client: WatersClient,
    *,
    lon: float,
    lat: float,
    max_distance_km: float = 50.0,
    aggregate_flag: bool = True,
    snap_distance_km: float = 5.0,
) -> dict[str, Any]:
    """Call /v3/drainageareadelineation GET.

    Returns `{"Result_Delineated_Area": {GeoJSON FeatureCollection}}`.
    Each feature's `properties` includes NHDPlusID and AreaSqKm.
    """
    params: dict[str, Any] = {
        "pgeometry": _point_wkt(lon, lat),
        "pmaxdistancekm": max_distance_km,
        "paggregateflag": "TRUE" if aggregate_flag else "FALSE",
        "psnapdistancekm": snap_distance_km,
    }
    return client.get("/v3/drainageareadelineation", params=params)


# ---------------------------------------------------------------------------
# /v1/gnisnamelookup — find GNIS-named features by free-text.
# ---------------------------------------------------------------------------

def gnis_name_lookup(
    client: WatersClient,
    *,
    name: str,
    state: str | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    """Call /v1/gnisnamelookup GET.

    `state` should be a two-letter code; pass "PR" to restrict to Puerto Rico.
    """
    params: dict[str, Any] = {
        "pgnisname": name,
        "pmaxresults": max_results,
    }
    if state is not None:
        params["pstate"] = state
    return client.get("/v1/gnisnamelookup", params=params)


# ---------------------------------------------------------------------------
# /v1/eventindexing — index a list of events (CSV/GeoJSON) onto NHDPlus.
# ---------------------------------------------------------------------------

def event_indexing(
    client: WatersClient,
    *,
    events_geojson: dict[str, Any],
    method: str = "DISTANCE",
    max_distance_km: float = 5.0,
) -> dict[str, Any]:
    """Call /v1/eventindexing POST (GeoJSON body required for batch indexing)."""
    params: dict[str, Any] = {
        "pindexingmethod": method,
        "pmaxdistancekm": max_distance_km,
    }
    return client.post("/v1/eventindexing", json_body=events_geojson, params=params)


# ---------------------------------------------------------------------------
# /v1/owldlocator — Oil & Water Loss Discovery — locate downstream waterbodies.
# ---------------------------------------------------------------------------

def owld_locator(
    client: WatersClient,
    *,
    lon: float,
    lat: float,
    max_distance_km: float = 50.0,
) -> dict[str, Any]:
    """Call /v1/owldlocator GET.

    Returns waterbodies downstream of a release point. Useful for service-event
    cascade analysis.
    """
    params: dict[str, Any] = {
        "pgeometry": _point_wkt(lon, lat),
        "pmaxdistancekm": max_distance_km,
    }
    return client.get("/v1/owldlocator", params=params)


# ---------------------------------------------------------------------------
# Convenience: extract canonical fields from a pointindexing response.
# ---------------------------------------------------------------------------

def first_flowline(point_indexing_response: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first flowline dict from a pointindexing response or None."""
    out = point_indexing_response.get("output", {})
    flowlines = out.get("ary_flowlines", [])
    return flowlines[0] if flowlines else None
