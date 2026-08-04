#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-crim_05504463104000.geojson}"
URL="https://sigejp.pr.gov/server/rest/services/crim/crim_feb_2025/MapServer/0/query"

curl --fail --show-error --silent --location \
  --get "$URL" \
  --data-urlencode "where=NUM_CATASTRO='05504463104000' OR OLDPID='05504463104000'" \
  --data-urlencode "outFields=OBJECTID,NUM_CATASTRO,OLDPID,GlobalID,X_COORD,Y_COORD,INSIDE_X,INSIDE_Y,TIPO,Shape.STArea(),Shape.STLength()" \
  --data-urlencode "returnGeometry=true" \
  --data-urlencode "returnZ=false" \
  --data-urlencode "outSR=4326" \
  --data-urlencode "f=geojson" \
  --output "$OUT"

python3 - "$OUT" <<'PY'
import json, math, sys
from pathlib import Path

path = Path(sys.argv[1])
doc = json.loads(path.read_text("utf-8"))
features = doc.get("features", [])
if len(features) != 1:
    raise SystemExit(f"FAIL: expected exactly 1 feature, got {len(features)}")

feature = features[0]
props = feature.get("properties") or {}
ids = {str(props.get("NUM_CATASTRO") or ""), str(props.get("OLDPID") or "")}
if "05504463104000" not in ids:
    raise SystemExit(f"FAIL: cadastral ID mismatch: {ids}")

if not props.get("GlobalID"):
    raise SystemExit("FAIL: missing GlobalID")

geom = feature.get("geometry")
if not geom or geom.get("type") not in {"Polygon", "MultiPolygon"}:
    raise SystemExit(f"FAIL: invalid geometry type: {None if not geom else geom.get('type')}")

def walk(obj):
    if isinstance(obj, list) and len(obj) >= 2 and all(isinstance(x, (int, float)) for x in obj[:2]):
        yield float(obj[0]), float(obj[1])
    elif isinstance(obj, list):
        for x in obj:
            yield from walk(x)

points = list(walk(geom.get("coordinates")))
if not points:
    raise SystemExit("FAIL: empty polygon coordinates")
if not all(-67.95 <= x <= -65.2 and 17.7 <= y <= 18.7 for x, y in points):
    raise SystemExit("FAIL: geometry outside Puerto Rico bounds")

area = props.get("Shape.STArea()")
if area is not None:
    deed_area = 165603.1968
    pct = abs(float(area) - deed_area) / deed_area * 100
    if pct > 5:
        raise SystemExit(f"FAIL: service area differs from deed area by {pct:.2f}%")

print(json.dumps({
    "status": "PASS",
    "feature_count": 1,
    "objectid": props.get("OBJECTID"),
    "globalid": props.get("GlobalID"),
    "num_catastro": props.get("NUM_CATASTRO"),
    "oldpid": props.get("OLDPID"),
    "geometry_type": geom.get("type"),
    "vertex_count": len(points),
    "service_area_m2": area,
}, indent=2))
PY

shasum -a 256 "$OUT"
