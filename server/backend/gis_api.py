"""GIS viewer API: /gis/catalog, /gis/identify, /gis/search, /gis/query, /gis/export.

Producer-agnostic router factory. The producer supplies three callables:

* ``catalog_provider()`` -> a gis-layer-catalog/1.0 document
  (schemas/gis_layer_catalog_v1.schema.json);
* ``feature_loader(layer_id)`` -> awaitable ``(features, manifest)`` where
  ``manifest["exists"]`` is False when the layer has no backing artifact on
  this deployment (an empty result, never an error);
* optionally ``location_context(lon, lat, loader)`` -> extra identify context
  (municipio membership, grid cell lookups, ...) and ``summary_builder``.

The same file is mirrored into the other PRII producers; keep it free of
producer-specific imports. Geometry lives in spiderweb/gis_query.py (mirrored
as ``<package>/gis_query.py``).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from aguayluz import gis_query as gq

FeatureLoader = Callable[[str], Awaitable[tuple[list[dict], dict]]]
CatalogProvider = Callable[[], Mapping[str, Any]]
LocationContext = Callable[[float, float, FeatureLoader], Awaitable[dict[str, Any]]]
SummaryBuilder = Callable[
    [list[dict[str, Any]], Mapping[str, Mapping[str, Any]]], dict[str, Any]
]

MAX_IDENTIFY_TOLERANCE_M = 5000.0


class GisQueryRequest(BaseModel):
    """Request body of POST /gis/query and POST /gis/export (gis-query/1.0)."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str | None = None
    geometry: dict[str, Any]
    layers: list[str] = Field(min_length=1)
    time_range: dict[str, str | None] | None = None
    tolerance_m: float = Field(
        default=gq.DEFAULT_TOLERANCE_M, gt=0, le=MAX_IDENTIFY_TOLERANCE_M
    )
    limit_per_layer: int = Field(default=500, ge=1, le=gq.MAX_LIMIT_PER_LAYER)


class GisExportRequest(GisQueryRequest):
    format: str = "geojson"


def default_summary(
    results: list[dict[str, Any]], catalog: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Matched counts per layer plus value counts of each layer's classification field."""
    summary: dict[str, Any] = {"matched_by_layer": {}, "classes": {}}
    for result in results:
        layer_id = result["layer_id"]
        summary["matched_by_layer"][layer_id] = result["matched_count"]
        classification = (catalog.get(layer_id) or {}).get("classification") or {}
        field = classification.get("field")
        if field and result["features"]:
            summary["classes"][layer_id] = gq.summarize(result["features"], [field])
    return summary


def _project_properties(
    props: Mapping[str, Any], fields: Sequence[str]
) -> dict[str, Any]:
    if not fields:
        return dict(props)
    return {field: props.get(field) for field in fields if field in props}


def _csv_list(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def build_gis_router(
    *,
    producer_repo: str,
    catalog_provider: CatalogProvider,
    feature_loader: FeatureLoader,
    location_context: LocationContext | None = None,
    summary_builder: SummaryBuilder = default_summary,
) -> APIRouter:
    router = APIRouter(prefix="/gis", tags=["gis"])

    def catalog_index() -> dict[str, Mapping[str, Any]]:
        return {
            layer["layer_id"]: layer for layer in catalog_provider().get("layers", [])
        }

    def require_layers(requested: Sequence[str]) -> dict[str, Mapping[str, Any]]:
        index = catalog_index()
        unknown = [layer_id for layer_id in requested if layer_id not in index]
        if unknown:
            raise HTTPException(400, f"unknown layer(s): {', '.join(unknown)}")
        return index

    async def run_query(
        req: GisQueryRequest,
    ) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
        index = require_layers(req.layers)
        try:
            area = gq.parse_geometry(req.geometry, tolerance_m=req.tolerance_m)
            time_range = gq.parse_time_range(req.time_range)
        except gq.GisQueryError as exc:
            raise HTTPException(422, str(exc)) from exc
        results: list[dict[str, Any]] = []
        for layer_id in req.layers:
            meta = index[layer_id]
            mode = "polygon" if area.mode == "polygon" else area.mode
            if meta.get("query_modes") and mode not in meta["query_modes"]:
                raise HTTPException(
                    422, f"layer {layer_id!r} does not support {mode} queries"
                )
            features, manifest = await feature_loader(layer_id)
            result = gq.query_layer(
                layer_id,
                features,
                area,
                temporal_field=meta.get("temporal_field"),
                time_range=time_range,
                limit=req.limit_per_layer,
            )
            if not manifest.get("exists", True):
                result["error"] = "no backing artifact on this deployment"
            results.append(result)
        response = {
            "contract_version": gq.CONTRACT_QUERY,
            "producer_repo": producer_repo,
            "geometry": req.geometry,
            "layers": results,
            "total_matched": sum(r["matched_count"] for r in results),
            "summary": summary_builder(results, index),
            "evidence_state": "COMPUTED",
        }
        if req.time_range:
            response["time_range"] = req.time_range
        return response, index

    @router.get("/catalog")
    async def gis_catalog():
        """gis-layer-catalog/1.0: every layer with its identify/search/query metadata."""
        return catalog_provider()

    @router.get("/identify")
    async def gis_identify(
        lon: float,
        lat: float,
        tol_m: float = Query(gq.DEFAULT_TOLERANCE_M, gt=0, le=MAX_IDENTIFY_TOLERANCE_M),
        layers: str | None = None,
        limit: int = Query(10, ge=1, le=100),
    ):
        """Features at a clicked point, nearest first, plus location context."""
        index = catalog_index()
        requested = _csv_list(layers) or [
            layer_id
            for layer_id, meta in index.items()
            if meta.get("data_available", True)
        ]
        index = require_layers(requested)
        hits: list[dict[str, Any]] = []
        try:
            for layer_id in requested:
                features, _manifest = await feature_loader(layer_id)
                for distance, feature in gq.identify(
                    features, lon, lat, tolerance_m=tol_m, limit=limit
                ):
                    meta = index[layer_id]
                    hits.append(
                        {
                            "layer_id": layer_id,
                            "feature_id": gq.feature_identifier(feature),
                            "distance_m": round(distance, 2),
                            "properties": _project_properties(
                                feature.get("properties") or {},
                                meta.get("identify_fields") or [],
                            ),
                            "anchor": gq.feature_anchor(feature),
                            "bbox": gq.feature_bbox(feature),
                        }
                    )
        except gq.GisQueryError as exc:
            raise HTTPException(422, str(exc)) from exc
        hits.sort(key=lambda hit: hit["distance_m"])
        context = (
            await location_context(lon, lat, feature_loader) if location_context else {}
        )
        return {
            "producer_repo": producer_repo,
            "point": {"lon": lon, "lat": lat},
            "tolerance_m": tol_m,
            "hits": hits[:limit],
            "location": context,
            "evidence_state": "COMPUTED",
        }

    @router.get("/search")
    async def gis_search(
        q: str = Query(..., min_length=1, max_length=200),
        layers: str | None = None,
        limit: int = Query(20, ge=1, le=200),
    ):
        """Ranked text search over each layer's search_fields, plus coordinate parsing."""
        index = catalog_index()
        requested = _csv_list(layers) or [
            layer_id for layer_id, meta in index.items() if meta.get("search_fields")
        ]
        index = require_layers(requested)
        hits: list[dict[str, Any]] = []
        coordinate = gq.parse_coordinate_text(q)
        if coordinate is not None:
            hits.append(
                {
                    "kind": "coordinate",
                    "layer_id": None,
                    "feature_id": None,
                    "label": f"{coordinate[1]:.6f}, {coordinate[0]:.6f}",
                    "field": None,
                    "rank": -1,
                    "anchor": list(coordinate),
                    "bbox": None,
                }
            )
        for layer_id in requested:
            fields = index[layer_id].get("search_fields") or []
            if not fields:
                continue
            features, _manifest = await feature_loader(layer_id)
            for match in gq.search_features(features, q, fields, limit=limit):
                feature = match["feature"]
                hits.append(
                    {
                        "kind": "feature",
                        "layer_id": layer_id,
                        "feature_id": gq.feature_identifier(feature),
                        "label": match["value"],
                        "field": match["field"],
                        "rank": match["rank"],
                        "anchor": gq.feature_anchor(feature),
                        "bbox": gq.feature_bbox(feature),
                    }
                )
        hits.sort(key=lambda hit: hit["rank"])
        return {"producer_repo": producer_repo, "query": q, "hits": hits[:limit]}

    @router.post("/query")
    async def gis_feature_query(req: GisQueryRequest):
        """gis-query/1.0: features of the requested layers inside the AOI."""
        response, _index = await run_query(req)
        return response

    @router.post("/export")
    async def gis_export(req: GisExportRequest):
        """Export an AOI selection as GeoJSON or CSV. PUBLIC layers only."""
        if req.format not in ("geojson", "csv"):
            raise HTTPException(422, "format must be 'geojson' or 'csv'")
        index = require_layers(req.layers)
        refused = [
            layer_id for layer_id in req.layers if not index[layer_id].get("exportable")
        ]
        if refused:
            raise HTTPException(
                403,
                f"layer(s) not exportable (access class is not PUBLIC): {', '.join(refused)}",
            )
        query = GisQueryRequest(**req.model_dump(exclude={"format"}))
        response, _index = await run_query(query)
        merged: list[dict[str, Any]] = []
        for result in response["layers"]:
            for feature in result["features"]:
                merged.append(
                    {
                        **feature,
                        "properties": {
                            "layer_id": result["layer_id"],
                            **(feature.get("properties") or {}),
                        },
                    }
                )
        meta = {
            "producer_repo": producer_repo,
            "geometry": req.geometry,
            "time_range": req.time_range,
            "layers": [
                {
                    k: r[k]
                    for k in (
                        "layer_id",
                        "matched_count",
                        "returned_count",
                        "excluded_count",
                        "truncated",
                    )
                }
                for r in response["layers"]
            ],
            "evidence_state": "COMPUTED",
        }
        if req.format == "csv":
            body = gq.features_to_csv(merged)
            return Response(
                content=body,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{producer_repo}-gis-export.csv"',
                    "X-Gis-Export-Meta": json.dumps(
                        meta["layers"], separators=(",", ":")
                    ),
                },
            )
        return JSONResponse(
            {"type": "FeatureCollection", "features": merged, "gis_export": meta},
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f'attachment; filename="{producer_repo}-gis-export.geojson"'
            },
        )

    return router
