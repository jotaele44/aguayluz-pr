#!/usr/bin/env python3
"""Site claims (wells and every other USGS site type) for the Puerto Rico hydrologic inventory.

Sources (``config/hydro_inventory_sources.v1.json``), all live, every page hashed:

  * USGS Water Data API ``monitoring-locations`` for state 72, every site type
  * USGS NWIS site service (groundwater): a cross-check that the two USGS services list the
    same wells with the same aquifer codes. It adds no claims; a disagreement fails the run.
  * Water Quality Portal stations of type Well (USGS and Puerto Rico EQB) and of type Spring
  * EPA SDWIS well facilities (``WL``) and water systems, which carry no coordinates

Outputs, committed:

  * ``data/hydro/claims_usgs_sites.jsonl``    every USGS monitoring location (later phases use the
    other site types)
  * ``data/hydro/claims_wqp_wells.jsonl``
  * ``data/hydro/claims_wqp_springs.jsonl``
  * ``data/hydro/claims_sdwis_wells.jsonl``
  * ``data/hydro/ingest_sites_receipt.json``

    python scripts/ingest_hydro_sites.py --src-dir /path/to/raw
    python scripts/ingest_hydro_sites.py --fetch
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
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

RAW_NAMES = {
    "usgs_monitoring_locations": "ml",
    "usgs_nwis_site_gw": "nwis_gw.rdb",
    "wqp_wells": "wqp_wells.csv",
    "epa_sdwis_wells": "sdwis_wl.json",
    "epa_sdwis_systems": "sdwis_ws.json",
    "wqp_springs": "wqp_springs.csv",
}
USGS_KEEP = ("site_type_code", "county_name", "hydrologic_unit_code", "aquifer_code", "national_aquifer_code",
             "aquifer_type_code", "well_constructed_depth", "hole_constructed_depth", "altitude", "vertical_datum",
             "original_horizontal_datum", "horizontal_positional_accuracy_code", "construction_date",
             "drainage_area")
#: Minimum plausible count of Puerto Rico USGS groundwater sites; far fewer means a truncated feed.
MIN_USGS_GW_SITES = 5000


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
    if response.status_code != 200:
        raise AcquisitionError(f"HTTP {response.status_code} from {url}")
    return response.content


def acquire(config: dict[str, Any], src_dir: Path | None) -> dict[str, Any]:
    live = {s["source_key"]: s for s in config["live_sources"]}
    raw: dict[str, Any] = {"manifest": [], "sha": {}}

    def record(key: str, url: str, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        raw["manifest"].append({"source_key": key, "url": url, "byte_sha256": digest, "bytes": len(payload),
                                "pin_matches": None})
        raw["sha"].setdefault(key, digest)
        return digest

    pages = []
    if src_dir:
        for path in sorted((src_dir / RAW_NAMES["usgs_monitoring_locations"]).glob("page_*.json")):
            payload = path.read_bytes()
            record("usgs_monitoring_locations", live["usgs_monitoring_locations"]["url"], payload)
            pages.append((json.loads(payload), hashlib.sha256(payload).hexdigest()))
    else:
        url: str | None = live["usgs_monitoring_locations"]["url"]
        while url:
            payload = _get(url)
            digest = record("usgs_monitoring_locations", url, payload)
            page = json.loads(payload)
            pages.append((page, digest))
            nxt = [link["href"] for link in page.get("links", []) if link.get("rel") == "next"]
            url = nxt[0] if nxt and page.get("features") else None
    raw["ml_pages"] = pages
    for key in ("usgs_nwis_site_gw", "wqp_wells", "wqp_springs", "epa_sdwis_wells", "epa_sdwis_systems"):
        url = live[key]["url"]
        payload = (src_dir / RAW_NAMES[key]).read_bytes() if src_dir else _get(url)
        if not payload.strip():
            raise AcquisitionError(f"{key}: empty response")
        record(key, url, payload)
        raw[key] = payload
    return raw


def _feature_type(site_type: str) -> str:
    """USGS site type to inventory feature type. Every other monitoring location is a gauge."""
    if site_type.startswith("GW"):
        return "well"
    if site_type == "SP":
        return "spring"
    return "gauge"


def parse_rdb(payload: bytes) -> list[dict[str, str]]:
    lines = [ln for ln in payload.decode("utf-8", "replace").splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        raise AcquisitionError("NWIS response has no header")
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"), strict=False)) for ln in lines[2:]]


def usgs_claims(raw: dict[str, Any], now: str, min_gw_sites: int = MIN_USGS_GW_SITES
                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims, seen = [], set()
    for page, digest in raw["ml_pages"]:
        for f in page.get("features", []):
            p = f["properties"]
            site = str(p.get("monitoring_location_number") or "")
            if not site or site in seen:
                continue
            seen.add(site)
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            lon, lat = coords[0], coords[1]
            in_pr = lon is not None and hi.PR_BOUNDS[0] <= lon <= hi.PR_BOUNDS[2] and hi.PR_BOUNDS[1] <= lat <= hi.PR_BOUNDS[3]
            claims.append(hi.claim(
                source_key="usgs_monitoring_locations", authority="USGS",
                feature_type=_feature_type(str(p.get("site_type_code") or "")),
                source_feature_id=site, name_raw=p.get("monitoring_location_name"), evidence_tier="T1",
                manifestation_sha256=digest, retrieved_utc=now, lat=lat if in_pr else None, lon=lon if in_pr else None,
                attributes={k: p.get(k) for k in USGS_KEEP} | ({"coordinates_outside_pr_bounds": [lon, lat]} if lon is not None and not in_pr else {})))
    gw = [c for c in claims if c["attributes"].get("site_type_code") in hi.GW_SITE_TYPES]
    if len(gw) < min_gw_sites:
        raise AcquisitionError(f"only {len(gw)} USGS groundwater sites returned; expected at least {min_gw_sites}")
    legacy = parse_rdb(raw["usgs_nwis_site_gw"])
    api = {c["source_feature_id"]: c for c in gw}
    legacy_sites = {r["site_no"]: r for r in legacy}
    only_legacy = sorted(set(legacy_sites) - set(api))
    only_api = sorted(set(api) - set(legacy_sites))
    code_disagree = sorted(s for s in set(api) & set(legacy_sites)
                           if (legacy_sites[s].get("aqfr_cd") or None) != (api[s]["attributes"].get("aquifer_code") or None))
    if only_legacy or only_api or code_disagree:
        raise AcquisitionError(f"USGS services disagree: {len(only_legacy)} legacy-only, {len(only_api)} API-only, "
                               f"{len(code_disagree)} aquifer-code differences (e.g. {(only_legacy + only_api + code_disagree)[:5]})")
    by_type: dict[str, int] = {}
    for c in claims:
        t = c["attributes"].get("site_type_code") or "none"
        by_type[t] = by_type.get(t, 0) + 1
    return claims, {"sites": len(claims), "by_site_type": dict(sorted(by_type.items())),
                    "cross_check": {"legacy_groundwater_sites": len(legacy), "api_groundwater_sites": len(gw),
                                    "only_legacy": 0, "only_api": 0, "aquifer_code_differences": 0,
                                    "note": "The legacy service's siteType=GW includes the GW-TH, GW-MW and GW-CR "
                                            "subtypes, which the API lists separately; that is why 5,437 and 5,197 "
                                            "both appear in earlier notes."}}


def wqp_claims(raw: dict[str, Any], now: str, key: str = "wqp_wells", feature_type: str = "well") -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(raw[key].decode("utf-8", "replace"))))
    if not rows or "MonitoringLocationIdentifier" not in rows[0]:
        raise AcquisitionError("WQP response is not a station table")
    out = []
    for r in rows:
        mid = r["MonitoringLocationIdentifier"]
        try:
            lat, lon = float(r["LatitudeMeasure"]), float(r["LongitudeMeasure"])
        except ValueError:
            lat = lon = None
        in_pr = lat is not None and hi.PR_BOUNDS[0] <= lon <= hi.PR_BOUNDS[2] and hi.PR_BOUNDS[1] <= lat <= hi.PR_BOUNDS[3]
        usgs_site = mid[5:] if mid.startswith("USGS-") else None
        excluded = None
        if r.get("OrganizationIdentifier", "").upper().startswith("DEMOTEST"):
            excluded = "test data published under a demonstration organisation"
        out.append(hi.claim(
            source_key=key, authority="WQP:" + r.get("OrganizationIdentifier", ""), feature_type=feature_type,
            source_feature_id=mid, name_raw=r.get("MonitoringLocationName"), evidence_tier="T2",
            manifestation_sha256=raw["sha"][key], retrieved_utc=now,
            lat=lat if in_pr else None, lon=lon if in_pr else None,
            attributes={"organization": r.get("OrganizationIdentifier"), "usgs_site_no": usgs_site,
                        "datum": r.get("HorizontalCoordinateReferenceSystemDatumName"),
                        "huc8": r.get("HUCEightDigitCode"), "county_code": r.get("CountyCode"),
                        "well_depth": r.get("WellDepthMeasure/MeasureValue"), "aquifer_name": r.get("AquiferName"),
                        "local_aquifer_name": r.get("LocalAqfrName")},
            disposition="EXCLUDED" if excluded else "RETAINED", exclusion_reason=excluded))
    return out


def sdwis_claims(raw: dict[str, Any], now: str) -> list[dict[str, Any]]:
    wells = json.loads(raw["epa_sdwis_wells"])
    systems = {s["pwsid"]: s for s in json.loads(raw["epa_sdwis_systems"])}
    if not isinstance(wells, list) or not wells:
        raise AcquisitionError("SDWIS returned no well facilities")
    out = []
    for w in wells:
        if w.get("facility_type_code") != "WL":
            raise AcquisitionError(f"SDWIS row {w.get('facility_id')} is not a well facility")
        system = systems.get(w["pwsid"], {})
        out.append(hi.claim(
            source_key="epa_sdwis_wells", authority="EPA_SDWIS", feature_type="well",
            source_feature_id=f"{w['pwsid']}:{w['facility_id']}", name_raw=w.get("facility_name"), evidence_tier="T2",
            manifestation_sha256=raw["sha"]["epa_sdwis_wells"], retrieved_utc=now,
            attributes={"pwsid": w["pwsid"], "facility_id": w["facility_id"], "state_facility_id": w.get("state_facility_id"),
                        "facility_activity_code": w.get("facility_activity_code"),
                        "facility_deactivation_date": (w.get("facility_deactivation_date") or "")[:10] or None,
                        "availability_code": w.get("availability_code"), "water_type_code": w.get("water_type_code"),
                        "system_name": system.get("pws_name"), "system_city": system.get("city_name"),
                        "system_owner_type": system.get("owner_type_code"), "system_type": system.get("pws_type_code"),
                        "location": "not published by SDWIS"}))
    return out


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-dir", type=Path)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--now")
    ap.add_argument("--min-gw-sites", type=int, default=MIN_USGS_GW_SITES,
                    help="fail when fewer USGS groundwater sites come back (a truncated feed)")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.fetch and not args.src_dir:
        print("ingest_hydro_sites: pass --fetch or --src-dir", file=sys.stderr)
        return 2
    now = _iso(datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc))
    config = json.loads((args.config_dir / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    hydro = args.data_dir / hi.HYDRO_DIR
    receipt_path = hydro / "ingest_sites_receipt.json"
    try:
        raw = acquire(config, None if args.fetch else args.src_dir)
        usgs, usgs_ledger = usgs_claims(raw, now, args.min_gw_sites)
        wqp = wqp_claims(raw, now)
        wqp_springs = wqp_claims(raw, now, "wqp_springs", "spring")
        sdwis = sdwis_claims(raw, now)
    except Exception as exc:  # noqa: BLE001 - every failure leaves a FAIL receipt
        print(f"ingest_hydro_sites: FAIL — {exc}", file=sys.stderr)
        if not args.dry_run:
            hi.write_fail_receipt(receipt_path, "sites", now, str(exc))
        return 1
    summary = {"stage": "sites", "status": "PASS", "run_utc": now, "manifestations": raw["manifest"],
               "ledgers": {"usgs_monitoring_locations": usgs_ledger,
                           "wqp_wells": {"rows": len(wqp), "usgs_rows": sum(1 for c in wqp if c["attributes"].get("usgs_site_no")),
                                         "other_rows": sum(1 for c in wqp if not c["attributes"].get("usgs_site_no"))},
                           "wqp_springs": {"rows": len(wqp_springs),
                                           "usgs_rows": sum(1 for c in wqp_springs if c["attributes"].get("usgs_site_no"))},
                           "epa_sdwis_wells": {"rows": len(sdwis),
                                               "active": sum(1 for c in sdwis if c["attributes"].get("facility_activity_code") == "A"),
                                               "inactive": sum(1 for c in sdwis if c["attributes"].get("facility_activity_code") == "I")}}}
    if args.dry_run:
        print(json.dumps(summary["ledgers"], indent=2))
        return 0
    hi.write_claims(hydro / "claims_usgs_sites.jsonl", usgs)
    hi.write_claims(hydro / "claims_wqp_wells.jsonl", wqp)
    hi.write_claims(hydro / "claims_wqp_springs.jsonl", wqp_springs)
    hi.write_claims(hydro / "claims_sdwis_wells.jsonl", sdwis)
    hi.atomic_write(receipt_path, json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    print(f"ingest_hydro_sites: PASS — {len(usgs)} USGS sites, {len(wqp)} WQP wells, {len(sdwis)} SDWIS wells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
