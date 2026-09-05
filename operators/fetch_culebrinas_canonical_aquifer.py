#!/usr/bin/env python3
"""Fetch and freeze the canonical SIGE aquifer feature for the Culebrinas frontier.

The operator is intentionally fail-closed. It never promotes a feature by proximity alone:
- source service/layer identity is fixed,
- spatial query anchor is fixed to an existing authoritative USGS control,
- exactly one intersecting SIGE feature must be returned,
- GlobalID must be present,
- geometry must be returned,
- the canonicalized feature and receipt are SHA-256 bound.

Network access is required only for acquisition. `freeze_response` is pure and unit-testable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCE_SERVICE = "https://sige.pr.gov/server/rest/services/MIPR/Geologia_v10_N/FeatureServer"
LAYER_ID = 2
LAYER_NAME = "Acuífero"
SOURCE_ITEM_ID = "294d280fa3094e4e8d3cffa339fd33b7"
SOURCE_NATIVE_EPSG = 32161
ANCHOR = {
    "id": "USGS-50148890",
    "name": "Rio Culebrinas at Margarita Damsite NR Aguada, PR",
    "longitude": -67.1512,
    "latitude": 18.394503,
    "crs": "EPSG:4326",
}


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def query_url() -> str:
    params = {
        "f": "json",
        "geometry": f'{ANCHOR["longitude"]},{ANCHOR["latitude"]}',
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "OBJECTID,DESCRIPCIO,GlobalID",
        "returnGeometry": "true",
        "outSR": "4326",
        "returnTrueCurves": "false",
    }
    return f"{SOURCE_SERVICE}/{LAYER_ID}/query?{urlencode(params)}"


def acquire(timeout_seconds: float = 30.0) -> dict[str, Any]:
    req = Request(query_url(), headers={"User-Agent": "aguayluz-culebrinas-canonical-freeze/1.0"})
    with urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - fixed authoritative URL
        payload = response.read()
    parsed = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("sige_response_not_object")
    return parsed


def freeze_response(response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if response.get("error"):
        raise ValueError(f'sige_error:{response["error"]}')
    features = response.get("features")
    if not isinstance(features, list):
        raise ValueError("sige_features_missing")
    if len(features) != 1:
        raise ValueError(f"sige_feature_cardinality:{len(features)}")
    feature = features[0]
    if not isinstance(feature, dict):
        raise ValueError("sige_feature_not_object")
    attributes = feature.get("attributes")
    geometry = feature.get("geometry")
    if not isinstance(attributes, dict):
        raise ValueError("sige_attributes_missing")
    if not isinstance(geometry, dict) or not geometry:
        raise ValueError("sige_geometry_missing")
    global_id = attributes.get("GlobalID")
    if not isinstance(global_id, str) or not global_id.strip():
        raise ValueError("sige_globalid_missing")
    object_id = attributes.get("OBJECTID")
    description = attributes.get("DESCRIPCIO")

    frozen = {
        "type": "Feature",
        "properties": {
            "source_authority": "Puerto Rico SIGE / PRPB",
            "source_service": SOURCE_SERVICE,
            "source_layer_id": LAYER_ID,
            "source_layer_name": LAYER_NAME,
            "source_item_id": SOURCE_ITEM_ID,
            "source_native_epsg": SOURCE_NATIVE_EPSG,
            "source_objectid": object_id,
            "source_globalid": global_id,
            "description": description,
            "binding_method": "authoritative_feature_intersects_authoritative_USGS_control",
            "anchor_id": ANCHOR["id"],
            "identity_state": "PASS_STABLE_GLOBALID",
        },
        "geometry": geometry,
    }
    frozen_hash = _sha256_bytes(_canonical_bytes(frozen))
    receipt = {
        "schema_version": "aguayluz.culebrinas-canonical-aquifer-freeze/v1.0",
        "state": "FROZEN",
        "source_service": SOURCE_SERVICE,
        "source_layer_id": LAYER_ID,
        "source_item_id": SOURCE_ITEM_ID,
        "source_native_epsg": SOURCE_NATIVE_EPSG,
        "query_output_epsg": 4326,
        "anchor": ANCHOR,
        "feature_count": 1,
        "global_id": global_id,
        "object_id": object_id,
        "feature_sha256": frozen_hash,
        "proximity_identity_used": False,
        "canonical_geometry_bound": True,
    }
    return frozen, receipt


def write_freeze(response: dict[str, Any], out_geojson: Path, out_receipt: Path) -> dict[str, Any]:
    feature, receipt = freeze_response(response)
    out_geojson.parent.mkdir(parents=True, exist_ok=True)
    out_receipt.parent.mkdir(parents=True, exist_ok=True)
    out_geojson.write_text(json.dumps(feature, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--response-json", type=Path, help="Use a previously captured SIGE JSON response instead of live acquisition")
    parser.add_argument("--out-geojson", type=Path, default=Path("data/culebrinas/frontier/v2/canonical_aquifer_feature.geojson"))
    parser.add_argument("--out-receipt", type=Path, default=Path("data/culebrinas/frontier/v2/canonical_aquifer_freeze_receipt.json"))
    args = parser.parse_args()
    if args.response_json:
        response = json.loads(args.response_json.read_text(encoding="utf-8"))
    else:
        response = acquire()
    receipt = write_freeze(response, args.out_geojson, args.out_receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
