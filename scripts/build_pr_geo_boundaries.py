#!/usr/bin/env python3
"""Build PR municipio + barrio boundary GeoJSON from U.S. Census cartographic files.

Map/visualization layer (complements data/geo/pr_municipios.json, which holds
centroids for the ingest/export pipeline). Census cartographic boundary (CB) files
are public domain and generalized for web mapping.

Inputs (download + unzip, pass the .shp via flags):
  * municipios = county-equivalents (STATEFP 72):
      https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip
  * barrios = county subdivisions:
      https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_72_cousub_500k.zip

Outputs: data/geo/pr_municipios.geojson (78), data/geo/pr_barrios.geojson (~900).
Geometry is reprojected to WGS84 (GeoJSON standard), simplified, and written at
~1 m coordinate precision to stay compact and committable.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd

SUFFIX = " Municipio"


def _emit(gdf: gpd.GeoDataFrame, keep: dict[str, str], out: Path, tolerance: float) -> int:
    gdf = gdf.to_crs(4326).copy()
    gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
    cols = {src: dst for src, dst in keep.items()}
    gdf = gdf[list(cols) + ["geometry"]].rename(columns=cols)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    gdf.to_file(out, driver="GeoJSON", COORDINATE_PRECISION=5)
    return len(gdf)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counties", default="/tmp/cb_2023_us_county_500k.shp", help="national county CB shapefile")
    ap.add_argument("--barrios", default="/tmp/cb_2023_72_cousub_500k.shp", help="PR county-subdivision CB shapefile")
    ap.add_argument("--out-dir", default="data/geo")
    ap.add_argument("--tolerance", type=float, default=0.0003, help="simplify tolerance in degrees (~33 m)")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)

    cty = gpd.read_file(args.counties)
    pr_cty = cty[cty["STATEFP"] == "72"]
    n_m = _emit(pr_cty, {"NAME": "name", "GEOID": "geoid"}, out_dir / "pr_municipios.geojson", args.tolerance)

    cs = gpd.read_file(args.barrios)
    pr_cs = cs[cs["STATEFP"] == "72"].copy()
    pr_cs["municipio"] = pr_cs["NAMELSADCO"].str.replace(SUFFIX, "", regex=False).str.strip()
    n_b = _emit(pr_cs, {"NAME": "name", "municipio": "municipio", "GEOID": "geoid"},
                out_dir / "pr_barrios.geojson", args.tolerance)

    print(f"wrote {n_m} municipios -> {out_dir/'pr_municipios.geojson'}")
    print(f"wrote {n_b} barrios   -> {out_dir/'pr_barrios.geojson'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
