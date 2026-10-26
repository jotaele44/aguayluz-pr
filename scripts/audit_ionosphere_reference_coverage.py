"""CI-only topology evidence for the frozen municipio reference, not cell identity."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SHA256 = "4320683f165f6c4c24bdceead5ce40da4a29de94898a27819c039fad09ea9796"


def classify(geometry, region) -> str:
    """Classify complete source geometry without repairing it or assigning identity."""
    if geometry is None or geometry.is_empty:
        return "NULL_EMPTY"
    if not geometry.is_valid:
        return "UNRESOLVED"
    if region.covers(geometry):
        return "FULLY_WITHIN"
    if region.disjoint(geometry):
        return "OUTSIDE"
    if region.touches(geometry):
        return "TOUCH_ONLY"
    return "PARTIAL"


def audit() -> dict:
    """Freeze all 78 reference rows against actual grid-node envelope and UI window."""
    from shapely.geometry import Polygon, box, shape

    region = box(0, 0, 2, 2)
    cases = [
        (box(0.5, 0.5, 1.5, 1.5), "FULLY_WITHIN"),
        (box(3, 3, 4, 4), "OUTSIDE"),
        (box(2, 0, 3, 1), "TOUCH_ONLY"),
        (box(1, 1, 3, 3), "PARTIAL"),
        (None, "NULL_EMPTY"),
        (Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]), "UNRESOLVED"),
    ]
    for geometry, expected in cases:
        if classify(geometry, region) != expected:
            raise ValueError("topology regression gate failed")
    raw = (ROOT / "data/geo/pr_municipios.geojson").read_bytes()
    if hashlib.sha256(raw).hexdigest() != REFERENCE_SHA256:
        raise ValueError("reference snapshot changed")
    reference = json.loads(raw)
    if (
        reference.get("crs", {}).get("properties", {}).get("name")
        != "urn:ogc:def:crs:OGC:1.3:CRS84"
    ):
        raise ValueError("reference CRS/axis order unverified")
    features = reference["features"]
    if len(features) != 78:
        raise ValueError("reference denominator differs")
    rows = []
    ids = set()
    for feature in features:
        p = feature["properties"]
        geoid = p["geoid"]
        if not isinstance(geoid, str) or not re.fullmatch(r"72[0-9]{3}", geoid) or geoid in ids:
            raise ValueError("invalid or duplicate reference GEOID")
        ids.add(geoid)
        g = shape(feature["geometry"]) if feature["geometry"] else None
        rows.append(
            {
                "source_properties": p,
                "geometry_type": g.geom_type if g else None,
                "valid": bool(g is not None and g.is_valid),
                "has_z": bool(g is not None and g.has_z),
                "has_m": bool(g is not None and getattr(g, "has_m", False)),
                "source_node_envelope": classify(g, box(-177.5, -88.75, 177.5, 88.75)),
                "context_window": classify(g, box(-70, 16, -60, 22)),
            }
        )
    counts = dict(Counter(row["source_node_envelope"] for row in rows))
    passed = counts == {"FULLY_WITHIN": 78} and all(
        row["context_window"] == "FULLY_WITHIN" for row in rows
    )
    return {
        "state": "PASS_REFERENCE_ENVELOPE_COVERAGE" if passed else "UNRESOLVED",
        "reference_sha256": REFERENCE_SHA256,
        "crs": reference["crs"],
        "reference_count": len(features),
        "classified_count": len(rows),
        "excluded_count": 0,
        "counts": counts,
        "rows": rows,
        "scope": "All geometries in the frozen generalized Census-derived municipio reference are within the actual complete source grid's coordinate envelope and the context window.",
        "limitations": [
            "No station, cell, municipality measurement or asset identity assigned",
            "Reference is generalized and simplified; no legal-boundary or EEZ completeness claim",
            "Model grid envelope is not an observation-support footprint",
        ],
        "reference_source": "scripts/build_pr_geo_boundaries.py; cb_2023_us_county_500k.zip; derived frozen reference only",
    }


if __name__ == "__main__":
    result = audit()
    raw = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode()
    target = ROOT / "data-sources/ionosphere/reference_coverage.json"
    if "--check" in sys.argv:
        if target.read_bytes() != raw:
            raise SystemExit("reference coverage report differs")
    else:
        target.write_bytes(raw)
    print(result["state"])
    raise SystemExit(0 if result["state"] == "PASS_REFERENCE_ENVELOPE_COVERAGE" else 1)
