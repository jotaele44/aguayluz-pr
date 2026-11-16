#!/usr/bin/env python3
"""Wetland and pond claims for the Puerto Rico hydrologic inventory, from the USFWS National
Wetlands Inventory (NWI).

Every NWI polygon in the Puerto Rico envelope becomes a claim keyed by its NWI GlobalID:

  * estuarine/marine, freshwater emergent and freshwater forested/shrub wetlands become
    ``wetland`` claims;
  * freshwater ponds and lakes become ``waterbody`` claims (the build lists each one that sits
    inside an NHD waterbody polygon as a candidate, never a merge);
  * riverine polygons (represented by the NHD reaches), estuarine and marine deepwater (open
    water) and polygons outside the Puerto Rico watersheds (the U.S. Virgin Islands, open sea)
    are excluded by reason.

The mapping vintage is old (largely 1980s imagery); the receipt and the page say so.
Retained polygons are simplified and written one file per HUC8 to ``data/geo/wetlands/``,
each under the 2 MB geometry budget. Claims: ``data/hydro/claims_nwi.jsonl``; receipt
``data/hydro/ingest_wetlands_receipt.json``. Needs shapely (the ``[geo]`` extra).

    python scripts/ingest_hydro_wetlands.py --fetch [--save-raw DIR]
    python scripts/ingest_hydro_wetlands.py --src-dir DIR      # reads DIR/nwi/page_*.json
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
PAGE = 500
SMALLEST_PAGE = 4
OUTSIDE = "outside the Puerto Rico watersheds (U.S. Virgin Islands or open sea)"


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


def acquire(source: dict[str, Any], src_dir: Path | None, save_raw: Path | None) -> dict[str, Any]:
    raw: dict[str, Any] = {"manifest": [], "pages": []}

    def record(url: str, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        raw["manifest"].append({"source_key": "usfws_nwi", "url": url, "byte_sha256": digest, "bytes": len(payload),
                                "pin_matches": None})
        return digest

    if src_dir:
        for path in sorted((src_dir / "nwi").glob("page_*.json")):
            payload = path.read_bytes()
            raw["pages"].append((json.loads(payload), record(source["url"], payload)))
    else:
        def fetch(offset: int, count: int) -> int:
            """Fetch one page; a page the server cannot render (HTTP 500) is split into smaller ones."""
            url = f"{source['url']}&resultOffset={offset}&resultRecordCount={count}"
            try:
                payload = _get(url)
            except AcquisitionError:
                if count <= SMALLEST_PAGE:
                    raise
                step = max(SMALLEST_PAGE, count // 5)
                return sum(fetch(o, min(step, offset + count - o)) for o in range(offset, offset + count, step))
            page = json.loads(payload)
            n = len(page.get("features") or [])
            if n:
                if save_raw:
                    (save_raw / "nwi").mkdir(parents=True, exist_ok=True)
                    (save_raw / "nwi" / f"page_{offset:06d}.json").write_bytes(payload)
                raw["pages"].append((page, record(url, payload)))
            return n

        offset = 0
        while fetch(offset, PAGE):
            offset += PAGE
    if not sum(len(p.get("features", [])) for p, _ in raw["pages"]):
        raise AcquisitionError("NWI returned no polygons")
    return raw


def nwi_claims(raw: dict[str, Any], source: dict[str, Any], huc8_index: hi.PolygonIndex, now: str
               ) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], Any]], dict[str, Any]]:
    from shapely.geometry import shape

    type_map, excluded_types = source["type_map"], source["excluded_types"]
    claims, geoms, excluded, seen = [], [], {}, set()
    total = 0
    for page, digest in raw["pages"]:
        for f in page.get("features", []):
            p = f.get("properties") or {}
            gid = str(p.get("GlobalID") or "").strip("{}")
            if not gid:
                raise AcquisitionError(f"NWI OBJECTID {p.get('OBJECTID')} has no GlobalID")
            if gid in seen:
                continue
            seen.add(gid)
            total += 1
            wtype = str(p.get("WETLAND_TYPE") or "NA")
            if not f.get("geometry"):
                raise AcquisitionError(f"NWI {gid} has no geometry")
            geom = shape(f["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            point = geom.representative_point()
            hits = huc8_index.containing(point.x, point.y)
            huc8 = str(hits[0].get("id", "")).split(":", 1)[-1] if hits else None
            if wtype in excluded_types:
                reason = excluded_types[wtype]
            elif wtype not in type_map:
                raise AcquisitionError(f"NWI wetland type {wtype!r} is not in the configured map")
            elif huc8 is None:
                reason = OUTSIDE
            else:
                reason = None
            kind = type_map.get(wtype, "wetland")
            claims.append(hi.claim(
                source_key="usfws_nwi", authority="USFWS_NWI", feature_type=kind, source_feature_id=gid, name_raw=None,
                evidence_tier=source["evidence_tier"], manifestation_sha256=digest, retrieved_utc=now,
                lat=point.y, lon=point.x,
                attributes={"wetland_type": wtype, "nwi_code": p.get("ATTRIBUTE"),
                            "acres": round(float(p["ACRES"]), 3) if p.get("ACRES") is not None else None, "huc8": huc8},
                disposition="EXCLUDED" if reason else "RETAINED", exclusion_reason=reason))
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
            else:
                geoms.append(({"id": gid, "kind": kind, "wetland_type": wtype, "code": p.get("ATTRIBUTE"), "huc8": huc8}, geom))
    if total < source["min_rows"]:
        raise AcquisitionError(f"NWI returned {total} polygons, fewer than {source['min_rows']}")
    ledger = hi.close_ledger(source_rows=total, retained=total - sum(excluded.values()), excluded=excluded, unresolved=0)
    return claims, geoms, ledger


def write_tiles(geoms: list[tuple[dict[str, Any], Any]], out_dir: Path) -> dict[str, int]:
    from shapely.geometry import mapping

    def rnd(obj: Any) -> Any:
        if isinstance(obj, float):
            return round(obj, DECIMALS)
        if isinstance(obj, (list, tuple)):
            return [rnd(o) for o in obj]
        return obj

    by_huc8: dict[str, list[dict[str, Any]]] = {}
    for props, geom in geoms:
        g = mapping(geom.simplify(SIMPLIFY_DEG, preserve_topology=True))
        by_huc8.setdefault(props["huc8"], []).append(
            {"type": "Feature", "properties": props, "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])}})
    texts = {}
    for huc8, feats in sorted(by_huc8.items()):
        text = json.dumps({"type": "FeatureCollection",
                           "_source": f"USFWS National Wetlands Inventory, HUC8 {huc8}; simplified {SIMPLIFY_DEG} deg",
                           "features": feats}, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        size = len(text.encode())
        if size > GEO_FILE_BUDGET_BYTES:
            raise ValueError(f"wetlands/{huc8}.geojson would be {size} bytes, over the {GEO_FILE_BUDGET_BYTES}-byte budget")
        texts[huc8] = text
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.geojson"):
        if stale.stem not in texts:
            stale.unlink()
    for huc8, text in texts.items():
        hi.atomic_write(out_dir / f"{huc8}.geojson", text)
    return {f"wetlands/{h}.geojson": len(t.encode()) for h, t in texts.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-dir", type=Path)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--save-raw", type=Path)
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--now")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.fetch and not args.src_dir:
        print("ingest_hydro_wetlands: pass --fetch or --src-dir", file=sys.stderr)
        return 2
    now = _iso(datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc))
    config = json.loads((args.config_dir / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    source = next(s for s in config["live_sources"] if s["source_key"] == "usfws_nwi")
    hydro = args.data_dir / hi.HYDRO_DIR
    receipt_path = hydro / "ingest_wetlands_receipt.json"
    try:
        sheds = json.loads((args.data_dir / "geo" / "pr_watersheds.geojson").read_text(encoding="utf-8"))
        huc8_index = hi.PolygonIndex(f for f in sheds["features"] if (f.get("properties") or {}).get("level") == "huc8")
        raw = acquire(source, None if args.fetch else args.src_dir, args.save_raw if args.fetch else None)
        claims, geoms, ledger = nwi_claims(raw, source, huc8_index, now)
        sizes = {} if args.dry_run else write_tiles(geoms, args.data_dir / "geo" / "wetlands")
    except Exception as exc:  # noqa: BLE001 - every failure leaves a FAIL receipt
        print(f"ingest_hydro_wetlands: FAIL — {exc}", file=sys.stderr)
        if not args.dry_run:
            hi.write_fail_receipt(receipt_path, "wetlands", now, str(exc))
        return 1
    by_kind: dict[str, int] = {}
    for c in claims:
        if c["disposition"] == "RETAINED":
            by_kind[c["feature_type"]] = by_kind.get(c["feature_type"], 0) + 1
    summary = {"stage": "wetlands", "status": "PASS", "run_utc": now, "manifestations": raw["manifest"],
               "ledgers": {"usfws_nwi": {**ledger, "retained_by_feature_type": by_kind}},
               "vintage": source["vintage"], "geometry_bytes": sizes, "geometry_budget_bytes": GEO_FILE_BUDGET_BYTES,
               "simplification": {"tolerance_deg": SIMPLIFY_DEG, "decimals": DECIMALS}}
    if args.dry_run:
        print(json.dumps(summary["ledgers"], indent=2, ensure_ascii=False))
        return 0
    hi.write_claims(hydro / "claims_nwi.jsonl", claims)
    hi.atomic_write(receipt_path, json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"ingest_hydro_wetlands: PASS — {ledger['retained']} of {ledger['source']} NWI polygons retained "
          f"({by_kind}); largest tile {max(sizes.values()) if sizes else 0} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
