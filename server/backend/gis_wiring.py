"""AguaYLuz wiring for the GIS viewer API.

Mounts the producer-agnostic ``/gis/*`` router (``server/backend/gis_api.py``,
mirrored from spiderweb-pr) with this producer's catalog and feature loaders, and
adds the AguaYLuz-specific routes:

* ``GET  /gis/layers/{layer_id}.geojson``             -- any catalog layer as GeoJSON
* ``GET  /gis/trace``                                 -- upstream/downstream dependents
* ``POST /gis/scenario``                              -- out-of-service scenario (HYPOTHESIS)
* ``GET  /gis/features/{layer_id}/{feature_id}/history``   -- alert timeline / gauge snapshot
* ``GET  /gis/features/{layer_id}/{feature_id}/documents`` -- source refs / JP flood documents

Features come from the same in-memory corpora and endpoint functions the rest of
the API serves (``server/backend/main.py``, ``hydromet_api.py``), so the map, the
GIS API and the existing endpoints never disagree. See docs/GIS_VIEWER_API.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from aguayluz import gis_network as net
from aguayluz import gis_query as gq
from aguayluz.gis_catalog import build_gis_catalog
from server.backend import hydromet_api
from server.backend import main as legacy
from server.backend.gis_api import build_gis_router

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "config" / "gis_layer_catalog.yaml"
PRODUCER_REPO = "aguayluz-pr"
ASSET_LAYERS = {"power_assets": "power", "water_assets": "water", "wastewater_assets": "wastewater"}


def _response_json(response: Any) -> dict[str, Any]:
    return json.loads(bytes(response.body).decode("utf-8"))


@lru_cache(maxsize=1)
def _catalog_config() -> dict[str, Any]:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8")) or {}


def _asset_features(asset_type: str) -> list[dict[str, Any]]:
    features = _response_json(legacy.assets_geojson())["features"]
    out = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("asset_type") != asset_type:
            continue
        patch = legacy._asset_patches.get(str(props.get("asset_id")))
        out.append({**feature, "properties": {**props, **patch}} if patch else feature)
    return out


def _asset_index() -> dict[str, dict[str, Any]]:
    return {str(a["asset_id"]): a for a in legacy._assets if a.get("asset_id")}


def _network() -> tuple[list[net.NetworkEdge], int]:
    return net.edges_from_rows(legacy._alert_edges)


def _dependency_features() -> list[dict[str, Any]]:
    assets = _asset_index()
    edges, _excluded = _network()
    features = []
    for edge in edges:
        a, b = assets.get(edge.from_id), assets.get(edge.to_id)
        if not a or not b:
            continue
        coords = [(a.get("lon"), a.get("lat")), (b.get("lon"), b.get("lat"))]
        if not all(isinstance(v, (int, float)) for pair in coords for v in pair):
            continue
        features.append(
            {
                "type": "Feature",
                "id": edge.edge_id,
                "geometry": {"type": "LineString", "coordinates": [list(pair) for pair in coords]},
                "properties": {
                    "edge_id": edge.edge_id,
                    "dependency_type": edge.relation,
                    "confidence": edge.confidence,
                    "evidence_required": edge.evidence_required,
                    "from_id": edge.from_id,
                    "to_id": edge.to_id,
                    "from_name": a.get("asset_name"),
                    "to_name": b.get("asset_name"),
                    "notes": edge.notes,
                },
            }
        )
    return features


LOADERS: dict[str, Callable[[], list[dict[str, Any]]]] = {
    **{layer_id: (lambda t=asset_type: _asset_features(t)) for layer_id, asset_type in ASSET_LAYERS.items()},
    "asset_dependencies": _dependency_features,
    "alerts": lambda: _response_json(legacy.alerts_geojson(critical_only=False))["features"],
    "river_gauges": lambda: _response_json(hydromet_api.hydromet_gauges_geojson())["features"],
    "municipios": lambda: list(legacy._municipios_geojson.get("features") or []),
    "barrios": lambda: list(legacy._barrios_geojson.get("features") or []),
}


def _data_available(layer_id: str) -> bool:
    return layer_id in LOADERS


def gis_catalog() -> dict[str, Any]:
    return build_gis_catalog(_catalog_config(), data_available=_data_available)


async def feature_loader(layer_id: str) -> tuple[list[dict], dict]:
    loader = LOADERS.get(layer_id)
    if loader is None:
        return [], {"exists": False}
    return loader(), {"exists": True}


def _containing(features: list[dict[str, Any]], lon: float, lat: float) -> dict[str, Any] | None:
    point = (float(lon), float(lat))
    for feature in features:
        parts = gq.feature_parts(feature)
        if parts is None or not parts.polygons:
            continue
        if any(gq.point_in_polygon(point, rings) for rings in parts.polygons):
            props = feature.get("properties") or {}
            return {"name": props.get("name"), "id": None if props.get("geoid") is None else str(props["geoid"])}
    return None


async def location_context(lon: float, lat: float, loader: Any) -> dict[str, Any]:
    municipios, _ = await loader("municipios")
    barrios, _ = await loader("barrios")
    return {"municipio": _containing(municipios, lon, lat), "barrio": _containing(barrios, lon, lat)}


def _layer_of(node_id: str) -> str | None:
    asset = _asset_index().get(node_id)
    if asset is None:
        return None
    return next((lid for lid, t in ASSET_LAYERS.items() if t == asset.get("asset_type")), None)


@lru_cache(maxsize=1)
def _municipio_parts() -> tuple[tuple[Any, tuple[float, float, float, float], str, str], ...]:
    out = []
    for feature in legacy._municipios_geojson.get("features") or []:
        parts = gq.feature_parts(feature)
        props = feature.get("properties") or {}
        if parts is None or not parts.polygons or props.get("geoid") is None:
            continue
        out.append((parts, parts.envelope(), str(props["geoid"]), str(props.get("name") or "")))
    return tuple(out)


def _municipio_at(lon: float, lat: float) -> tuple[str, str] | None:
    for parts, (w, s, e, n), geoid, name in _municipio_parts():
        if not (w <= lon <= e and s <= lat <= n):
            continue
        if any(gq.point_in_polygon((lon, lat), rings) for rings in parts.polygons):
            return geoid, name
    return None


def _areas_of(node_id: str) -> list[tuple[str, str, str | None]]:
    """Municipio of a node: its recorded municipality when that names a real
    municipio, otherwise the municipio containing its coordinates. Most assets
    record ``municipality`` as "unknown" or the island-level "Puerto Rico"."""
    asset = _asset_index().get(node_id) or {}
    name = asset.get("municipality")
    geoid = legacy._MUNICIPIO_GEOID_BY_NAME.get(name) if isinstance(name, str) else None
    if geoid:
        return [("municipio", str(geoid), name)]
    lon, lat = asset.get("lon"), asset.get("lat")
    if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
        hit = _municipio_at(float(lon), float(lat))
        if hit:
            return [("municipio", hit[0], hit[1])]
    return []


class ScenarioFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer_id: str
    feature_id: str


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected: list[ScenarioFeature] = Field(min_length=1, max_length=50)
    max_hops: int = Field(default=net.DEFAULT_MAX_HOPS, ge=1, le=100)


domain_router = APIRouter(prefix="/gis", tags=["gis"])


@domain_router.get("/layers/{layer_id}.geojson")
async def gis_layer_geojson(layer_id: str) -> JSONResponse:
    if layer_id not in {layer["layer_id"] for layer in gis_catalog()["layers"]}:
        raise HTTPException(404, f"unknown layer {layer_id!r}")
    features, _manifest = await feature_loader(layer_id)
    return JSONResponse({"type": "FeatureCollection", "features": features}, media_type="application/geo+json")


@domain_router.get("/trace")
def gis_trace(
    feature_id: str = Query(..., min_length=1, max_length=200),
    direction: str = Query("downstream", pattern="^(downstream|upstream)$"),
    max_hops: int = Query(net.DEFAULT_MAX_HOPS, ge=1, le=100),
) -> dict[str, Any]:
    """Recorded dependency links from a feature, with per-hop link evidence."""
    edges, excluded = _network()
    hits = net.trace(feature_id, edges, direction=direction, max_hops=max_hops)
    unverified = any(hit.evidence_required for hit in hits)
    return {
        "producer_repo": PRODUCER_REPO,
        "start": {"layer_id": _layer_of(feature_id), "feature_id": feature_id},
        "direction": direction,
        "max_hops": max_hops,
        "hits": [{**hit.as_dict(), "layer_id": _layer_of(hit.feature_id)} for hit in hits],
        "unverified_links_used": unverified,
        "links_excluded_missing_endpoint": excluded,
        "notes": [net.PROXY_NOTE] if unverified else [],
        "evidence_state": "COMPUTED",
    }


@domain_router.post("/scenario")
def gis_scenario(req: ScenarioRequest) -> dict[str, Any]:
    """gis-scenario-result/1.0: what loses service if the selected features fail."""
    edges, _excluded = _network()
    result = net.scenario_out_of_service(
        [(item.layer_id, item.feature_id) for item in req.selected],
        edges,
        layer_of=_layer_of,
        areas_of=_areas_of,
        max_hops=req.max_hops,
    )
    result["notes"].append(
        "Affected municipios use the asset's recorded municipality when it names a municipio, "
        "otherwise the municipio containing the asset's coordinates (point-in-polygon)."
    )
    return result


def _alert_timeline(asset_id: str) -> list[dict[str, Any]]:
    rows = [
        a
        for a in legacy._alerts
        if a.get("asset_id") == asset_id or asset_id in (a.get("linked_asset_ids") or [])
    ]
    rows.sort(key=lambda a: str(a.get("start_at") or a.get("published_at") or ""), reverse=True)
    keep = ("alert_id", "event_type", "severity", "status", "start_at", "end_at", "published_at", "source_title")
    return [{k: a.get(k) for k in keep} for a in rows]


@domain_router.get("/features/{layer_id}/{feature_id}/history")
async def gis_feature_history(layer_id: str, feature_id: str) -> dict[str, Any]:
    if layer_id in ASSET_LAYERS:
        return {"layer_id": layer_id, "feature_id": feature_id, "kind": "alert_timeline", "items": _alert_timeline(feature_id)}
    if layer_id == "river_gauges":
        features, _ = await feature_loader("river_gauges")
        match = next((f for f in features if (f.get("properties") or {}).get("lid") == feature_id), None)
        return {
            "layer_id": layer_id,
            "feature_id": feature_id,
            "kind": "latest_observation_snapshot",
            "items": [match["properties"]] if match else [],
            "note": "data/nwps_gauge_state.jsonl keeps the latest observation per gauge, not a stored series.",
        }
    raise HTTPException(404, f"layer {layer_id!r} has no history source")


@domain_router.get("/features/{layer_id}/{feature_id}/documents")
def gis_feature_documents(layer_id: str, feature_id: str) -> dict[str, Any]:
    if layer_id in ASSET_LAYERS:
        asset = _asset_index().get(feature_id)
        if asset is None:
            raise HTTPException(404, "asset not found")
        refs = asset.get("source_ref")
        refs = refs if isinstance(refs, list) else [refs] if refs else []
        return {"layer_id": layer_id, "feature_id": feature_id, "documents": [{"kind": "source_ref", "value": r} for r in refs]}
    if layer_id == "municipios":
        name = next(
            (
                (f.get("properties") or {}).get("name")
                for f in legacy._municipios_geojson.get("features") or []
                if str((f.get("properties") or {}).get("geoid")) == feature_id
                or (f.get("properties") or {}).get("name") == feature_id
            ),
            None,
        )
        if name is None:
            raise HTTPException(404, "municipio not found")
        from server.backend import app as served_app  # imported lazily: app.py includes this router

        binding = served_app._jp_flood_document_for_municipio(name)
        documents = []
        if binding:
            documents.append(
                {"kind": "jp_flood_document", "url": f"/municipios/{name}/flood-document/file", "binding": binding}
            )
        return {"layer_id": layer_id, "feature_id": feature_id, "name": name, "documents": documents}
    raise HTTPException(404, f"layer {layer_id!r} has no document source")


core_router = build_gis_router(
    producer_repo=PRODUCER_REPO,
    catalog_provider=gis_catalog,
    feature_loader=feature_loader,
    location_context=location_context,
)
