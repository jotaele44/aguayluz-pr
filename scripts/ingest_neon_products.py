#!/usr/bin/env python3
"""Download changed NEON water products for the PR aquatic sites into readings.

Second half of the NEON integration. ``scripts/ingest_neon.py`` tracks *what* NEON
has published using only open endpoints; this script downloads the products that
actually moved and turns them into ``monitoring_reading`` rows:

  * readings -> ``data/neon_readings.jsonl`` (metric=streamflow / gage_height /
    water_quality, asset_id=NEON_<site>)

**This half needs a NEON API token.** ``/api/v0/data/{product}/{site}/{month}``
returns HTTP 403 ``Access Denied`` to anonymous callers — verified against NEON's
own gateway, not a local proxy; the metadata endpoints on the same host answer 200.
With no token the script prints a skip notice and exits 0, the same contract
``scripts/ingest_osha.py`` uses for its DOL key, so a token-less refresh run warns
and continues instead of failing.

    export NEON_API_TOKEN=...            # https://data.neonscience.org/myaccount
    python scripts/ingest_neon_products.py
    python scripts/ingest_neon_products.py --months 3      # widen the backfill window
    python scripts/ingest_neon_products.py \
        --src-manifest tests/fixtures/neon_data_manifest_sample.json \
        --src-csv tests/fixtures/neon_continuous_discharge_sample.csv

Only products present in ``aguayluz.neon.mapping.PRODUCT_METRICS`` are downloaded —
the ``metric`` enum in ``schemas/monitoring_reading.schema.json`` is closed, so
precipitation / soil / evapotranspiration products are tracked for availability but
cannot be stored until that enum is extended (see ``docs/NEON_INTEGRATION.md``).

Integrity: every downloaded file is checked against the ``md5`` NEON publishes in
the manifest before it is parsed. A mismatch skips the file rather than ingesting
possibly-truncated data, and is reported on stderr and in the run summary.

    NOTE ON VERIFICATION: because the endpoint is credential-gated and no NEON token
    was available when this was written, the live download path has not been
    exercised end-to-end. The offline fixtures under tests/fixtures/ are
    hand-authored from NEON's published response and file formats and are labelled
    SYNTHETIC. Column names come from the NEON data-product documentation; the
    parser fails safe (skips the file with a warning) when no known column matches,
    rather than guessing at a value column.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz.neon import (  # noqa: E402
    NEON_EVIDENCE_TIER,
    PRODUCT_METRICS,
    NeonAccessDenied,
    NeonAuthError,
    NeonClient,
    endpoints,
    resolve_token,
)

#: Per-product CSV column candidates, from the NEON data-product documentation.
#:
#: ``date`` lists observation-timestamp columns and ``value`` the measurement, both
#: in preference order; the first column actually present in the file wins. ``scale``
#: converts NEON's published unit to the unit recorded on the reading (NEON reports
#: discharge in litres/second; this repo stores m3/s).
#:
#: A product whose file matches none of its candidates is SKIPPED with a warning —
#: never silently mapped onto some other column.
CSV_COLUMNS: dict[str, dict[str, Any]] = {
    "DP4.00130.001": {
        "date": ["endDate", "date", "startDate"],
        "value": ["maxpostDischarge", "continuousDischarge", "meanQ"],
        "scale": 0.001,  # L/s -> m3/s
    },
    "DP1.20193.001": {
        "date": ["collectDate", "startDate", "endDate"],
        "value": ["finalDischarge", "streamDischarge"],
        "scale": 0.001,  # L/s -> m3/s
    },
    "DP1.20048.001": {
        "date": ["collectDate", "startDate", "endDate"],
        "value": ["finalDischarge", "totalDischarge"],
        "scale": 0.001,  # L/s -> m3/s
    },
    "DP1.20016.001": {
        "date": ["endDate", "date", "startDate"],
        "value": ["surfacewaterElevMean", "surfacewaterElev"],
        "scale": 1.0,
    },
    "DP1.20093.001": {
        "date": ["collectDate", "startDate", "endDate"],
        "value": ["specificConductance", "waterTemp"],
        "scale": 1.0,
    },
    "DP1.20033.001": {
        "date": ["startDateTime", "collectDate", "startDate"],
        "value": ["surfWaterNitrateMean", "surfWaterNitrate"],
        "scale": 1.0,
    },
    "DP1.20097.001": {
        "date": ["collectDate", "startDate"],
        "value": ["dissolvedCO2", "dissolvedCH4"],
        "scale": 1.0,
    },
}

#: NEON quality-flag columns. A row flagged 1 is a failed sensor/QA check and is
#: dropped rather than ingested — the "QA downgrade" signal, applied at the row level.
QF_COLUMNS: tuple[str, ...] = ("finalQF", "dischargeFinalQF", "surfacewaterElevFinalQF")

#: Only the basic package is downloaded; the expanded package adds QA detail this
#: producer does not store and multiplies download size.
PACKAGE = "basic"

DEFAULT_MONTHS_BACK = 2


def _confidence(provisional: bool = False) -> int:
    try:
        from aguayluz.confidence import score

        base = int(score(NEON_EVIDENCE_TIER, has_coords=True))
    except Exception:  # noqa: BLE001
        base = 80
    return max(0, base - (5 if provisional else 0))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _recent_months(back: int, today: date | None = None) -> list[str]:
    """The last ``back`` + 1 months as ``YYYY-MM``, newest first."""
    today = today or date.today()
    out: list[str] = []
    y, m = today.year, today.month
    for _ in range(back + 1):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


# ── target selection ──────────────────────────────────────────────────────────
def select_targets(
    changes: list[dict],
    *,
    months_back: int = DEFAULT_MONTHS_BACK,
    today: date | None = None,
) -> list[dict]:
    """(product, site, month) triples worth downloading, from publication changes.

    Only ingestible products are considered — this is the "download only what
    changed" contract. A ``new_month`` change downloads the newly published month;
    ``new_product`` and ``backfilled_month`` pull the recent window because the
    specific month that moved is not identifiable from the hash alone.
    """
    window = set(_recent_months(months_back, today))
    seen: set[tuple[str, str, str]] = set()
    targets: list[dict] = []

    for rec in changes:
        product_code = rec.get("product_code")
        site = rec.get("neon_site")
        if product_code not in PRODUCT_METRICS or not site:
            continue
        change_type = rec.get("change_type")
        if change_type == "publication_gap":
            continue  # nothing new to fetch; it is an alert, not a download

        if change_type == "new_month" and rec.get("latest_month"):
            months = {str(rec["latest_month"])}
        else:
            latest = str(rec.get("latest_month") or "")
            months = {m for m in window if not latest or m <= latest}
            if latest and latest not in months:
                months.add(latest)

        for month in sorted(months, reverse=True):
            key = (product_code, site, month)
            if key in seen:
                continue
            seen.add(key)
            targets.append({
                "product_code": product_code,
                "neon_site": site,
                "month": month,
                "change_type": change_type,
                "latest_release": rec.get("latest_release"),
            })
    return targets


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_manifest(client: NeonClient, product_code: str, site: str, month: str) -> dict | None:
    """File manifest for one product/site/month, or ``None`` when NEON has none."""
    path = endpoints.data_manifest(product_code, site, month)
    try:
        return client.get_data(path)
    except NeonAuthError:
        raise
    except NeonAccessDenied:
        raise
    except Exception as e:  # noqa: BLE001 — a 404 for an unpublished month is normal
        print(f"  manifest {product_code}/{site}/{month} unavailable ({e})", file=sys.stderr)
        return None


def select_files(manifest: dict, package: str = PACKAGE) -> list[dict]:
    """Data CSVs in a manifest, excluding readme/variables/sensor-position sidecars."""
    out: list[dict] = []
    for f in manifest.get("files") or []:
        name = str(f.get("name") or "")
        if not name.endswith(".csv"):
            continue
        lowered = name.lower()
        if any(tok in lowered for tok in ("readme", "variables", "validation", "categoricalcodes")):
            continue
        if f".{package}." not in lowered and package != "":
            continue
        out.append(f)
    return out


def download_file(client: NeonClient, entry: dict) -> bytes | None:
    """Download one manifest file and verify NEON's published md5 before returning.

    A mismatch returns ``None`` — a truncated or corrupted download must not reach
    the reading store.
    """
    import httpx

    url = entry.get("url")
    if not url:
        return None
    r = httpx.get(url, timeout=180, follow_redirects=True)
    r.raise_for_status()
    payload = r.content
    expected = str(entry.get("md5") or "").strip().lower()
    if expected:
        actual = hashlib.md5(payload).hexdigest()  # noqa: S324 — integrity, not security
        if actual != expected:
            print(
                f"  md5 mismatch for {entry.get('name')}: expected {expected}, got {actual}; skipping",
                file=sys.stderr,
            )
            return None
    return payload


# ── parse CSV -> readings ─────────────────────────────────────────────────────
def _pick_column(fieldnames: list[str], candidates: list[str]) -> str | None:
    lookup = {f.lower(): f for f in fieldnames}
    for cand in candidates:
        hit = lookup.get(cand.lower())
        if hit:
            return hit
    return None


def _flagged(row: dict[str, str]) -> bool:
    for col in QF_COLUMNS:
        raw = row.get(col)
        if raw in (None, ""):
            continue
        try:
            if int(float(raw)) == 1:
                return True
        except (TypeError, ValueError):
            continue
    return False


def build_readings(
    payload: str | bytes,
    product_code: str,
    site: str,
    *,
    provisional: bool = False,
    release: str | None = None,
) -> list[dict]:
    """Parse one NEON basic-package CSV into daily ``monitoring_reading`` rows.

    Sub-daily sensor records are reduced to a daily mean per site/metric, matching
    the ``AYL_RDG_<YYYYMMDD>_<site>_<metric>`` "stable per asset/metric/day"
    contract the schema documents. QA-flagged rows are dropped before aggregation.

    Returns ``[]`` (with a warning) when the file carries none of the documented
    columns for its product — a fail-safe, never a guess at which column to read.
    """
    spec = CSV_COLUMNS.get(product_code)
    meta = PRODUCT_METRICS.get(product_code)
    if not spec or not meta:
        return []

    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    reader = csv.DictReader(io.StringIO(text))
    fields = list(reader.fieldnames or [])
    if not fields:
        return []

    date_col = _pick_column(fields, spec["date"])
    value_col = _pick_column(fields, spec["value"])
    if not date_col or not value_col:
        print(
            f"  {product_code}/{site}: no known date/value column "
            f"(looked for {spec['date']} / {spec['value']}); skipping file",
            file=sys.stderr,
        )
        return []

    scale = float(spec.get("scale", 1.0))
    daily: dict[str, list[float]] = {}
    for row in reader:
        if _flagged(row):
            continue
        raw = row.get(value_col)
        if raw in (None, ""):
            continue
        try:
            val = float(raw) * scale
        except (TypeError, ValueError):
            continue
        day = str(row.get(date_col) or "")[:10].replace("/", "-")
        if len(day) != 10:
            continue
        daily.setdefault(day, []).append(val)

    metric = meta["metric"]
    unit = meta["unit"]
    src = (
        f"NEON API {endpoints.API_VERSION} "
        f"{endpoints.data_manifest(product_code, site, '{month}')} "
        f"({product_code} {meta['title']}"
        + (f", {release}" if release else "")
        + ")"
    )
    rows: list[dict] = []
    for day, values in sorted(daily.items()):
        mean = sum(values) / len(values)
        rows.append({
            "reading_id": f"AYL_RDG_{day.replace('-', '')}_NEON_{site}_{metric}",
            "asset_id": f"NEON_{site}",
            "site_no": site,
            "metric": metric,
            "parameter_code": product_code,
            "value": round(mean, 6),
            "unit": unit,
            "observed_date": day,
            "provisional": provisional,
            "source_ref": src,
            "source_hash": hashlib.sha256(
                f"{product_code}|{site}|{day}|{mean}".encode()
            ).hexdigest(),
            "evidence_tier": NEON_EVIDENCE_TIER,
            "confidence": _confidence(provisional),
            "review_status": "accepted",
        })
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_readings(existing: list[dict], new: list[dict]) -> list[dict]:
    by_id = {r["reading_id"]: r for r in existing}
    for r in new:
        by_id[r["reading_id"]] = r
    return sorted(by_id.values(), key=lambda r: (r["asset_id"], r["metric"], r["observed_date"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--changes", default="outputs/neon_changes.jsonl",
                    help="Publication-change records from scripts/ingest_neon.py.")
    ap.add_argument("--readings-out", default="data/neon_readings.jsonl")
    ap.add_argument("--months", type=int, default=DEFAULT_MONTHS_BACK,
                    help="How many months back to pull for a new/backfilled product.")
    ap.add_argument("--src-manifest", type=Path, help="Offline NEON data-manifest JSON.")
    ap.add_argument("--src-csv", nargs="*", type=Path, help="Offline NEON product CSV(s).")
    ap.add_argument("--product", help="Product code for --src-csv (default: first ingestible).")
    ap.add_argument("--site", default="CUPE", help="Site code for --src-csv.")
    args = ap.parse_args()

    readings: list[dict] = []
    skipped = 0

    # ── offline path ─────────────────────────────────────────────────────────
    if args.src_csv:
        product_code = args.product or next(iter(PRODUCT_METRICS))
        release = None
        if args.src_manifest and args.src_manifest.is_file():
            doc = json.loads(args.src_manifest.read_text())
            manifest = doc.get("data") if isinstance(doc, dict) and "data" in doc else doc
            release = (manifest or {}).get("release")
        for p in args.src_csv:
            rows = build_readings(
                p.read_text(), product_code, args.site,
                provisional=(release or "PROVISIONAL").upper().startswith("PROVISIONAL"),
                release=release,
            )
            if not rows:
                skipped += 1
            readings.extend(rows)
        origin = ", ".join(str(p) for p in args.src_csv)

    # ── live path ────────────────────────────────────────────────────────────
    else:
        if resolve_token() is None:
            print(
                "NEON_API_TOKEN not set — skipping NEON product download.\n"
                "  The NEON file-manifest endpoint (/api/v0/data/...) returns HTTP 403 to\n"
                "  anonymous callers. Site and availability tracking (scripts/ingest_neon.py)\n"
                "  needs no credential and is unaffected. Get a token at\n"
                "  https://data.neonscience.org/myaccount, or pass --src-csv to run offline."
            )
            return 0

        changes = _read_jsonl(REPO / args.changes)
        if not changes:
            print(f"no publication changes in {args.changes}; nothing to download")
            return 0

        targets = select_targets(changes, months_back=args.months)
        if not targets:
            print(f"{len(changes)} change(s), none for an ingestible product; nothing to download")
            return 0

        print(f"{len(targets)} product/site/month target(s) from {len(changes)} change(s)")
        with NeonClient() as client:
            for t in targets:
                try:
                    manifest = fetch_manifest(
                        client, t["product_code"], t["neon_site"], t["month"]
                    )
                except (NeonAuthError, NeonAccessDenied) as e:
                    print(f"NEON denied the manifest request: {e}", file=sys.stderr)
                    return 1
                if not manifest:
                    continue
                release = manifest.get("release")
                provisional = str(release or "PROVISIONAL").upper().startswith("PROVISIONAL")
                for entry in select_files(manifest):
                    try:
                        payload = download_file(client, entry)
                    except Exception as e:  # noqa: BLE001
                        print(f"  download failed for {entry.get('name')} ({e})", file=sys.stderr)
                        skipped += 1
                        continue
                    if payload is None:
                        skipped += 1
                        continue
                    rows = build_readings(
                        payload, t["product_code"], t["neon_site"],
                        provisional=provisional, release=release,
                    )
                    if not rows:
                        skipped += 1
                    readings.extend(rows)
        origin = f"live NEON API ({len(targets)} targets)"

    rpath = REPO / args.readings_out
    combined = merge_readings(_read_jsonl(rpath), readings)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined))

    print(f"source: {origin}")
    print(f"wrote {len(readings)} NEON readings ({len(combined)} total) -> {rpath}")
    if skipped:
        print(f"  {skipped} file(s) skipped (md5 mismatch, download error, or unknown columns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
