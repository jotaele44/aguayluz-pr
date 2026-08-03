#!/usr/bin/env python3
"""Ingest the NEON Puerto Rico (Domain D04) site network and its publication state.

Fills the *research-observatory* gap. The producer's hydrology backbone is
regulatory and operational — USGS gauges, NOAA tide stations, EPA SDWIS/ECHO. None
of it carries research-grade stream chemistry, and none of it covers the southwest
dry-forest / Lajas valley corridor at sensor density. NEON does: four NSF sites in
Domain D04 "Atlantic Neotropical", two of them stream sites (CUPE, GUIL) publishing
continuous discharge, surface-water elevation and full water chemistry.

Source: the NEON API v0 (``data.neonscience.org/api/v0``), a federal NSF T1 feed.
This script uses only its **open, keyless** endpoints and writes two halves:

  * assets       -> ``data/utility_assets.jsonl``          (asset_type=water, NEON_* prefix)
  * availability -> ``data/neon_availability.jsonl``       (one row per site x product)
  * events       -> ``data/neon_publication_events.jsonl`` (deduped publication log)

The availability file is the point. ``/sites/{code}`` returns, for every data
product at that site, an ``availableMonths[]`` array. Diffing that array run over
run yields the entire publication-change signal — a new monthly release, a product
that appeared, a historical month silently re-published after a correction — with
no file download and no credential. ``scripts/ingest_neon_products.py`` consumes
those change records to fetch only what actually moved.

**``data/neon_availability.jsonl`` is committed, unlike the time-series reading
files.** It is not regenerable output: it IS the previous state the delta is
computed against. Gitignoring it would make every CI runner start empty and report
all ~320 site/product pairs as new on every run.

Months are stored as a sha256 over the sorted month list rather than the raw array
(~100 entries x ~320 pairs would bloat a committed file). The hash still detects a
back-filled historical month — the "corrected product" case — which a
``latest_month`` comparison alone would miss.

    python scripts/ingest_neon.py                          # live (no credential needed)
    python scripts/ingest_neon.py --src tests/fixtures/neon_site_cupe_sample.json
    python scripts/ingest_neon.py --stale-months 3         # publication-gap threshold
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz.neon import (  # noqa: E402
    NEON_EVIDENCE_TIER,
    NEON_OPERATOR,
    PR_SITES,
    PRODUCT_METRICS,
    NeonClient,
    check_health,
    endpoints,
    site_by_code,
)
from aguayluz.neon.mapping import MONTHLY_CADENCE_PRODUCTS  # noqa: E402

# Reuse the surface-water ingester's municipality resolver — the same point-in-polygon
# helper ingest_usgs_groundwater.py reuses. No new geo code.
from ingest_usgs_water import (  # noqa: E402
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MUNI_GEOJSON,
    load_municipios,
    municipality_for,
)

#: Only continuous-sensor / regular-monthly products are checked for a publication
#: gap. Most NEON products are sampled annually, seasonally or by field campaign, so
#: a blanket "no new month in N months" rule fires constantly on healthy feeds.
_CADENCE_MONTHLY = MONTHLY_CADENCE_PRODUCTS

DEFAULT_STALE_MONTHS = 3


def _confidence(has_coords: bool = True) -> int:
    try:
        from aguayluz.confidence import score

        return int(score(NEON_EVIDENCE_TIER, has_coords=has_coords))
    except Exception:  # noqa: BLE001
        return 80 if has_coords else 65


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── source acquisition ────────────────────────────────────────────────────────
def fetch_sites_live(client: NeonClient | None = None) -> list[dict[str, Any]]:
    """Fetch ``/sites/{code}`` for each of the four PR sites.

    Deliberately not ``/sites`` — that returns every NEON site worldwide (~26 MB)
    when four targeted requests cost ~4 of the 200/hour anonymous quota.
    """
    owns = client is None
    client = client or NeonClient()
    try:
        docs: list[dict[str, Any]] = []
        for s in PR_SITES:
            try:
                data = client.get_data(endpoints.site(s["code"]))
            except Exception as e:  # noqa: BLE001
                print(f"  site {s['code']} fetch failed ({e}); skipping", file=sys.stderr)
                continue
            if isinstance(data, dict):
                docs.append(data)
        return docs
    finally:
        if owns:
            client.close()


# ── build asset rows ──────────────────────────────────────────────────────────
def build_asset(doc: dict[str, Any], munis: list[tuple[str, list[list]]] | None = None) -> dict:
    """Project one NEON site-detail doc into a utility_asset row.

    ``asset_type`` is ``water`` for all four sites. The enum offers only
    water/wastewater/power/telecom/fuel/unknown, and GUAN and LAJA are a dry forest
    and an agricultural station rather than water infrastructure — but their
    hydrologic products (precipitation, soil water) are precisely why this producer
    wants them, so ``water`` is more honest than ``unknown``. The distinction is
    carried explicitly in ``asset_subtype``, never flattened away.
    """
    code = str(doc.get("siteCode") or "")
    reg = site_by_code(code) or {}
    lat = doc.get("siteLatitude", reg.get("lat"))
    lon = doc.get("siteLongitude", reg.get("lon"))
    habitat = reg.get("habitat") or ("aquatic" if str(doc.get("siteType")) == "CORE" else "terrestrial")

    in_bounds = (
        isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX
    )
    muni = "unknown"
    if in_bounds and munis:
        muni = municipality_for(float(lat), float(lon), munis)

    products = doc.get("dataProducts") or []
    fingerprint = _sha256(
        json.dumps(
            {
                "siteCode": code,
                "siteName": doc.get("siteName"),
                "lat": lat,
                "lon": lon,
                "n_products": len(products),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
    )

    row = {
        "asset_id": f"NEON_{code}",
        "asset_name": str(doc.get("siteName") or reg.get("name") or f"NEON {code}"),
        "asset_type": "water",
        "asset_subtype": f"research_station_{habitat}",
        "operator": NEON_OPERATOR,
        "municipality": muni,
        "geometry_type": "point" if in_bounds else "unknown",
        "status": "active",
        "source_ref": f"NEON API {endpoints.API_VERSION} {endpoints.site(code)}",
        "source_hash": fingerprint,
        "evidence_tier": NEON_EVIDENCE_TIER,
        "confidence": _confidence(in_bounds),
        "review_status": "accepted",
    }
    if in_bounds:
        row["lat"], row["lon"] = round(float(lat), 6), round(float(lon), 6)
    return row


# ── build availability rows ───────────────────────────────────────────────────
def _latest_release(doc: dict[str, Any]) -> tuple[str | None, str | None]:
    """(release name, generation date) of the newest release listed for the site."""
    releases = [r for r in (doc.get("releases") or []) if isinstance(r, dict)]
    if not releases:
        return None, None
    newest = max(releases, key=lambda r: str(r.get("generationDate") or ""))
    return newest.get("release"), newest.get("generationDate")


def build_availability(doc: dict[str, Any]) -> list[dict]:
    """One current-state row per (site, product) from a site-detail doc.

    Carries no ``first_seen``/``last_changed`` — those need the previous state and
    are stamped by :func:`merge_availability`.
    """
    code = str(doc.get("siteCode") or "")
    if not code:
        return []
    reg = site_by_code(code) or {}
    release_name, release_generated = _latest_release(doc)
    source_ref = f"NEON API {endpoints.API_VERSION} {endpoints.site(code)}"

    rows: list[dict] = []
    for prod in doc.get("dataProducts") or []:
        if not isinstance(prod, dict):
            continue
        product_code = str(prod.get("dataProductCode") or "")
        if not product_code:
            continue
        months = sorted(str(m) for m in (prod.get("availableMonths") or []))
        months_hash = _sha256("|".join(months))
        rows.append({
            "registry_id": f"NEON_{code}_{product_code}",
            "neon_site": code,
            "site_name": str(doc.get("siteName") or reg.get("name") or code),
            "habitat": reg.get("habitat") or "unknown",
            "lat": reg.get("lat"),
            "lon": reg.get("lon"),
            "product_code": product_code,
            "product_title": str(prod.get("dataProductTitle") or product_code),
            "month_count": len(months),
            "first_month": months[0] if months else None,
            "latest_month": months[-1] if months else None,
            "months_sha256": months_hash,
            "latest_release": release_name,
            "release_generated_at": release_generated,
            "ingestible": product_code in PRODUCT_METRICS,
            "source_ref": source_ref,
            "source_hash": months_hash,
            "evidence_tier": NEON_EVIDENCE_TIER,
            "confidence": _confidence(True),
            "review_status": "accepted",
        })
    return rows


# ── delta ─────────────────────────────────────────────────────────────────────
def _month_key(month: str | None) -> tuple[int, int]:
    try:
        y, m = str(month).split("-")[:2]
        return int(y), int(m)
    except (ValueError, AttributeError):
        return (0, 0)


def _months_behind(month: str | None, today: date) -> int:
    if not month:
        return 10_000
    y, m = _month_key(month)
    if (y, m) == (0, 0):
        return 10_000
    return (today.year - y) * 12 + (today.month - m)


def _change_record(row: dict, change_type: str, **extra: Any) -> dict:
    """One typed publication-change record for an availability row.

    Module-level rather than a closure inside :func:`diff_availability` so the row
    it describes is bound explicitly at call time (ruff B023) instead of captured
    from the enclosing loop.
    """
    rec = {
        # Deterministic per publication event, NOT per run: the same new month
        # detected twice must dedupe, so the alert derived from it is stable
        # instead of flapping in and out of data/alert_events.jsonl.
        "event_id": (
            f"{row.get('neon_site')}_{row.get('product_code')}_"
            f"{change_type}_{row.get('latest_month') or 'none'}"
        ),
        "change_type": change_type,
        "registry_id": row.get("registry_id"),
        "neon_site": row.get("neon_site"),
        "site_name": row.get("site_name"),
        "habitat": row.get("habitat"),
        "lat": row.get("lat"),
        "lon": row.get("lon"),
        "product_code": row.get("product_code"),
        "product_title": row.get("product_title"),
        "latest_month": row.get("latest_month"),
        "month_count": row.get("month_count"),
        "latest_release": row.get("latest_release"),
        "release_generated_at": row.get("release_generated_at"),
        "ingestible": row.get("ingestible"),
        "source_ref": row.get("source_ref"),
        "source_hash": row.get("source_hash"),
        "evidence_tier": row.get("evidence_tier"),
        "confidence": row.get("confidence"),
    }
    rec.update(extra)
    return rec


def diff_availability(
    previous: list[dict],
    current: list[dict],
    *,
    today: date | None = None,
    stale_months: int = DEFAULT_STALE_MONTHS,
) -> list[dict]:
    """Typed publication-change records between two availability snapshots.

    Change types:
      ``new_product``      — a product appeared at a site for the first time
      ``new_month``        — a newer month was published (the routine release)
      ``backfilled_month`` — the month list changed but ``latest_month`` did not,
                             i.e. a historical month was corrected or re-published
      ``new_release``      — the site's newest NEON RELEASE tag changed
      ``publication_gap``  — a monthly-cadence product has not published in
                             ``stale_months`` months (possible sensor outage)

    A **bootstrap run — empty ``previous`` — yields no changes at all.** There is no
    delta against nothing, and treating the initial inventory as ~328 ``new_product``
    events would flood the alert layer on first adoption with rows that describe
    NEON's decade-old catalogue rather than anything that just happened. The registry
    is populated on that run; the first real delta lands on the next one.

    Pure: no I/O, no wall-clock (``today`` is injected). Directly unit-testable.
    """
    today = today or date.today()
    if not previous:
        return []
    prev_by_id = {r.get("registry_id"): r for r in previous}
    changes: list[dict] = []

    for row in current:
        rid = row.get("registry_id")
        prev = prev_by_id.get(rid)

        _record = partial(_change_record, row)

        if prev is None:
            # A first-ever run would flag all ~320 pairs as new. That is correct
            # behaviour for a genuinely new product, and why the registry file is
            # committed rather than regenerated from empty on every CI runner.
            changes.append(_record("new_product", previous_latest_month=None))
            continue

        prev_latest = prev.get("latest_month")
        curr_latest = row.get("latest_month")
        if _month_key(curr_latest) > _month_key(prev_latest):
            changes.append(_record("new_month", previous_latest_month=prev_latest))
        elif prev.get("months_sha256") != row.get("months_sha256"):
            changes.append(_record(
                "backfilled_month",
                previous_latest_month=prev_latest,
                previous_month_count=prev.get("month_count"),
            ))

        if prev.get("latest_release") != row.get("latest_release") and row.get("latest_release"):
            changes.append(_record(
                "new_release", previous_release=prev.get("latest_release"),
            ))

        if (
            row.get("product_code") in _CADENCE_MONTHLY
            and _months_behind(curr_latest, today) > stale_months
        ):
            changes.append(_record(
                "publication_gap",
                previous_latest_month=prev_latest,
                months_behind=_months_behind(curr_latest, today),
            ))

    return changes


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_assets(existing: list[dict], sites: list[dict]) -> list[dict]:
    """Preserve every non-NEON row; (re)place NEON_* rows."""
    by_id = {
        r["asset_id"]: r
        for r in existing
        if not str(r.get("asset_id", "")).startswith("NEON_")
    }
    for r in sites:
        by_id[r["asset_id"]] = r
    return list(by_id.values())


def merge_availability(previous: list[dict], current: list[dict], now_iso: str) -> list[dict]:
    """Carry ``first_seen`` forward and stamp ``last_changed`` only on real change.

    Stamping ``last_changed`` unconditionally would dirty every row on every run and
    produce a ~320-line diff per scheduled refresh.
    """
    prev_by_id = {r.get("registry_id"): r for r in previous}
    out: list[dict] = []
    for row in current:
        prev = prev_by_id.get(row.get("registry_id"))
        merged = dict(row)
        if prev is None:
            merged["first_seen"] = now_iso
            merged["last_changed"] = now_iso
        else:
            merged["first_seen"] = prev.get("first_seen") or now_iso
            changed = prev.get("months_sha256") != row.get("months_sha256") or prev.get(
                "latest_release"
            ) != row.get("latest_release")
            merged["last_changed"] = now_iso if changed else (prev.get("last_changed") or now_iso)
        out.append(merged)
    # Retired site/product pairs are dropped rather than tombstoned: NEON removing a
    # product from a site is rare, and a stale row would keep re-firing publication_gap.
    return sorted(out, key=lambda r: (r["neon_site"], r["product_code"]))


def merge_events(existing: list[dict], new: list[dict], keep: int) -> list[dict]:
    """Append newly detected publication events to the persistent log.

    Deduped on ``event_id``, so re-detecting the same publication is a no-op and the
    alert built from it keeps a stable ``alert_id``. Retained newest-first to
    ``keep`` rows: without a cap this file grows by ~300 rows a month forever, and
    an alert for a two-year-old release has no operational value.
    """
    by_id: dict[str, dict] = {}
    for rec in existing:
        eid = rec.get("event_id")
        if eid:
            by_id[eid] = rec
    for rec in new:
        eid = rec.get("event_id")
        if eid and eid not in by_id:  # first detection wins — keeps detected_at true
            by_id[eid] = rec
    ordered = sorted(by_id.values(), key=lambda r: str(r.get("detected_at") or ""), reverse=True)
    return list(reversed(ordered[:keep]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", nargs="*", type=Path,
                    help="Local NEON /sites/{code} JSON file(s) (the `data` member or the full envelope).")
    ap.add_argument("--assets-out", default="data/utility_assets.jsonl")
    ap.add_argument("--availability-out", default="data/neon_availability.jsonl")
    ap.add_argument("--changes-out", default="outputs/neon_changes.jsonl",
                    help="This run's new publication changes; consumed by ingest_neon_products.py.")
    ap.add_argument("--events-out", default="data/neon_publication_events.jsonl",
                    help="Persistent deduped publication-event log; consumed by build_alerts.py.")
    ap.add_argument("--keep-events", type=int, default=500,
                    help="Publication events retained in the persistent log (newest first).")
    ap.add_argument("--health-out", default="outputs/neon_health.json")
    ap.add_argument("--stale-months", type=int, default=DEFAULT_STALE_MONTHS,
                    help="Months without a new publication before a monthly-cadence product is flagged.")
    ap.add_argument("--no-health", action="store_true", help="Skip the provider health probe.")
    args = ap.parse_args()

    now_iso = _utc_now_iso()

    if args.src:
        docs = []
        for p in args.src:
            doc = json.loads(p.read_text())
            # Accept both the raw NEON envelope and a bare `data` member.
            docs.append(doc.get("data") if isinstance(doc, dict) and "data" in doc else doc)
        origin = ", ".join(str(p) for p in args.src)
        health: dict[str, Any] | None = None
    else:
        docs = fetch_sites_live()
        origin = f"live NEON API ({len(docs)}/{len(PR_SITES)} PR sites)"
        health = None if args.no_health else check_health()
        if not docs:
            print("no NEON site data fetched; pass --src <json> to run offline", file=sys.stderr)
            return 1

    assets: list[dict] = []
    availability: list[dict] = []
    munis = load_municipios(MUNI_GEOJSON)
    for doc in docs:
        if not isinstance(doc, dict) or not doc.get("siteCode"):
            continue
        assets.append(build_asset(doc, munis))
        availability.extend(build_availability(doc))

    apath = REPO / args.assets_out
    combined_assets = merge_assets(_read_jsonl(apath), assets)
    apath.parent.mkdir(parents=True, exist_ok=True)
    # Default ensure_ascii (escaped unicode), matching how every other asset ingest
    # writes this file. Emitting raw UTF-8 here re-encodes all 347 accented rows and
    # turns a 4-row addition into a 700-line diff.
    apath.write_text("".join(json.dumps(r) + "\n" for r in combined_assets))

    vpath = REPO / args.availability_out
    previous = _read_jsonl(vpath)
    changes = diff_availability(previous, availability, stale_months=args.stale_months)
    for rec in changes:
        rec["detected_at"] = now_iso
    combined_availability = merge_availability(previous, availability, now_iso)
    vpath.parent.mkdir(parents=True, exist_ok=True)
    vpath.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined_availability)
    )

    cpath = REPO / args.changes_out
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in changes))

    epath = REPO / args.events_out
    combined_events = merge_events(_read_jsonl(epath), changes, args.keep_events)
    epath.parent.mkdir(parents=True, exist_ok=True)
    epath.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in combined_events))

    if health is not None:
        hpath = REPO / args.health_out
        hpath.parent.mkdir(parents=True, exist_ok=True)
        hpath.write_text(json.dumps(health, indent=2, ensure_ascii=False) + "\n")

    by_change: dict[str, int] = {}
    for rec in changes:
        by_change[rec["change_type"]] = by_change.get(rec["change_type"], 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_change.items())) or "none"

    print(f"source: {origin}")
    if health is not None:
        auth = "authenticated" if health["authenticated"] else (
            "token rejected" if health["token_present"] else "anonymous"
        )
        print(f"health: reachable={health['reachable']} ({auth}) "
              f"latency={health['latency_ms']}ms quota={health['rate_limit_remaining']}")
    print(f"wrote {len(assets)} NEON site assets -> {apath}")
    print(f"wrote {len(combined_availability)} availability rows -> {vpath}")
    print(f"wrote {len(changes)} publication changes ({breakdown}) -> {cpath}")
    print(f"wrote {len(combined_events)} retained publication events -> {epath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
