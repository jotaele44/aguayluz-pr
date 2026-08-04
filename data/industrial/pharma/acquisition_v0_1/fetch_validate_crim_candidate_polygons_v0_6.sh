#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-crim_candidate_polygons_v0_6}"
BINDING_JSON="${2:-}"
mkdir -p "$OUT_DIR/raw"

SERVICE="https://sigejp.pr.gov/server/rest/services/crim/crim_feb_2025/MapServer/0/query"
OUT_FIELDS="OBJECTID,NUM_CATASTRO,OLDPID,GlobalID,TIPO,Shape.STArea(),Shape.STLength()"

fetch_one() {
  local objectid="$1"
  local outfile="$2"
  curl --fail --show-error --silent --location \
    --get "$SERVICE" \
    --data-urlencode "objectIds=$objectid" \
    --data-urlencode "outFields=$OUT_FIELDS" \
    --data-urlencode "returnGeometry=true" \
    --data-urlencode "returnZ=false" \
    --data-urlencode "outSR=4326" \
    --data-urlencode "f=geojson" \
    --output "$outfile"
}

fetch_one 1094625 "$OUT_DIR/raw/starlink_objectid_1094625.geojson"
fetch_one 1095803 "$OUT_DIR/raw/boehringer_objectid_1095803.geojson"

shasum -a 256 "$OUT_DIR"/raw/*.geojson > "$OUT_DIR/raw_sha256.txt"

python3 - "$OUT_DIR" "$BINDING_JSON" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from shapely.geometry import shape
    from shapely.validation import explain_validity
except Exception as exc:
    raise SystemExit(
        "BLOCKED_MISSING_SHAPELY: install shapely in the operator environment "
        "before topology and non-overlap validation. Raw GeoJSON was preserved."
    ) from exc

root = Path(sys.argv[1])
binding_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None

expected = {
    "starlink": {
        "file": root / "raw" / "starlink_objectid_1094625.geojson",
        "objectid": 1094625,
        "globalid": "{99DFF9A0-F44B-4153-AD48-D9771A8DC3F3}",
        "num_catastro": "055-044-631-04",
        "oldpid": "055-000-002-36",
        "service_area_m2": 166456.563266,
        "deed_area_m2": 165603.1968,
    },
    "boehringer": {
        "file": root / "raw" / "boehringer_objectid_1095803.geojson",
        "objectid": 1095803,
        "globalid": "{43F9EB17-0C8C-41E6-9350-5D65DF3B4B1F}",
        "num_catastro": "055-000-002-20",
        "oldpid": "055-000-002-20",
        "service_area_m2": 626589.73053691,
        "deed_area_m2": 620638.5453,
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prop(props: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in props:
            return props[name]
    return None


def collect_coords(obj: Any, out: list[tuple[float, float]]) -> None:
    if (
        isinstance(obj, list)
        and len(obj) >= 2
        and isinstance(obj[0], (int, float))
        and isinstance(obj[1], (int, float))
    ):
        out.append((float(obj[0]), float(obj[1])))
    elif isinstance(obj, list):
        for child in obj:
            collect_coords(child, out)


results: dict[str, Any] = {}
geometries: dict[str, Any] = {}

for label, exp in expected.items():
    doc = json.loads(exp["file"].read_text("utf-8"))
    features = doc.get("features", [])
    if len(features) != 1:
        raise SystemExit(f"FAIL_{label.upper()}_FEATURE_COUNT: {len(features)}")

    feature = features[0]
    props = feature.get("properties") or {}
    geom_json = feature.get("geometry")
    if not geom_json or geom_json.get("type") not in {"Polygon", "MultiPolygon"}:
        raise SystemExit(f"FAIL_{label.upper()}_GEOMETRY_TYPE")

    objectid = prop(props, "OBJECTID", "objectid")
    globalid = prop(props, "GlobalID", "GLOBALID", "globalid")
    num_catastro = prop(props, "NUM_CATASTRO", "num_catastro")
    oldpid = prop(props, "OLDPID", "oldpid")
    area = prop(props, "Shape.STArea()", "SHAPE.STArea()", "shape.starea()")

    if int(objectid) != exp["objectid"]:
        raise SystemExit(f"FAIL_{label.upper()}_OBJECTID: {objectid}")
    if str(globalid).upper() != exp["globalid"].upper():
        raise SystemExit(f"FAIL_{label.upper()}_GLOBALID: {globalid}")
    if str(num_catastro) != exp["num_catastro"]:
        raise SystemExit(f"FAIL_{label.upper()}_NUM_CATASTRO: {num_catastro}")
    if str(oldpid) != exp["oldpid"]:
        raise SystemExit(f"FAIL_{label.upper()}_OLDPID: {oldpid}")

    area = float(area)
    service_delta_pct = abs(area - exp["service_area_m2"]) / exp["service_area_m2"] * 100
    deed_delta_pct = abs(area - exp["deed_area_m2"]) / exp["deed_area_m2"] * 100
    if service_delta_pct > 0.01:
        raise SystemExit(f"FAIL_{label.upper()}_SERVICE_AREA_DELTA: {service_delta_pct:.6f}%")
    if deed_delta_pct > 5.0:
        raise SystemExit(f"FAIL_{label.upper()}_DEED_AREA_DELTA: {deed_delta_pct:.6f}%")

    coords: list[tuple[float, float]] = []
    collect_coords(geom_json.get("coordinates"), coords)
    if len(coords) < 4:
        raise SystemExit(f"FAIL_{label.upper()}_VERTEX_COUNT: {len(coords)}")
    if not all(-67.95 <= x <= -65.2 and 17.7 <= y <= 18.7 for x, y in coords):
        raise SystemExit(f"FAIL_{label.upper()}_PUERTO_RICO_BOUNDS")

    geom = shape(geom_json)
    if geom.is_empty or not geom.is_valid:
        raise SystemExit(
            f"FAIL_{label.upper()}_TOPOLOGY: "
            f"{'empty' if geom.is_empty else explain_validity(geom)}"
        )

    geometries[label] = geom
    results[label] = {
        "file": str(exp["file"]),
        "sha256": sha256(exp["file"]),
        "feature_count": 1,
        "objectid": objectid,
        "globalid": globalid,
        "num_catastro": num_catastro,
        "oldpid": oldpid,
        "geometry_type": geom_json["type"],
        "vertex_count": len(coords),
        "geometry_valid": True,
        "service_area_m2": area,
        "service_area_delta_pct": service_delta_pct,
        "deed_area_delta_pct": deed_delta_pct,
        "bounds": list(geom.bounds),
    }

intersection = geometries["starlink"].intersection(geometries["boehringer"])
intersection_area_degrees = float(intersection.area)
touches = geometries["starlink"].touches(geometries["boehringer"])
overlaps = geometries["starlink"].overlaps(geometries["boehringer"])
if overlaps or intersection_area_degrees > 1e-12:
    raise SystemExit(
        "FAIL_NON_OVERLAP: candidate polygons have positive areal intersection "
        f"in EPSG:4326 ({intersection_area_degrees})"
    )

binding_ok = False
binding_errors: list[str] = []
if binding_path:
    binding = json.loads(binding_path.read_text("utf-8"))
    for label in ("starlink", "boehringer"):
        item = binding.get(label) or {}
        if item.get("binding_status") != "CONFIRMED":
            binding_errors.append(f"{label}.binding_status")
        if int(item.get("objectid", -1)) != expected[label]["objectid"]:
            binding_errors.append(f"{label}.objectid")
        if not item.get("registry_finca"):
            binding_errors.append(f"{label}.registry_finca")
        if not item.get("instrument_id"):
            binding_errors.append(f"{label}.instrument_id")
        source_hash = str(item.get("source_sha256") or "")
        if len(source_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in source_hash):
            binding_errors.append(f"{label}.source_sha256")
    binding_ok = not binding_errors

receipt = {
    "schema_version": "aguayluz.crim-polygon-validation/v0.6",
    "polygons": results,
    "topology": {
        "starlink_valid": True,
        "boehringer_valid": True,
        "touches": touches,
        "overlaps": overlaps,
        "intersection_area_degrees": intersection_area_degrees,
        "non_overlap_pass": True,
    },
    "registry_binding": {
        "provided": bool(binding_path),
        "valid": binding_ok,
        "errors": binding_errors,
        "source_file": str(binding_path) if binding_path else None,
        "source_sha256": sha256(binding_path) if binding_path else None,
    },
    "promotion": {
        "eligible": bool(binding_ok),
        "decision": (
            "PROMOTION_ELIGIBLE"
            if binding_ok
            else "CANDIDATE_GEOMETRY_VALID_BUT_LEGAL_BINDING_REQUIRED"
        ),
    },
}
(root / "polygon_validation_receipt_v0_6.json").write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(receipt, ensure_ascii=False, indent=2))
PY

find "$OUT_DIR" -type f -print0 | sort -z | xargs -0 shasum -a 256 \
  > "$OUT_DIR/all_sha256.txt"

echo "Receipt: $OUT_DIR/polygon_validation_receipt_v0_6.json"
