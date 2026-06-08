#!/usr/bin/env python3
"""Build data/geo/pr_municipios.json (canonical PR municipio names + centroids).

Source: U.S. Census Bureau Gazetteer "counties" file. Puerto Rico's 78 municipios
are county-equivalents (GEOID prefix ``72``); ``INTPTLAT``/``INTPTLONG`` are the
Census internal points (≈ centroid). Census Gazetteer data is public domain.

Download the gazetteer (any recent year), unzip, and pass the ``.txt`` via --src:
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_counties_national.zip

The resulting table is the canonical join key between the ALLCAPS/no-accent
municipio names emitted by utility feeds (e.g. LUMA ``outages_by_town.json``:
``CATANO``) and aguayluz's accented canonical names (``Cataño``). The adapter
derives the lookup key as ``unaccent(name).upper()`` at load time, so no alias
table is maintained by hand.
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

DEFAULT_SRC = "/tmp/2023_Gaz_counties_national.txt"
SUFFIX = " Municipio"
SOURCE_NOTE = (
    "U.S. Census Bureau Gazetteer (counties), Puerto Rico county-equivalents "
    "(GEOID prefix 72); centroid = INTPTLAT/INTPTLONG. Public domain."
)


def unaccent_upper(name: str) -> str:
    """Fold diacritics and uppercase -> the join key utility feeds use (CATANO)."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def build(rows: list[str]) -> list[dict]:
    out = []
    for line in rows:
        cols = line.rstrip("\n").split("\t")
        geoid, name = cols[1].strip(), cols[3].strip()
        if not geoid.startswith("72"):
            continue
        if name.endswith(SUFFIX):
            name = name[: -len(SUFFIX)].strip()
        lat, lon = float(cols[-2].strip()), float(cols[-1].strip())
        out.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6)})
    out.sort(key=lambda m: m["name"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default="data/geo/pr_municipios.json")
    args = ap.parse_args()

    rows = Path(args.src).read_text(encoding="utf-8").splitlines()[1:]  # drop header
    municipios = build(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"_source": SOURCE_NOTE, "municipios": municipios}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(municipios)} municipios -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
