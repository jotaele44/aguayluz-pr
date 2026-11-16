#!/usr/bin/env python3
"""GNIS name claims (springs, streams, lakes, reservoirs) for the Puerto Rico hydrologic inventory.

Source: the USGS Geographic Names Information System (GNIS) domestic-names file for Puerto
Rico (``config/hydro_inventory_sources.v1.json``, ``usgs_gnis_names``). Only the hydrographic
feature classes listed in the config are claimed; every other row (populated places,
summits, valleys...) is counted in the receipt and excluded by reason, so the file's row
arithmetic closes.

GNIS gives one point per named feature (the primary point; for a stream, its mouth) and no
geometry. A GNIS feature id is the identifier the National Hydrography Dataset publishes on
its own features, which is what lets a later phase merge GNIS and NHD claims on I2.

Outputs, committed:

  * ``data/hydro/claims_gnis_names.jsonl``
  * ``data/hydro/ingest_names_receipt.json``

    python scripts/ingest_hydro_names.py --src-dir /path/to/raw
    python scripts/ingest_hydro_names.py --fetch
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
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

RAW_NAME = "DomesticNames_PR_Text.zip"
REQUIRED = {"feature_id", "feature_name", "feature_class", "state_name", "county_name", "prim_lat_dec", "prim_long_dec"}


class AcquisitionError(RuntimeError):
    """The source did not return the file we asked for."""


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


def parse(payload: bytes) -> list[dict[str, str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise AcquisitionError(f"not a zip archive: {exc}") from exc
    names = [n for n in archive.namelist() if n.endswith(".txt")]
    if len(names) != 1:
        raise AcquisitionError(f"expected one text table in the archive, found {names}")
    text = archive.read(names[0]).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    if not rows or not set(rows[0]) >= REQUIRED:
        raise AcquisitionError(f"GNIS table columns changed: missing {REQUIRED - set(rows[0] if rows else {})}")
    return rows


def claims_from(rows: list[dict[str, str]], classes: dict[str, str], sha: str, now: str
                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out, excluded = [], {}
    for r in rows:
        klass = r["feature_class"]
        if klass not in classes:
            excluded[f"GNIS class '{klass}' is not hydrographic"] = excluded.get(f"GNIS class '{klass}' is not hydrographic", 0) + 1
            continue
        try:
            lat, lon = float(r["prim_lat_dec"]), float(r["prim_long_dec"])
        except ValueError:
            lat = lon = None
        if lat == 0 and lon == 0:
            lat = lon = None
        out.append(hi.claim(
            source_key="usgs_gnis_names", authority="USGS_GNIS", feature_type=classes[klass],
            source_feature_id=str(r["feature_id"]), name_raw=r["feature_name"], evidence_tier="T2",
            manifestation_sha256=sha, retrieved_utc=now, lat=lat, lon=lon,
            attributes={"gnis_class": klass, "county_name": r.get("county_name"), "map_name": r.get("map_name"),
                        "date_edited": r.get("date_edited"), "point": "GNIS primary point (a stream's mouth)"}))
    ledger = hi.close_ledger(source_rows=len(rows), retained=len(out), excluded=excluded, unresolved=0)
    by_class: dict[str, int] = {}
    for c in out:
        by_class[c["attributes"]["gnis_class"]] = by_class.get(c["attributes"]["gnis_class"], 0) + 1
    return out, {**ledger, "retained_by_class": dict(sorted(by_class.items()))}


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
        print("ingest_hydro_names: pass --fetch or --src-dir", file=sys.stderr)
        return 2
    now = _iso(datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc))
    config = json.loads((args.config_dir / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    source = next(s for s in config["live_sources"] if s["source_key"] == "usgs_gnis_names")
    receipt_path = args.data_dir / hi.HYDRO_DIR / "ingest_names_receipt.json"
    try:
        payload = (args.src_dir / RAW_NAME).read_bytes() if args.src_dir else _get(source["url"])
        sha = hashlib.sha256(payload).hexdigest()
        claims, ledger = claims_from(parse(payload), source["classes"], sha, now)
    except Exception as exc:  # noqa: BLE001 - every failure leaves a FAIL receipt
        print(f"ingest_hydro_names: FAIL — {exc}", file=sys.stderr)
        if not args.dry_run:
            hi.write_fail_receipt(receipt_path, "names", now, str(exc))
        return 1
    summary = {"stage": "names", "status": "PASS", "run_utc": now,
               "manifestations": [{"source_key": "usgs_gnis_names", "url": source["url"], "byte_sha256": sha,
                                   "bytes": len(payload), "pin_matches": None}],
               "ledgers": {"usgs_gnis_names": ledger}}
    if args.dry_run:
        print(json.dumps(summary["ledgers"], indent=2))
        return 0
    hi.write_claims(args.data_dir / hi.HYDRO_DIR / "claims_gnis_names.jsonl", claims)
    hi.atomic_write(receipt_path, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"ingest_hydro_names: PASS — {len(claims)} hydrographic names of {ledger['source']} GNIS rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
