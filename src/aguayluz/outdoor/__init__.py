"""Outdoor conditions layer: per-municipio current conditions for time spent outside.

Six sources join the NWS hydromet plane (:mod:`aguayluz.hydromet`), so they share its
byte-SHA-256 manifestations, receipts and freshness, and show up on the dashboard's NWS
Hydromet page with no UI of their own:

==========================  ===============================================  ===========
source_id                   what it carries                                  writes
==========================  ===============================================  ===========
``nws_surf_zone``           NWS San Juan Surf Zone Forecast (rip current      records +
                            risk, surf height) per beach zone                 state
``nws_marine_alerts``       NWS alerts for the PR marine zones (AMZ7xx)       records
``ndbc_buoys``              NDBC/CARICOOS buoy observations (waves, wind,     state
                            water temperature)
``epa_uv``                  EPA UV index forecast, one ZIP per municipio      state
``nws_gridpoint_heat``      NWS gridded heat index at each municipio          state
                            centroid
``airnow``                  AirNow current AQI (needs ``AIRNOW_API_KEY``)     state
==========================  ===============================================  ===========

:mod:`aguayluz.outdoor.compose` folds these, plus conditions the corpus already holds
(DRNA beach advisories, NWPS flood stage, Stage IV rainfall, NHC storms, El Yunque
closures), into ``data/outdoor_conditions.jsonl``: one row per municipio. That file is
what the federation export carries to the hub; this repository's dashboard is
diagnostic only (ADR 0001).

Conditions are context, not safety advice. A component the corpus has no data for says
why (``NOT_COVERED``, ``NOT_INGESTED``, ``STALE``, ``SOURCE_FAILED``,
``NOT_CONFIGURED``) and is never shown as benign.

Stdlib only, like :mod:`aguayluz.hydromet.store`: the backend may import it.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from .. import DATA_DIR, REPO_ROOT

#: Per-source current-state file, under the data directory. Committed (see .gitignore).
STATE_FILES: dict[str, str] = {
    "nws_surf_zone": "outdoor_surf_state.jsonl",
    "ndbc_buoys": "outdoor_buoy_state.jsonl",
    "epa_uv": "outdoor_uv_state.jsonl",
    "nws_gridpoint_heat": "outdoor_heat_state.jsonl",
    "airnow": "outdoor_aqi_state.jsonl",
}

#: The composed per-municipio layer.
CONDITIONS_FILE = "outdoor_conditions.jsonl"

#: Frozen reference bindings (marine zones → municipios, centroid → NWS gridpoint,
#: municipio → ZIP). Built by scripts/freeze_outdoor_reference.py from public sources.
#: Lives in the repository tree, not the (relocatable) data workspace.
REFERENCE_FILE = REPO_ROOT / "data" / "reference" / "outdoor_reference.v1.json"
REFERENCE_SCHEMA = "aguayluz.outdoor-reference/v1"


def state_path(source_id: str, data_dir: Path | str | None = None) -> Path:
    try:
        name = STATE_FILES[source_id]
    except KeyError:
        raise ValueError(f"{source_id!r} keeps no outdoor state file") from None
    return Path(data_dir if data_dir is not None else DATA_DIR) / name


def conditions_path(data_dir: Path | str | None = None) -> Path:
    return Path(data_dir if data_dir is not None else DATA_DIR) / CONDITIONS_FILE


MUNICIPIO_CENTROIDS = REPO_ROOT / "data" / "geo" / "pr_municipios.json"
MUNICIPIO_POLYGONS = REPO_ROOT / "data" / "geo" / "pr_municipios.geojson"


def municipio_key(name: Any) -> str:
    """Accent- and case-insensitive name key (same folding as aguayluz.hydromet.spatial)."""
    folded = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return " ".join(folded.casefold().split())


def load_municipios(centroids: Path | None = None,
                    polygons: Path | None = None) -> list[dict[str, Any]]:
    """The 78 municipios: Census name, GEOID and internal point (INTPTLAT/INTPTLONG).

    The internal point is the Census-published point guaranteed to fall inside the
    polygon; every consumer of it labels the geometry ``REPRESENTATIVE_POINT``.
    """
    points = json.loads(Path(centroids or MUNICIPIO_CENTROIDS).read_text(encoding="utf-8"))
    shapes = json.loads(Path(polygons or MUNICIPIO_POLYGONS).read_text(encoding="utf-8"))
    geoids = {
        municipio_key((f.get("properties") or {}).get("name")): str(f["properties"]["geoid"])
        for f in shapes.get("features", []) if (f.get("properties") or {}).get("geoid")
    }
    out = []
    for row in points.get("municipios", []):
        geoid = geoids.get(municipio_key(row.get("name")))
        if geoid is None:
            raise ValueError(f"municipio {row.get('name')!r} has a centroid but no polygon GEOID")
        out.append({"name": row["name"], "geoid": geoid,
                    "lat": float(row["lat"]), "lon": float(row["lon"])})
    return sorted(out, key=lambda m: m["geoid"])


def load_reference(path: Path | str | None = None) -> dict[str, Any]:
    """The frozen reference file, or an empty skeleton when it has not been built."""
    target = Path(path) if path is not None else REFERENCE_FILE
    if not target.is_file():
        return {"schema_version": REFERENCE_SCHEMA, "marine_zones": [], "gridpoints": [],
                "uv_zips": [], "unresolved_material": ["REFERENCE_FILE_MISSING"]}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != REFERENCE_SCHEMA:
        raise ValueError(f"{target} is not an {REFERENCE_SCHEMA} file")
    return payload


__all__ = [
    "CONDITIONS_FILE",
    "MUNICIPIO_CENTROIDS",
    "MUNICIPIO_POLYGONS",
    "REFERENCE_FILE",
    "REFERENCE_SCHEMA",
    "STATE_FILES",
    "conditions_path",
    "load_municipios",
    "load_reference",
    "municipio_key",
    "state_path",
]
