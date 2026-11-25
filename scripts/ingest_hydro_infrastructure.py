#!/usr/bin/env python3
"""Water-infrastructure claims for the Puerto Rico hydrologic inventory: PRASA facilities, dams,
wastewater plants, drinking-water facilities and non-PRASA community systems.

Sources (``config/hydro_inventory_sources.v1.json``), all official:

  * PRASA's public ArcGIS layer ``PR_PRASA_Facilities`` (a May 2020 snapshot, T2): wells,
    intakes, filtration plants, wastewater plants, pump stations, tanks and reservoirs.
    Offices are excluded by reason; the pipe-network layers are not read.
  * USACE National Inventory of Dams, nation CSV, filtered to Puerto Rico (T1).
  * EPA ECHO Clean Water Act facilities in Puerto Rico; publicly owned treatment works
    are retained, every other NPDES permittee is counted and excluded by reason (T1).
  * EPA SDWIS facilities of type TP, SP and ST (treatment plants, springs, storage). SDWIS
    publishes no coordinates, so these are listed and never placed.
  * FEMA Region 2's layer of EPA non-PRASA sites (2017): one point per community water system,
    keyed by the system's federal PWSID.

Claims: ``data/hydro/claims_prasa_facilities.jsonl``, ``claims_nid_dams.jsonl``,
``claims_echo_potw.jsonl``, ``claims_sdwis_facilities.jsonl``, ``claims_fema_nonprasa.jsonl``;
receipt ``data/hydro/ingest_infrastructure_receipt.json``. Every source has a ledger that
closes: rows fetched = claims retained + rows excluded by reason.

    python scripts/ingest_hydro_infrastructure.py --fetch
    python scripts/ingest_hydro_infrastructure.py --src-dir /path/to/raw --now 2026-11-15T00:00:00Z

``--src-dir`` reads ``prasa/page_*.json``, ``nid_nation.csv``, ``echo/facilities.json`` plus
``echo/page_*.json``, ``sdwis_<code>.json`` and ``fema_nonprasa.json``; ``--save-raw DIR``
writes exactly that layout from a live fetch.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import CONFIG_DIR, DATA_DIR  # noqa: E402
from aguayluz import hydro_inventory as hi  # noqa: E402

PRASA_PAGE = 2000
#: PRASA publishes both a point geometry and Xcoord/Ycoord columns; they must agree.
COORD_AGREEMENT_M = 1.0


class AcquisitionError(RuntimeError):
    """A source did not return what we asked for."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _get(url: str) -> bytes:
    import httpx

    from aguayluz.http_retry import get_with_retry
    from aguayluz.hydromet import USER_AGENT

    with httpx.Client(timeout=600, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        response = get_with_retry(url, client=client)
    if response.status_code != 200 or b'"error"' in response.content[:200]:
        raise AcquisitionError(f"HTTP {response.status_code} from {url}")
    return response.content


def _text(value: Any) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text or None


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def acquire(config: dict[str, Any], src_dir: Path | None, save_raw: Path | None = None) -> dict[str, Any]:
    live = {s["source_key"]: s for s in config["live_sources"]}
    raw: dict[str, Any] = {"manifest": []}

    def record(key: str, url: str, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        raw["manifest"].append({"source_key": key, "url": url, "byte_sha256": digest, "bytes": len(payload),
                                "pin_matches": None})
        return digest

    def read(rel: str, url: str) -> bytes:
        if src_dir:
            return (src_dir / rel).read_bytes()
        payload = _get(url)
        if save_raw:
            (save_raw / rel).parent.mkdir(parents=True, exist_ok=True)
            (save_raw / rel).write_bytes(payload)
        return payload

    # PRASA facilities, paged
    prasa = live["prasa_facilities"]
    raw["prasa"] = []
    if src_dir:
        for path in sorted((src_dir / "prasa").glob("page_*.json")):
            payload = path.read_bytes()
            raw["prasa"].append((json.loads(payload), record("prasa_facilities", prasa["url"], payload)))
    else:
        offset = 0
        while True:
            url = f"{prasa['url']}&resultOffset={offset}&resultRecordCount={PRASA_PAGE}"
            payload = read(f"prasa/page_{offset // PRASA_PAGE:03d}.json", url)
            page = json.loads(payload)
            raw["prasa"].append((page, record("prasa_facilities", url, payload)))
            if not page.get("features") or not page.get("exceededTransferLimit"):
                break
            offset += PRASA_PAGE

    nid = live["usace_nid"]
    payload = read("nid_nation.csv", nid["url"])
    raw["nid"] = (payload, record("usace_nid", nid["url"], payload))

    echo = live["epa_echo_potw"]
    payload = read("echo/facilities.json", echo["url"])
    record("epa_echo_potw", echo["url"], payload)
    results = json.loads(payload).get("Results") or {}
    qid, rows = results.get("QueryID"), int(results.get("QueryRows") or 0)
    raw["echo"] = {"query_rows": rows, "pages": []}
    if src_dir:
        for path in sorted((src_dir / "echo").glob("page_*.json")):
            payload = path.read_bytes()
            raw["echo"]["pages"].append((json.loads(payload), record("epa_echo_potw", echo["qid_url"], payload)))
    else:
        if not qid:
            raise AcquisitionError("ECHO returned no QueryID")
        page_no = 1
        while True:
            url = f"{echo['qid_url']}&qid={qid}&pageno={page_no}"
            payload = read(f"echo/page_{page_no:03d}.json", url)
            page = json.loads(payload)
            facilities = (page.get("Results") or {}).get("Facilities") or []
            if not facilities:
                break
            raw["echo"]["pages"].append((page, record("epa_echo_potw", url, payload)))
            page_no += 1

    sdwis = live["epa_sdwis_facilities"]
    raw["sdwis"] = {}
    for code in sdwis["type_map"]:
        url = sdwis["url"].format(code=code)
        payload = read(f"sdwis_{code}.json", url)
        raw["sdwis"][code] = (json.loads(payload), record("epa_sdwis_facilities", url, payload))

    fema = live["fema_nonprasa_sites"]
    payload = read("fema_nonprasa.json", fema["url"])
    raw["fema"] = (json.loads(payload), record("fema_nonprasa_sites", fema["url"], payload))
    return raw


# ── claims ────────────────────────────────────────────────────────────────────
def prasa_claims(raw: dict[str, Any], source: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims, excluded, seen = [], {}, set()
    total = 0
    tipo_map, excluded_tipos = source["tipo_map"], source["excluded_tipos"]
    for page, digest in raw["prasa"]:
        if "features" not in page:
            raise AcquisitionError("PRASA page without features")
        for f in page["features"]:
            a = f.get("attributes") or {}
            fid = _text(a.get("Identificación_de_facilidad"))
            if not fid:
                raise AcquisitionError(f"PRASA OBJECTID {a.get('OBJECTID')} has no facility id")
            if fid in seen:
                raise AcquisitionError(f"PRASA facility id {fid} appears twice")
            seen.add(fid)
            total += 1
            tipo = _text(a.get("Tipo")) or ""
            if tipo in excluded_tipos:
                reason = excluded_tipos[tipo]
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            kind = tipo_map.get(tipo)
            if kind is None:
                raise AcquisitionError(f"PRASA Tipo {tipo!r} is not in the configured map")
            g = f.get("geometry") or {}
            lon, lat = _float(g.get("x")), _float(g.get("y"))
            x, y = _float(a.get("Xcoord")), _float(a.get("Ycoord"))
            if lat is not None and x is not None and y is not None \
                    and hi.haversine_m(lat, lon, y, x) > COORD_AGREEMENT_M:
                raise AcquisitionError(f"PRASA {fid}: geometry and Xcoord/Ycoord disagree")
            claims.append(hi.claim(
                source_key="prasa_facilities", authority="PRASA", feature_type=kind, source_feature_id=fid,
                name_raw=_text(a.get("Nombre")), evidence_tier=source["evidence_tier"], manifestation_sha256=digest,
                retrieved_utc=now, lat=lat, lon=lon,
                attributes={"tipo": tipo, "abrv": _text(a.get("ABRV")), "status": _text(a.get("Estatus")),
                            "water_kind": _text(a.get("Tipo_Agua")), "capacity": _float(a.get("Capacidad")),
                            "region": _text(a.get("Región")), "operational_area": _text(a.get("Area_Operacional")),
                            "municipio": _text(a.get("County")) or _text(a.get("Municipio"))}))
    if total < source["min_rows"]:
        raise AcquisitionError(f"PRASA returned {total} facilities, fewer than {source['min_rows']}")
    ledger = hi.close_ledger(source_rows=total, retained=len(claims), excluded=excluded, unresolved=0)
    return claims, ledger


def clean_nid_name(name: str | None) -> str | None:
    """The NID CSV double-encodes some non-breaking spaces ('Ana Mariaâ\\xa0V Dam'); read them as spaces."""
    if name is None:
        return None
    return " ".join(name.replace("â\xa0", " ").replace("Â\xa0", " ").replace("\xa0", " ").split()) or None


def nid_claims(raw: dict[str, Any], source: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload, digest = raw["nid"]
    lines = payload.decode("utf-8", errors="replace").splitlines()
    if lines and lines[0].startswith("Data Last Updated"):
        updated = lines[0].split(",", 1)[1].strip() if "," in lines[0] else None
        lines = lines[1:]
    else:
        updated = None
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if not reader.fieldnames or "NID ID" not in reader.fieldnames:
        raise AcquisitionError("NID CSV has no 'NID ID' column")
    claims, total_rows = [], 0
    for r in reader:
        total_rows += 1
        if r.get("State") != "Puerto Rico":
            continue
        nid_id = _text(r.get("NID ID"))
        if not nid_id:
            raise AcquisitionError("a Puerto Rico NID row has no NID ID")
        claims.append(hi.claim(
            source_key="usace_nid", authority="USACE_NID", feature_type="dam", source_feature_id=nid_id,
            name_raw=r.get("Dam Name"), evidence_tier=source["evidence_tier"], manifestation_sha256=digest,
            retrieved_utc=now, lat=_float(r.get("Latitude")), lon=_float(r.get("Longitude")),
            attributes={"name_clean": clean_nid_name(r.get("Dam Name")), "other_names": clean_nid_name(r.get("Other Names")),
                        "owner": _text(r.get("Owner Names")), "owner_type": _text(r.get("Primary Owner Type")),
                        "purpose": _text(r.get("Primary Purpose")), "purposes": _text(r.get("Purposes")),
                        "river": clean_nid_name(r.get("River or Stream Name")), "municipio": _text(r.get("County")),
                        "year_completed": _text(r.get("Year Completed")), "height_ft": _float(r.get("Dam Height (Ft)")),
                        "storage_acre_ft": _float(r.get("NID Storage (Acre-Ft)")),
                        "hazard": _text(r.get("Hazard Potential Classification")),
                        "associated_structure": _text(r.get("Is Associated Structure?")), "nid_data_updated": updated}))
    if len(claims) < source["min_rows"]:
        raise AcquisitionError(f"NID has {len(claims)} Puerto Rico dams, fewer than {source['min_rows']}")
    ledger = hi.close_ledger(source_rows=len(claims), retained=len(claims), excluded={}, unresolved=0)
    ledger["nation_rows_read"] = total_rows
    ledger["nid_data_updated"] = updated
    return claims, ledger


def echo_claims(raw: dict[str, Any], source: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims, seen, excluded = [], set(), {}
    for page, digest in raw["echo"]["pages"]:
        for r in (page.get("Results") or {}).get("Facilities") or []:
            sid = _text(r.get("SourceID"))
            if not sid or sid in seen:
                continue
            seen.add(sid)
            if r.get("CWPFacilityTypeIndicator") != source["retained_facility_type"]:
                excluded[source["excluded_reason"]] = excluded.get(source["excluded_reason"], 0) + 1
                continue
            claims.append(hi.claim(
                source_key="epa_echo_potw", authority="EPA_ECHO", feature_type="wastewater_plant", source_feature_id=sid,
                name_raw=_text(r.get("CWPName")), evidence_tier=source["evidence_tier"], manifestation_sha256=digest,
                retrieved_utc=now, lat=_float(r.get("FacLat")), lon=_float(r.get("FacLong")),
                attributes={"npdes_id": sid, "city": _text(r.get("CWPCity")), "sic_codes": _text(r.get("CWPSICCodes")),
                            "permit_status": _text(r.get("CWPPermitStatusDesc")), "permit_type": _text(r.get("CWPPermitTypeDesc")),
                            "major_minor": _text(r.get("CWPMajorMinorStatusFlag")),
                            "actual_average_flow_mgd": _float(r.get("CWPActualAverageFlowNmbr"))}))
    total = len(seen)
    if raw["echo"]["query_rows"] and total != raw["echo"]["query_rows"]:
        raise AcquisitionError(f"ECHO reported {raw['echo']['query_rows']} facilities, pages held {total}")
    if len(claims) < source["min_potw"]:
        raise AcquisitionError(f"ECHO returned {len(claims)} POTWs, fewer than {source['min_potw']}")
    ledger = hi.close_ledger(source_rows=total, retained=len(claims), excluded=excluded, unresolved=0)
    return claims, ledger


def sdwis_claims(raw: dict[str, Any], source: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims, by_code = [], {}
    for code, (rows, digest) in raw["sdwis"].items():
        if not isinstance(rows, list) or not rows:
            raise AcquisitionError(f"SDWIS returned no {code} facilities")
        kind = source["type_map"][code]
        for r in rows:
            if r.get("facility_type_code") != code:
                raise AcquisitionError(f"SDWIS row {r.get('facility_id')} is not of type {code}")
            claims.append(hi.claim(
                source_key="epa_sdwis_facilities", authority="EPA_SDWIS", feature_type=kind,
                source_feature_id=f"{r['pwsid']}:{r['facility_id']}", name_raw=_text(r.get("facility_name")),
                evidence_tier=source["evidence_tier"], manifestation_sha256=digest, retrieved_utc=now,
                attributes={"pwsid": r["pwsid"], "facility_type_code": code,
                            "facility_activity_code": r.get("facility_activity_code"),
                            "water_type_code": r.get("water_type_code"), "availability_code": r.get("availability_code"),
                            "location": "not published by SDWIS"}))
        by_code[code] = len(rows)
    ledger = hi.close_ledger(source_rows=len(claims), retained=len(claims), excluded={}, unresolved=0)
    ledger["by_facility_type"] = by_code
    return claims, ledger


def fema_claims(raw: dict[str, Any], source: dict[str, Any], now: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    doc, digest = raw["fema"]
    feats = doc.get("features")
    if not feats or doc.get("exceededTransferLimit"):
        raise AcquisitionError("FEMA non-PRASA layer: no features, or the page was truncated")
    claims, excluded = [], {}
    for f in feats:
        a = f.get("attributes") or {}
        site, pws = _text(a.get("ID")), _text(a.get("PWS"))
        if not site or not pws:
            # two rows were appended without an assessment id or PWSID: nothing to join them on
            reason = "no site id or PWSID in the source row"
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        g = f.get("geometry") or {}
        claims.append(hi.claim(
            source_key="fema_nonprasa_sites", authority="FEMA_R2_EPA", feature_type="water_system",
            source_feature_id=site, name_raw=_text(a.get("SYSTEM_NAM")), evidence_tier=source["evidence_tier"],
            manifestation_sha256=digest, retrieved_utc=now, lat=_float(g.get("y")), lon=_float(g.get("x")),
            attributes={"pwsid": pws, "municipio": _text(a.get("MUNICIPALI")), "status_2017": _text(a.get("vvlCurrent")),
                        "location_meaning": source["location_meaning"]}))
    if len(claims) < source["min_rows"]:
        raise AcquisitionError(f"FEMA layer has {len(claims)} sites, fewer than {source['min_rows']}")
    ids = [c["source_feature_id"] for c in claims]
    if len(ids) != len(set(ids)):
        raise AcquisitionError("FEMA site ids repeat")
    ledger = hi.close_ledger(source_rows=len(feats), retained=len(claims), excluded=excluded, unresolved=0)
    return claims, ledger


OUTPUTS = (("prasa_facilities", "claims_prasa_facilities.jsonl", prasa_claims),
           ("usace_nid", "claims_nid_dams.jsonl", nid_claims),
           ("epa_echo_potw", "claims_echo_potw.jsonl", echo_claims),
           ("epa_sdwis_facilities", "claims_sdwis_facilities.jsonl", sdwis_claims),
           ("fema_nonprasa_sites", "claims_fema_nonprasa.jsonl", fema_claims))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-dir", type=Path)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--save-raw", type=Path, help="with --fetch, also write the raw responses in the --src-dir layout")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--now")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.fetch and not args.src_dir:
        print("ingest_hydro_infrastructure: pass --fetch or --src-dir", file=sys.stderr)
        return 2
    now = _iso(datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc))
    config = json.loads((args.config_dir / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    live = {s["source_key"]: s for s in config["live_sources"]}
    hydro = args.data_dir / hi.HYDRO_DIR
    receipt_path = hydro / "ingest_infrastructure_receipt.json"
    try:
        raw = acquire(config, None if args.fetch else args.src_dir, args.save_raw if args.fetch else None)
        built = {key: (name, *fn(raw, live[key], now)) for key, name, fn in OUTPUTS}
    except Exception as exc:  # noqa: BLE001 - every failure leaves a FAIL receipt
        print(f"ingest_hydro_infrastructure: FAIL — {exc}", file=sys.stderr)
        if not args.dry_run:
            hi.write_fail_receipt(receipt_path, "infrastructure", now, str(exc))
        return 1
    summary = {"stage": "infrastructure", "status": "PASS", "run_utc": now, "manifestations": raw["manifest"],
               "ledgers": {key: ledger for key, (_, _, ledger) in built.items()},
               "not_ingested": {"prasa_facilities": live["prasa_facilities"]["not_ingested"],
                                "epa_sdwis_facilities": live["epa_sdwis_facilities"]["not_ingested"]},
               "residue_sources": config.get("residue_sources", [])}
    if args.dry_run:
        print(json.dumps(summary["ledgers"], indent=2, ensure_ascii=False))
        return 0
    for _key, (name, rows, _) in built.items():
        hi.write_claims(hydro / name, rows)
    hi.atomic_write(receipt_path, json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print("ingest_hydro_infrastructure: PASS — " + ", ".join(
        f"{key} {ledger['retained']}/{ledger['source']}" for key, (_, _, ledger) in built.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
