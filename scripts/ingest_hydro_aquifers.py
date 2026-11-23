#!/usr/bin/env python3
"""Aquifer claims for the Puerto Rico hydrologic feature inventory.

Sources (``config/hydro_inventory_sources.v1.json``):

  * USGS HA 730-N polygon release ``aquifers_pr`` (doi:10.5066/P98YGFVN), pinned by SHA-256
  * USGS aquifer-code dictionaries (Water Data API), live: hashes recorded
  * USGS HA 730-N text pages, live: each quoted sentence must be present or the run fails
  * DRNA PIRA 2016, transcribed unit list held in the config (tier T2)

Outputs, all committed:

  * ``data/geo/pr_aquifers.geojson``        simplified WGS84 polygons, Puerto Rico only
  * ``data/hydro/claims_aquifers.jsonl``     one claim per source statement about an aquifer
  * ``data/hydro/ingest_aquifers_receipt.json``

Datum. The shapefile's ``.prj`` declares NAD27, but read that way the mainland sits about
210 m north of the Census coastline; read as Puerto Rico 1940 (EPSG:4139) it fits to a
median of tens of metres. The run re-measures both readings against
``data/geo/pr_municipios.geojson`` every time, uses Puerto Rico 1940, refuses any
transformation without a stated accuracy (PROJ "ballpark"), and fails if the median
coastline distance is not under ``COASTLINE_GATE_M``.

Needs the ``[geo]`` extra (geopandas, shapely, pyproj). Offline: ``--src-dir`` holding the
raw files under the names in ``RAW_NAMES``; the default is a live fetch.

    python scripts/ingest_hydro_aquifers.py --src-dir /path/to/raw --dry-run
    python scripts/ingest_hydro_aquifers.py --fetch
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import statistics
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import CONFIG_DIR, DATA_DIR  # noqa: E402
from aguayluz import hydro_inventory as hi  # noqa: E402

COASTLINE_GATE_M = 100.0
SIMPLIFY_DEG = 0.0003
DECIMALS = 5
AREA_TOLERANCE = 0.02
SCIENCEBASE_ITEM = "https://www.sciencebase.gov/catalog/item/{item}?format=json"
PR_AOI = (-68.0, 17.5, -65.0, 18.7)

RAW_NAMES = {
    "usgs_ha730_aquifers_pr": "aquifers_pr_shp.zip",
    "usgs_aquifer_codes": "aquifer-codes.json",
    "usgs_national_aquifer_codes": "national-aquifer-codes.json",
    "usgs_monitoring_locations": "ml",  # directory of page_*.json (used for code assignment)
    "usgs_ha730_text": "ha730_text",  # directory of the quoted pages
}

#: HA 730-N classes. Only these are aquifers; 997 and 999 are not, and 907/420 are Virgin Islands units.
AQUIFER_CLASSES = {"4191", "4192", "114", "115", "908"}
NON_AQUIFER_REASON = {"997": "confining unit in the source, not an aquifer", "999": "'other' in the source, not an aquifer"}
USVI_CLASSES = {"907", "420"}


class AcquisitionError(RuntimeError):
    """A source did not return the bytes we asked for."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _get(url: str) -> bytes:
    import httpx

    from aguayluz.http_retry import get_with_retry
    from aguayluz.hydromet import USER_AGENT

    with httpx.Client(timeout=180, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        response = get_with_retry(url, client=client)
    if response.status_code != 200:
        raise AcquisitionError(f"HTTP {response.status_code} from {url}")
    return response.content


# ── acquisition ───────────────────────────────────────────────────────────────
def acquire(config: dict[str, Any], src_dir: Path | None, accept_new: bool) -> dict[str, Any]:
    """Raw bytes for every source, with a manifestation record each."""
    static = {s["source_key"]: s for s in config["static_sources"]}
    live = {s["source_key"]: s for s in config["live_sources"]}
    raw: dict[str, Any] = {}
    manifest: list[dict[str, Any]] = []

    def record(key: str, url: str, payload: bytes, pin: str | None) -> None:
        digest = hashlib.sha256(payload).hexdigest()
        if pin is not None and digest != pin and not accept_new:
            raise AcquisitionError(f"{key}: SHA-256 {digest} differs from the pin {pin}; the release changed")
        manifest.append({"source_key": key, "url": url, "byte_sha256": digest, "bytes": len(payload),
                         "pin_matches": None if pin is None else digest == pin})

    ha = static["usgs_ha730_aquifers_pr"]
    if src_dir:
        payload = (src_dir / RAW_NAMES["usgs_ha730_aquifers_pr"]).read_bytes()
    else:
        item = json.loads(_get(SCIENCEBASE_ITEM.format(item=ha["sciencebase_item_id"])))
        files = [f for f in item.get("files", []) if f.get("name") == ha["file_name"]]
        if len(files) != 1:
            raise AcquisitionError(f"ScienceBase item has {len(files)} files named {ha['file_name']}")
        payload = _get(files[0]["url"])
        if hashlib.md5(payload, usedforsecurity=False).hexdigest() != ha["expected_md5"]:
            raise AcquisitionError("aquifers_pr_shp.zip: MD5 does not match ScienceBase")
    record(ha["source_key"], ha["source_url"], payload, ha["pinned_sha256"])
    raw["ha730_zip"] = payload

    for key in ("usgs_aquifer_codes", "usgs_national_aquifer_codes"):
        url = live[key]["url"]
        payload = (src_dir / RAW_NAMES[key]).read_bytes() if src_dir else _get(url)
        record(key, url, payload, None)
        raw[key] = json.loads(payload)

    pages: list[dict[str, Any]] = []
    if src_dir:
        for path in sorted((src_dir / RAW_NAMES["usgs_monitoring_locations"]).glob("page_*.json")):
            payload = path.read_bytes()
            record("usgs_monitoring_locations", live["usgs_monitoring_locations"]["url"], payload, None)
            pages.append(json.loads(payload))
    else:
        url: str | None = live["usgs_monitoring_locations"]["url"]
        while url:
            payload = _get(url)
            record("usgs_monitoring_locations", url, payload, None)
            page = json.loads(payload)
            pages.append(page)
            nxt = [link["href"] for link in page.get("links", []) if link.get("rel") == "next"]
            url = nxt[0] if nxt and page.get("features") else None
    raw["monitoring_locations"] = pages

    text = live["usgs_ha730_text"]
    raw["ha730_text"] = {}
    for page in text["pages"]:
        url = text["url"] + page
        payload = (src_dir / RAW_NAMES["usgs_ha730_text"] / page).read_bytes() if src_dir else _get(url)
        record("usgs_ha730_text", url, payload, None)
        raw["ha730_text"][page] = payload
    raw["manifest"] = manifest
    return raw


# ── geometry ──────────────────────────────────────────────────────────────────
def _transformer_crs(gdf_crs: Any, datum_epsg: int) -> Any:
    import pyproj
    from pyproj.crs import ProjectedCRS

    declared = pyproj.CRS.from_wkt(gdf_crs.to_wkt())
    return ProjectedCRS(conversion=declared.coordinate_operation, geodetic_crs=pyproj.CRS.from_epsg(datum_epsg))


def choose_transformer(src_crs: Any) -> tuple[Any, dict[str, Any]]:
    """The most accurate available operation to WGS84; never one without a stated accuracy."""
    import pyproj

    group = pyproj.transformer.TransformerGroup(
        src_crs, "EPSG:4326", always_xy=True, area_of_interest=pyproj.aoi.AreaOfInterest(*PR_AOI)
    )
    usable = [t for t in group.transformers if t.accuracy is not None and t.accuracy > 0]
    if not usable:
        raise ValueError("no transformation with a stated accuracy is available; refusing a ballpark offset")
    best = min(usable, key=lambda t: t.accuracy)
    return best, {"operation": best.description, "accuracy_m": best.accuracy,
                  "unavailable_better_operations": [op.name for op in group.unavailable_operations]}


def coastline_offsets(polygons_wgs84: list[Any], coast: Any) -> dict[str, float]:
    """Median and 90th-percentile distance (m), and signed north-south offset, outline to coast."""
    import pyproj
    from shapely.ops import nearest_points, unary_union

    union = unary_union(polygons_wgs84)
    parts = sorted(getattr(union, "geoms", [union]), key=lambda p: -p.area)
    outline = parts[0].exterior
    geod = pyproj.Geod(ellps="WGS84")
    distances, north = [], []
    for i in range(400):
        p = outline.interpolate(i / 400, normalized=True)
        q = nearest_points(p, coast)[1]
        distances.append(geod.inv(p.x, p.y, q.x, q.y)[2])
        north.append(geod.inv(p.x, q.y, p.x, p.y)[2] * (1 if p.y >= q.y else -1))
    distances.sort()
    return {"median_m": round(statistics.median(distances), 1),
            "p90_m": round(distances[int(0.9 * len(distances))], 1),
            "median_north_offset_m": round(statistics.median(north), 1)}


def island_of(lon: float, lat: float) -> str:
    if lon > -65.1:
        return "usvi"
    if lon < -67.7:
        return "mona"
    if -65.65 <= lon <= -65.2 and lat < 18.2:
        return "vieques"
    if -65.4 <= lon <= -65.2 and lat > 18.25:
        return "culebra"
    return "main"


def process_polygons(zip_bytes: bytes, municipios_path: Path) -> dict[str, Any]:
    import geopandas as gpd
    from shapely.ops import unary_union

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        shp_names = [n for n in archive.namelist() if n.endswith(".shp")]
        if len(shp_names) != 1:
            raise ValueError(f"expected one shapefile in the archive, found {shp_names}")
        stem = shp_names[0][:-4]
        tmp = {n: archive.read(n) for n in archive.namelist() if n.startswith(stem)}
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, data in tmp.items():
            Path(tmpdir, Path(name).name).write_bytes(data)
        source = gpd.read_file(Path(tmpdir, Path(shp_names[0]).name))
    expected = {"AQ_CODE", "AQ_NAME", "ROCK_NAME"}
    if not expected <= set(source.columns):
        raise ValueError(f"shapefile columns changed: missing {expected - set(source.columns)}")
    declared_wkt = source.crs.to_wkt()
    source["polygon_index"] = range(len(source))
    source["AQ_CODE"] = source["AQ_CODE"].astype(int).astype(str)

    mun = gpd.read_file(municipios_path).to_crs(4326)
    coast = unary_union(list(mun.geometry)).boundary
    mainland_mask = ~source["AQ_CODE"].isin(USVI_CLASSES)

    checks = {}
    for label, epsg in (("declared_nad27", 4267), ("puerto_rico_1940", 4139)):
        crs = _transformer_crs(source.crs, epsg)
        transformer, op = choose_transformer(crs)
        reproj = source[mainland_mask].set_crs(crs, allow_override=True).to_crs(4326)
        checks[label] = {**op, **coastline_offsets(list(reproj.geometry), coast)}
    used = checks["puerto_rico_1940"]
    if used["median_m"] >= COASTLINE_GATE_M:
        raise ValueError(f"coastline gate failed: median {used['median_m']} m with Puerto Rico 1940")

    crs = _transformer_crs(source.crs, 4139)
    projected = source.set_crs(crs, allow_override=True)
    wgs = projected.to_crs(4326)
    wgs["island"] = [island_of(g.representative_point().x, g.representative_point().y) for g in wgs.geometry]

    simplified = wgs.copy()
    simplified["geometry"] = simplified.geometry.simplify(SIMPLIFY_DEG, preserve_topology=True)
    simplified["geometry"] = simplified.geometry.make_valid()
    back = simplified.to_crs(crs)
    area_check = {}
    for code, group in projected.groupby("AQ_CODE"):
        before = float(group.geometry.area.sum())
        after = float(back.loc[group.index].geometry.area.sum())
        change = (after - before) / before if before else 0.0
        area_check[code] = {"source_km2": round(before / 1e6, 3), "simplified_km2": round(after / 1e6, 3),
                            "relative_change": round(change, 4)}
        if abs(change) > AREA_TOLERANCE:
            raise ValueError(f"simplification changed class {code} area by {change:.1%}")
    simplified["area_km2"] = [round(a / 1e6, 4) for a in projected.geometry.area]
    return {"frame": simplified, "projected": projected, "municipios": mun, "datum_checks": checks,
            "area_check": area_check, "declared_wkt": declared_wkt}


def _touching_components(idx: list[int], touches: Any) -> dict[int, list[int]]:
    parent = {i: i for i in idx}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a_pos, a in enumerate(idx):
        for b in idx[a_pos + 1:]:
            if touches(a, b):
                parent[find(a)] = find(b)
    comps: dict[int, list[int]] = {}
    for i in idx:
        comps.setdefault(find(i), []).append(i)
    return comps


def group_features(frame: Any, municipios: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Polygon rows (for the GeoJSON) and HA 730 aquifer groups (for the claims)."""
    from shapely.ops import unary_union

    rows, groups = [], {}
    pr = frame[frame["island"] != "usvi"]
    # alluvial valleys: touching polygons on one island form one unnamed component
    comp_of: dict[int, str] = {}
    for island, sub in pr[pr["AQ_CODE"] == "115"].groupby("island"):
        idx = list(sub.index)
        geoms = sub.geometry
        comps = _touching_components(idx, lambda a, b, g=geoms: g[a].buffer(1e-7).intersects(g[b]))
        ordered = sorted(comps.values(), key=lambda members: unary_union([geoms[m] for m in members]).centroid.x)
        for n, members in enumerate(ordered, 1):
            for m in members:
                comp_of[m] = f"HA730:115:{island}:c{n:02d}"
    for i, row in frame.iterrows():
        code, island = row["AQ_CODE"], row["island"]
        if island == "usvi" or code in USVI_CLASSES:
            disposition, group, reason = "EXCLUDED", None, "outside Puerto Rico (U.S. Virgin Islands)"
        elif code in NON_AQUIFER_REASON:
            disposition, group, reason = "EXCLUDED", None, NON_AQUIFER_REASON[code]
        elif code == "115":
            disposition, group, reason = "RETAINED", comp_of[i], None
        elif code in AQUIFER_CLASSES:
            disposition, group, reason = "RETAINED", f"HA730:{code}:{island}", None
        else:
            raise ValueError(f"unknown HA 730 class {code}")
        polygon_id = f"HA730_P{int(row['polygon_index']):04d}"
        rows.append({"polygon_id": polygon_id, "aq_code": code, "aq_name": row["AQ_NAME"], "island": island,
                     "area_km2": row["area_km2"], "group_key": group, "disposition": disposition,
                     "exclusion_reason": reason, "geometry": row.geometry})
        if group:
            g = groups.setdefault(group, {"group_key": group, "aq_code": code, "aq_name": row["AQ_NAME"],
                                          "rock_name": row.get("ROCK_NAME"), "island": island,
                                          "polygon_ids": [], "geoms": []})
            g["polygon_ids"].append(polygon_id)
            g["geoms"].append(row.geometry)
    out = []
    mun_geoms = list(zip(municipios["name"], municipios.geometry, strict=True))
    for key in sorted(groups):
        g = groups[key]
        union = unary_union(g.pop("geoms"))
        overlaps = sorted(((union.intersection(mg).area, name) for name, mg in mun_geoms if union.intersects(mg)),
                          reverse=True)
        g["municipios"] = [name for area, name in overlaps if area > 0][:6]
        g["area_km2"] = round(sum(r["area_km2"] for r in rows if r["group_key"] == key), 3)
        out.append(g)
    return rows, out


def write_geojson(rows: list[dict[str, Any]], path: Path) -> None:
    from shapely.geometry import mapping

    def rnd(obj: Any) -> Any:
        if isinstance(obj, float):
            return round(obj, DECIMALS)
        if isinstance(obj, (list, tuple)):
            return [rnd(o) for o in obj]
        return obj

    def clean(value: Any) -> Any:
        # shapefile attributes come through pandas, where a missing value is NaN; JSON has no NaN
        return None if isinstance(value, float) and value != value else value

    features = []
    for r in rows:
        if r["disposition"] != "RETAINED" and r["exclusion_reason"].startswith("outside"):
            continue  # Virgin Islands polygons are counted in the receipt, not drawn
        geom = mapping(r["geometry"])
        features.append({"type": "Feature",
                         "properties": {k: clean(r[k]) for k in ("polygon_id", "aq_code", "aq_name", "island", "area_km2",
                                                                "group_key", "disposition", "exclusion_reason")},
                         "geometry": {"type": geom["type"], "coordinates": rnd(geom["coordinates"])}})
    doc = {"type": "FeatureCollection",
           "_source": "USGS HA 730-N aquifers_pr (doi:10.5066/P98YGFVN); datum read as Puerto Rico 1940; "
                      f"simplified {SIMPLIFY_DEG} deg, {DECIMALS} decimals. Built by scripts/ingest_hydro_aquifers.py.",
           "features": features}
    hi.atomic_write(path, json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


# ── claims ────────────────────────────────────────────────────────────────────
def code_claims(raw: dict[str, Any], config: dict[str, Any], manifest_sha: dict[str, str], now: str
                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    names = {f["id"]: f["properties"]["aquifer_name"] for f in raw["usgs_aquifer_codes"]["features"]}
    nat_names = {f["id"]: f["properties"]["national_aquifer_name"] for f in raw["usgs_national_aquifer_codes"]["features"]}
    assigned: dict[str, int] = {}
    nat_assigned: dict[str, int] = {}
    for page in raw["monitoring_locations"]:
        for f in page["features"]:
            p = f["properties"]
            if p.get("aquifer_code"):
                assigned[p["aquifer_code"]] = assigned.get(p["aquifer_code"], 0) + 1
            if p.get("national_aquifer_code"):
                nat_assigned[p["national_aquifer_code"]] = nat_assigned.get(p["national_aquifer_code"], 0) + 1
    rules = config["aquifer_codes"]
    claims, excluded = [], {}
    for code in sorted(set(assigned) | set(rules["named_for_puerto_rico_unassigned"])):
        if code not in names:
            raise ValueError(f"aquifer code {code} is not in the USGS dictionary")
        basis = (f"assigned to {assigned[code]} Puerto Rico monitoring location(s)" if code in assigned
                 else "named for a Puerto Rico place in the USGS dictionary; no Puerto Rico location assigned")
        claims.append(hi.claim(
            source_key="usgs_aquifer_codes", authority="USGS", feature_type="aquifer",
            source_feature_id=f"USGS_AQFR:{code}", name_raw=names[code], evidence_tier="T1",
            manifestation_sha256=manifest_sha["usgs_aquifer_codes"], retrieved_utc=now,
            attributes={"aquifer_code": code, "assigned_location_count": assigned.get(code, 0), "selection_basis": basis}))
    for code in sorted(nat_assigned):
        if code in rules["catch_all_excluded"]:
            excluded[code] = f"catch-all national code ('{nat_names.get(code)}'), not an aquifer unit"
            continue
        claims.append(hi.claim(
            source_key="usgs_national_aquifer_codes", authority="USGS", feature_type="aquifer",
            source_feature_id=f"USGS_NAQFR:{code}", name_raw=nat_names[code], evidence_tier="T1",
            manifestation_sha256=manifest_sha["usgs_national_aquifer_codes"], retrieved_utc=now,
            attributes={"national_aquifer_code": code, "assigned_location_count": nat_assigned[code]}))
    for code in rules["stratigraphic_known_not_enumerated"]:
        excluded[code] = f"stratigraphic unit ('{names.get(code, 'not in dictionary')}') with no Puerto Rico location assigned"
    ledger = {"codes_assigned_in_pr": len(assigned), "national_codes_assigned_in_pr": len(nat_assigned),
              "codes_named_for_pr_unassigned": len(rules["named_for_puerto_rico_unassigned"]),
              "excluded": excluded}
    return claims, ledger


def text_claims(raw: dict[str, Any], config: dict[str, Any], manifest_sha: dict[str, str], now: str
                ) -> list[dict[str, Any]]:
    out = []
    pages = {k: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", v.decode("utf-8", "replace"))))
             for k, v in raw["ha730_text"].items()}
    for tc in config["text_claims"]:
        if tc["quote"] not in pages[tc["page"]]:
            raise ValueError(f"{tc['claim_key']}: the quoted sentence is no longer on {tc['page']}")
    esperanza = next(t for t in config["text_claims"] if t["claim_key"] == "ha730_esperanza")
    out.append(hi.claim(
        source_key="usgs_ha730_text", authority="USGS", feature_type="aquifer",
        source_feature_id="HA730_TEXT:ESPERANZA_RESOLUCION", name_raw="Esperanza-Resolución Valley aquifer",
        evidence_tier="T1", manifestation_sha256=manifest_sha[f"usgs_ha730_text:{esperanza['page']}"],
        retrieved_utc=now, attributes={"island": "vieques", "quote": esperanza["quote"], "page": esperanza["page"]}))
    return out


def pira_claims(config: dict[str, Any]) -> list[dict[str, Any]]:
    src = next(s for s in config["static_sources"] if s["source_key"] == "drna_pira_2016")
    out = []
    for unit in config["pira_2016_units"]:
        out.append(hi.claim(
            source_key="drna_pira_2016", authority="PR_DRNA", feature_type="aquifer",
            source_feature_id=unit["unit_key"], name_raw=unit["name_raw"], evidence_tier="T2",
            manifestation_sha256=src["pinned_sha256"], retrieved_utc=src["retrieved_utc"],
            extraction_method="manual_transcription",
            attributes={k: unit[k] for k in ("system", "rock_type", "page", "quote") if k in unit}))
    return out


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-dir", type=Path, help="directory of raw files (offline)")
    ap.add_argument("--fetch", action="store_true", help="fetch every source live")
    ap.add_argument("--accept-new-release", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--now", help="override the run clock (ISO 8601)")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.fetch and not args.src_dir:
        print("ingest_hydro_aquifers: pass --fetch or --src-dir", file=sys.stderr)
        return 2
    now = _iso(datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc))
    config = json.loads((args.config_dir / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    receipt_path = args.data_dir / hi.HYDRO_DIR / "ingest_aquifers_receipt.json"
    try:
        raw = acquire(config, None if args.fetch else args.src_dir, args.accept_new_release)
        geo = process_polygons(raw["ha730_zip"], args.data_dir / "geo" / "pr_municipios.geojson")
        rows, groups = group_features(geo["frame"], geo["municipios"])
    except Exception as exc:  # noqa: BLE001 - every failure leaves a FAIL receipt
        print(f"ingest_hydro_aquifers: FAIL — {exc}", file=sys.stderr)
        if not args.dry_run:
            hi.write_fail_receipt(receipt_path, "aquifers", now, str(exc))
        return 1

    sha = {m["source_key"]: m["byte_sha256"] for m in raw["manifest"]}
    for m in raw["manifest"]:
        if m["source_key"] == "usgs_ha730_text":
            sha[f"usgs_ha730_text:{m['url'].rsplit('/', 1)[-1]}"] = m["byte_sha256"]
    ha = next(s for s in config["static_sources"] if s["source_key"] == "usgs_ha730_aquifers_pr")
    claims = []
    for g in groups:
        claims.append(hi.claim(
            source_key="usgs_ha730_aquifers_pr", authority="USGS", feature_type="aquifer",
            source_feature_id=g["group_key"], name_raw=g["aq_name"], evidence_tier="T1",
            manifestation_sha256=sha["usgs_ha730_aquifers_pr"], retrieved_utc=ha["retrieved_utc"],
            attributes={"aq_code": g["aq_code"], "rock_name": g["rock_name"], "island": g["island"],
                        "polygon_ids": g["polygon_ids"], "area_km2": g["area_km2"], "municipios": g["municipios"],
                        "name_is_source_class_only": g["aq_code"] == "115"}))
    try:
        cc, code_ledger = code_claims(raw, config, sha, now)
        claims += cc + text_claims(raw, config, sha, now) + pira_claims(config)
    except Exception as exc:  # noqa: BLE001
        print(f"ingest_hydro_aquifers: FAIL — {exc}", file=sys.stderr)
        if not args.dry_run:
            hi.write_fail_receipt(receipt_path, "aquifers", now, str(exc))
        return 1

    by_reason: dict[str, int] = {}
    for r in rows:
        if r["disposition"] == "EXCLUDED":
            by_reason[r["exclusion_reason"]] = by_reason.get(r["exclusion_reason"], 0) + 1
    retained = sum(1 for r in rows if r["disposition"] == "RETAINED")
    polygon_ledger = hi.close_ledger(source_rows=len(rows), retained=retained, excluded=by_reason, unresolved=0)
    summary = {
        "stage": "aquifers", "status": "PASS", "run_utc": now, "manifestations": raw["manifest"],
        "datum": {"declared_wkt_sha256": hashlib.sha256(geo["declared_wkt"].encode()).hexdigest(),
                  "used": "EPSG:4139 Puerto Rico 1940", "checks": geo["datum_checks"],
                  "gate_m": COASTLINE_GATE_M},
        "simplification": {"tolerance_deg": SIMPLIFY_DEG, "decimals": DECIMALS, "area_check": geo["area_check"]},
        "ledgers": {"ha730_polygons": polygon_ledger, "aquifer_codes": code_ledger,
                    "ha730_groups": len(groups), "claims": len(claims)},
    }
    if args.dry_run:
        print(json.dumps(summary, indent=2, default=str)[:4000])
        return 0
    write_geojson(rows, args.data_dir / "geo" / "pr_aquifers.geojson")
    hi.write_claims(args.data_dir / hi.HYDRO_DIR / "claims_aquifers.jsonl", claims)
    hi.atomic_write(receipt_path, json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    print(f"ingest_hydro_aquifers: PASS — {len(claims)} aquifer claims, {retained} polygons retained, "
          f"coastline median {geo['datum_checks']['puerto_rico_1940']['median_m']} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
