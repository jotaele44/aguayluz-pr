#!/usr/bin/env python3
"""Surface-water claims for the Puerto Rico hydrologic inventory: streams, waterbodies, watersheds,
intakes and gauges.

Sources (``config/hydro_inventory_sources.v1.json``):

  * USGS National Hydrography Dataset, large scale, flowlines and waterbodies (The National Map)
  * USGS Watershed Boundary Dataset, HUC8 and HUC10
  * EPA SDWIS intake facilities, which carry no coordinates
  * NOAA NWPS gauges (``data/nwps_gauge_state.jsonl``, committed) and the repository's own
    OSM reservoirs and local intake points (``data/utility_assets.jsonl``)

Every mapped flowline reach becomes a claim (coastline segments are excluded by reason);
canal/ditch reaches (FType 336) are claimed as canals. A
reach's published ``gnis_id`` is what later joins it to its named watercourse (I2).
Geometry is simplified and written to committed files that stay under the size budget:

  * ``data/geo/streams/<huc8>.geojson``   reaches, one file per HUC8
  * ``data/geo/pr_waterbodies.geojson``
  * ``data/geo/pr_watersheds.geojson``    HUC8 and HUC10

Claims: ``data/hydro/claims_nhd_flowlines.jsonl``, ``claims_nhd_waterbodies.jsonl``,
``claims_wbd.jsonl``, ``claims_sdwis_intakes.jsonl``, ``claims_nwps_gauges.jsonl``,
``claims_repo_assets.jsonl``; receipt ``data/hydro/ingest_surface_receipt.json``.

Needs shapely (the ``[geo]`` extra) for simplification.

    python scripts/ingest_hydro_nhd.py --src-dir /path/to/raw
    python scripts/ingest_hydro_nhd.py --fetch
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import CONFIG_DIR, DATA_DIR  # noqa: E402
from aguayluz import hydro_inventory as hi  # noqa: E402

SIMPLIFY_DEG = 0.0003
DECIMALS = 5
GEO_FILE_BUDGET_BYTES = 2_000_000
PAGE = 1000
#: NHD FType 336 CanalDitch: a built conveyance, listed as a canal rather than a stream reach.
CANAL_FTYPES = frozenset({"336"})


class AcquisitionError(RuntimeError):
    """A source did not return what we asked for."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _get(url: str) -> bytes:
    import httpx

    from aguayluz.http_retry import get_with_retry
    from aguayluz.hydromet import USER_AGENT

    with httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        response = get_with_retry(url, client=client)
    if response.status_code != 200 or b'"error"' in response.content[:200]:
        raise AcquisitionError(f"HTTP {response.status_code} from {url}")
    return response.content


def _lower(props: dict[str, Any]) -> dict[str, Any]:
    return {k.lower(): v for k, v in props.items()}


def _gnis(value: Any) -> str | None:
    """NHD zero-pads GNIS ids ('01609456'); GNIS does not ('1609456'). Compare the numbers."""
    text = str(value or "").strip()
    return str(int(text)) if text.isdigit() else (text or None)


def acquire(config: dict[str, Any], src_dir: Path | None) -> dict[str, Any]:
    live = {s["source_key"]: s for s in config["live_sources"]}
    raw: dict[str, Any] = {"manifest": []}

    def record(key: str, url: str, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        raw["manifest"].append({"source_key": key, "url": url, "byte_sha256": digest, "bytes": len(payload),
                                "pin_matches": None})
        return digest

    def pages(key: str, dirname: str) -> list[tuple[dict[str, Any], str]]:
        out = []
        if src_dir:
            for path in sorted((src_dir / dirname).glob("page_*.json")):
                payload = path.read_bytes()
                out.append((json.loads(payload), record(key, live[key]["url"], payload)))
        else:
            offset = 0
            while True:
                url = f"{live[key]['url']}&resultOffset={offset}&resultRecordCount={PAGE}"
                payload = _get(url)
                page = json.loads(payload)
                out.append((page, record(key, url, payload)))
                if not page.get("features"):
                    break
                offset += PAGE
        if not sum(len(p.get("features", [])) for p, _ in out):
            raise AcquisitionError(f"{key}: no features returned")
        return out

    raw["flowlines"] = pages("usgs_nhd_flowlines", "nhd_flow")
    raw["waterbodies"] = pages("usgs_nhd_waterbodies", "nhd_wb")
    wbd = live["usgs_wbd"]
    raw["wbd"] = {}
    for level, layer in wbd["layers"].items():
        url = (f"{wbd['url']}{layer}/query?where=1%3D1&geometry=-68.0%2C17.8%2C-65.2%2C18.6&geometryType="
               "esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects&outSR=4326&outFields=*&f=geojson")
        payload = (src_dir / "wbd" / f"{level}.json").read_bytes() if src_dir else _get(url)
        raw["wbd"][level] = (json.loads(payload), record("usgs_wbd", url, payload))
    url = live["epa_sdwis_intakes"]["url"]
    payload = (src_dir / "sdwis_in.json").read_bytes() if src_dir else _get(url)
    raw["intakes"] = (json.loads(payload), record("epa_sdwis_intakes", url, payload))
    return raw


def _repo_file(data_dir: Path, name: str) -> tuple[list[dict[str, Any]], str]:
    path = data_dir / name
    payload = path.read_bytes() if path.is_file() else b""
    rows = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
    return rows, hashlib.sha256(payload).hexdigest()


# ── claims ────────────────────────────────────────────────────────────────────
def flowline_claims(raw: dict[str, Any], source: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims, excluded, seen = [], {}, set()
    total = 0
    for page, digest in raw["flowlines"]:
        for f in page.get("features", []):
            p = _lower(f["properties"])
            pid = str(p.get("permanent_identifier") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            total += 1
            ftype = str(p.get("ftype"))
            reason = source["excluded_ftypes"].get(ftype)
            coords = (f.get("geometry") or {}).get("coordinates") or []
            mid = coords[len(coords) // 2] if coords and isinstance(coords[0], list) and not isinstance(coords[0][0], list) else None
            claims.append(hi.claim(
                source_key="usgs_nhd_flowlines", authority="USGS_NHD",
                feature_type="canal" if ftype in CANAL_FTYPES else "stream", source_feature_id=pid,
                name_raw=p.get("gnis_name"), evidence_tier="T1", manifestation_sha256=digest, retrieved_utc=now,
                lat=mid[1] if mid else None, lon=mid[0] if mid else None,
                attributes={"gnis_id": _gnis(p.get("gnis_id")), "reachcode": p.get("reachcode"),
                            "huc8": str(p.get("reachcode") or "")[:8] or None, "ftype": ftype,
                            "flow_type": source["ftype"].get(ftype, ftype), "fcode": p.get("fcode"),
                            "lengthkm": round(float(p["lengthkm"]), 3) if p.get("lengthkm") is not None else None,
                            "innetwork": p.get("innetwork")},
                disposition="EXCLUDED" if reason else "RETAINED", exclusion_reason=reason))
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
    ledger = hi.close_ledger(source_rows=total, retained=total - sum(excluded.values()), excluded=excluded, unresolved=0)
    return claims, ledger


def waterbody_claims(raw: dict[str, Any], source: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], list[Any]]:
    from shapely.geometry import shape

    claims, geoms, seen = [], [], set()
    for page, digest in raw["waterbodies"]:
        for f in page.get("features", []):
            p = _lower(f["properties"])
            pid = str(p.get("permanent_identifier") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            ftype = str(p.get("ftype"))
            kind = "reservoir" if ftype in source["reservoir_ftypes"] else "waterbody"
            geom = shape(f["geometry"])
            point = geom.representative_point()
            claims.append(hi.claim(
                source_key="usgs_nhd_waterbodies", authority="USGS_NHD", feature_type=kind, source_feature_id=pid,
                name_raw=p.get("gnis_name"), evidence_tier="T1", manifestation_sha256=digest, retrieved_utc=now,
                lat=point.y, lon=point.x,
                attributes={"gnis_id": _gnis(p.get("gnis_id")), "ftype": ftype,
                            "water_type": source["ftype"].get(ftype, ftype), "areasqkm": p.get("areasqkm"),
                            "reachcode": p.get("reachcode")}))
            geoms.append((pid, kind, p.get("gnis_name"), geom))
    return claims, geoms


def watershed_claims(raw: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], list[Any]]:
    from shapely.geometry import shape

    claims, geoms = [], []
    for level, (doc, digest) in raw["wbd"].items():
        for f in doc.get("features", []):
            p = _lower(f["properties"])
            code = str(p.get(level) or "")
            if not code.startswith("2101"):
                continue
            geom = shape(f["geometry"])
            point = geom.representative_point()
            claims.append(hi.claim(
                source_key="usgs_wbd", authority="USGS_WBD", feature_type="watershed", source_feature_id=f"{level.upper()}:{code}",
                name_raw=p.get("name"), evidence_tier="T1", manifestation_sha256=digest, retrieved_utc=now,
                lat=point.y, lon=point.x, attributes={"level": level, "huc": code, "areasqkm": p.get("areasqkm")}))
            geoms.append((f"{level.upper()}:{code}", level, p.get("name"), geom))
    return claims, geoms


def intake_claims(raw: dict[str, Any], now: str) -> list[dict[str, Any]]:
    rows, digest = raw["intakes"]
    if not isinstance(rows, list) or not rows:
        raise AcquisitionError("SDWIS returned no intake facilities")
    out = []
    for r in rows:
        if r.get("facility_type_code") != "IN":
            raise AcquisitionError(f"SDWIS row {r.get('facility_id')} is not an intake")
        out.append(hi.claim(
            source_key="epa_sdwis_intakes", authority="EPA_SDWIS", feature_type="intake",
            source_feature_id=f"{r['pwsid']}:{r['facility_id']}", name_raw=r.get("facility_name"), evidence_tier="T2",
            manifestation_sha256=digest, retrieved_utc=now,
            attributes={"pwsid": r["pwsid"], "facility_activity_code": r.get("facility_activity_code"),
                        "water_type_code": r.get("water_type_code"), "availability_code": r.get("availability_code"),
                        "location": "not published by SDWIS"}))
    return out


def nwps_claims(data_dir: Path, now: str) -> list[dict[str, Any]]:
    rows, digest = _repo_file(data_dir, "nwps_gauge_state.jsonl")
    return [hi.claim(
        source_key="noaa_nwps_gauges", authority="NOAA_NWS", feature_type="gauge", source_feature_id=str(r["lid"]),
        name_raw=r.get("name"), evidence_tier="T1", manifestation_sha256=digest, retrieved_utc=now,
        lat=r.get("latitude"), lon=r.get("longitude"),
        attributes={"usgs_site_no": r.get("usgs_id"), "municipio": r.get("municipio"), "in_service": r.get("in_service")})
        for r in rows if r.get("lid")]


def repo_asset_claims(data_dir: Path, now: str) -> list[dict[str, Any]]:
    rows, digest = _repo_file(data_dir, "utility_assets.jsonl")
    out = []
    for r in rows:
        asset = str(r.get("asset_id", ""))
        if asset.startswith("RSV_"):
            kind = "reservoir"
        elif r.get("asset_subtype") == "intake_outfall":
            kind = "intake"
        else:
            continue
        out.append(hi.claim(
            source_key="repo_utility_assets", authority=str(r.get("source_ref") or "REPO")[:60], feature_type=kind,
            source_feature_id=asset, name_raw=r.get("asset_name"), evidence_tier=str(r.get("evidence_tier") or "T3"),
            manifestation_sha256=digest, retrieved_utc=now, lat=r.get("lat"), lon=r.get("lon"),
            attributes={"asset_subtype": r.get("asset_subtype"), "municipality": r.get("municipality"),
                        "review_status": r.get("review_status")}))
    return out


# ── geometry ──────────────────────────────────────────────────────────────────
def _write_geo(path: Path, features: list[dict[str, Any]], note: str) -> int:
    from shapely.geometry import mapping

    def rnd(obj: Any) -> Any:
        if isinstance(obj, float):
            return round(obj, DECIMALS)
        if isinstance(obj, (list, tuple)):
            return [rnd(o) for o in obj]
        return obj

    out = []
    for props, geom in features:
        g = mapping(geom.simplify(SIMPLIFY_DEG, preserve_topology=True))
        out.append({"type": "Feature", "properties": props, "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])}})
    text = json.dumps({"type": "FeatureCollection", "_source": note, "features": out}, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False) + "\n"
    if len(text.encode()) > GEO_FILE_BUDGET_BYTES:
        raise ValueError(f"{path.name} would be {len(text.encode())} bytes, over the {GEO_FILE_BUDGET_BYTES}-byte budget")
    hi.atomic_write(path, text)
    return len(text.encode())


def write_geometry(raw: dict[str, Any], flow_claims: list[dict[str, Any]], wb_geoms: list[Any], ws_geoms: list[Any],
                   data_dir: Path) -> dict[str, int]:
    from shapely.geometry import shape

    retained = {c["source_feature_id"]: c for c in flow_claims if c["disposition"] == "RETAINED"}
    by_huc8: dict[str, list[Any]] = {}
    for page, _ in raw["flowlines"]:
        for f in page.get("features", []):
            pid = str(_lower(f["properties"]).get("permanent_identifier") or "")
            c = retained.get(pid)
            if c is None or not f.get("geometry"):
                continue
            a = c["attributes"]
            by_huc8.setdefault(a.get("huc8") or "unknown", []).append(
                ({"id": pid, "name": c["name_raw"], "flow_type": a["flow_type"]}, shape(f["geometry"])))
    sizes = {}
    stream_dir = data_dir / "geo" / "streams"
    for huc8, feats in sorted(by_huc8.items()):
        sizes[f"streams/{huc8}.geojson"] = _write_geo(stream_dir / f"{huc8}.geojson", feats,
                                                      f"USGS NHD large-scale flowlines, HUC8 {huc8}; simplified {SIMPLIFY_DEG} deg")
    sizes["pr_waterbodies.geojson"] = _write_geo(
        data_dir / "geo" / "pr_waterbodies.geojson",
        [({"id": pid, "kind": kind, "name": name}, g) for pid, kind, name, g in wb_geoms],
        f"USGS NHD large-scale waterbodies; simplified {SIMPLIFY_DEG} deg")
    sizes["pr_watersheds.geojson"] = _write_geo(
        data_dir / "geo" / "pr_watersheds.geojson",
        [({"id": wid, "level": level, "name": name}, g) for wid, level, name, g in ws_geoms],
        f"USGS WBD HUC8 and HUC10; simplified {SIMPLIFY_DEG} deg")
    return sizes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-dir", type=Path)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--now")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.fetch and not args.src_dir:
        print("ingest_hydro_nhd: pass --fetch or --src-dir", file=sys.stderr)
        return 2
    now = _iso(datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc))
    config = json.loads((args.config_dir / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    live = {s["source_key"]: s for s in config["live_sources"]}
    hydro = args.data_dir / hi.HYDRO_DIR
    receipt_path = hydro / "ingest_surface_receipt.json"
    try:
        raw = acquire(config, None if args.fetch else args.src_dir)
        flows, flow_ledger = flowline_claims(raw, live["usgs_nhd_flowlines"], now)
        waters, wb_geoms = waterbody_claims(raw, live["usgs_nhd_waterbodies"], now)
        sheds, ws_geoms = watershed_claims(raw, now)
        intakes = intake_claims(raw, now)
        gauges = nwps_claims(args.data_dir, now)
        assets = repo_asset_claims(args.data_dir, now)
        sizes = {} if args.dry_run else write_geometry(raw, flows, wb_geoms, ws_geoms, args.data_dir)
    except Exception as exc:  # noqa: BLE001 - every failure leaves a FAIL receipt
        print(f"ingest_hydro_nhd: FAIL — {exc}", file=sys.stderr)
        if not args.dry_run:
            hi.write_fail_receipt(receipt_path, "surface", now, str(exc))
        return 1
    summary = {"stage": "surface", "status": "PASS", "run_utc": now, "manifestations": raw["manifest"],
               "ledgers": {"usgs_nhd_flowlines": flow_ledger, "usgs_nhd_waterbodies": {"rows": len(waters)},
                           "usgs_wbd": {"rows": len(sheds)}, "epa_sdwis_intakes": {"rows": len(intakes)},
                           "noaa_nwps_gauges": {"rows": len(gauges)}, "repo_utility_assets": {"rows": len(assets)}},
               "geometry_bytes": sizes, "geometry_budget_bytes": GEO_FILE_BUDGET_BYTES,
               "simplification": {"tolerance_deg": SIMPLIFY_DEG, "decimals": DECIMALS}}
    if args.dry_run:
        print(json.dumps(summary["ledgers"], indent=2))
        return 0
    for name, rows in (("claims_nhd_flowlines.jsonl", flows), ("claims_nhd_waterbodies.jsonl", waters),
                       ("claims_wbd.jsonl", sheds), ("claims_sdwis_intakes.jsonl", intakes),
                       ("claims_nwps_gauges.jsonl", gauges), ("claims_repo_assets.jsonl", assets)):
        hi.write_claims(hydro / name, rows)
    hi.atomic_write(receipt_path, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"ingest_hydro_nhd: PASS — {flow_ledger['retained']} reaches, {len(waters)} waterbodies, {len(sheds)} watersheds, "
          f"{len(intakes)} SDWIS intakes, {len(gauges)} NWPS gauges, {len(assets)} repo assets; largest geometry file "
          f"{max(sizes.values()) if sizes else 0} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
