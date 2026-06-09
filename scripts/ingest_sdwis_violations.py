#!/usr/bin/env python3
"""Ingest EPA SDWIS drinking-water violations for PR into service_events.jsonl.

The missing public-health water signal. Source: EPA Envirofacts SDWIS
(``data.epa.gov/efservice``) — federal T1 records of every Safe Drinking Water
Act violation by Puerto Rico public water systems (PWSIDs beginning "PR"). Two
tables:
  VIOLATION        the violations (code, category, health-based flag, contaminant,
                   public-notification tier, compliance period, population served)
  GEOGRAPHIC_AREA  pwsid -> city_served / county_served (PR municipios)

Each violation becomes a schema-valid ``service_event`` (event_type=
water_quality_violation). Because ``federation_export`` already projects every
service_event into the canonical entity graph, SDWIS events reach the Hub with no
exporter change. Municipality is resolved against ``data/geo/pr_municipios.geojson``
by unaccented match (county_served is unaccented; canonical names are accented) —
no silent substitution: unmatched -> null.

review_status: health-based violations not yet returned-to-compliance route to
needs_review (G04); resolved/non-health-based -> accepted.

Run (EPA is reachable; sandbox WebFetch may drop the body — use a browser or run
local):
    python scripts/ingest_sdwis_violations.py                       # live
    python scripts/ingest_sdwis_violations.py --src viol.json geo.json   # offline

Merges into data/service_events.jsonl, idempotent: existing EPA-SDWIS rows are
replaced, all other events preserved.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

EFSERVICE = "https://data.epa.gov/efservice"
PAGE = 10000

# SDWIS rule groups that are microbial / pathogen-driven — the contaminations
# that trigger a BOIL-WATER advisory (vs. e.g. nitrate, which is acute but "do
# not boil"). Total Coliform / Revised TCR (100/110/120), Surface Water Treatment
# rules incl. IESWTR/LT1/LT2 (200/210/220/230), Ground Water Rule (410/420).
# There is NO public machine-readable PRASA boil-water feed (the AAA portal is a
# Webflow marketing site with no API), so Tier-1 acute microbial SDWIS notices are
# the authoritative regulatory boil-water signal. Non-microbial acute notices stay
# water_quality_violation (honest: not every Tier-1 notice is "boil the water").
MICROBIAL_RULE_GROUPS = {"100", "110", "120", "200", "210", "220", "230", "410", "420"}
REPO = Path(__file__).resolve().parent.parent
MUNI_GEOJSON = REPO / "data" / "geo" / "pr_municipios.geojson"
SDWIS_SOURCE_PREFIX = "EPA SDWIS VIOLATION"


# ── source acquisition ────────────────────────────────────────────────────────
def _fetch_table_live(table: str) -> list[dict[str, Any]]:
    import httpx

    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        url = f"{EFSERVICE}/{table}/PWSID/BEGINNING/PR/ROWS/{start}:{start + PAGE - 1}/JSON"
        r = httpx.get(url, timeout=120)
        r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        start += PAGE
    return rows


def _read_json_file(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text())
    return doc if isinstance(doc, list) else [doc]


# ── municipality resolution (unaccent match) ──────────────────────────────────
def _unaccent(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)
    ).strip().upper()


def load_muni_canonical(path: Path) -> dict[str, str]:
    """unaccented UPPER name -> canonical accented municipio name."""
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text())
    out: dict[str, str] = {}
    for feat in doc.get("features", []):
        name = (feat.get("properties") or {}).get("name")
        if name:
            out[_unaccent(name)] = name
    return out


def municipality_from_geo(geo_row: dict[str, Any], canon: dict[str, str]) -> str | None:
    """First county_served entry, mapped to a canonical accented municipio."""
    counties = (geo_row or {}).get("county_served") or ""
    for raw in counties.split(","):
        name = raw.strip()
        if name.upper().endswith(" MUNICIPIO"):
            name = name[: -len(" Municipio")].strip()
        canonical = canon.get(_unaccent(name))
        if canonical:
            return canonical
    return None


# ── mapping ───────────────────────────────────────────────────────────────────
def _confidence() -> int:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score

        return int(score("T1", has_coords=True))
    except Exception:
        return 80


def _isodate(raw: Any) -> str | None:
    """'2014-07-01 00:00:00' -> '2014-07-01T00:00:00Z'; None/blank -> None."""
    s = str(raw or "").strip()
    if not s or s.lower() == "null":
        return None
    s = s.replace(" ", "T")
    if "T" not in s:
        s += "T00:00:00"
    return s + "Z"


def build_events(
    violations: list[dict[str, Any]],
    geo_by_pwsid: dict[str, dict[str, Any]],
    canon: dict[str, str],
) -> list[dict]:
    conf = _confidence()
    rows: list[dict] = []
    for v in violations:
        pwsid = (v.get("pwsid") or "").strip()
        vid = (v.get("violation_id") or "").strip()
        if not pwsid or not vid:
            continue
        begin = _isodate(v.get("compl_per_begin_date"))
        day = (begin or "")[:10].replace("-", "")
        if len(day) != 8:
            continue  # event_id pattern requires YYYYMMDD
        geo = geo_by_pwsid.get(pwsid, {})
        muni = municipality_from_geo(geo, canon)
        affected = (geo.get("city_served") or geo.get("county_served") or pwsid).strip() or pwsid
        health = (v.get("is_health_based_ind") or "").strip().upper() == "Y"
        resolved = (v.get("compliance_status_code") or "").strip().upper() == "R"
        try:
            tier = int(v.get("public_notification_tier"))
        except (TypeError, ValueError):
            tier = None
        rule_group = str(v.get("rule_group_code") or "").strip()
        is_boil_water = health and tier == 1 and rule_group in MICROBIAL_RULE_GROUPS
        try:
            pop = int(float(v.get("population_served_count")))
        except (TypeError, ValueError):
            pop = None
        rows.append({
            "event_id": f"AYL_EVT_{day}_{pwsid}_{vid}",
            "event_type": "boil_water" if is_boil_water else "water_quality_violation",
            "affected_area": affected,
            "municipality": muni,
            "zone": None,
            "status_text": (
                f"viol={v.get('violation_code')}/{v.get('violation_category_code')} "
                f"contaminant={v.get('contaminant_code')} health_based={v.get('is_health_based_ind')} "
                f"pn_tier={v.get('public_notification_tier')} compliance={v.get('compliance_status_code')}"
            ),
            "start_time": begin,
            "end_time": _isodate(v.get("compl_per_end_date")),
            "reported_customers_or_users": pop,
            "source_ref": f"{SDWIS_SOURCE_PREFIX} pwsid={pwsid} violation_id={vid}",
            "source_hash": None,
            "evidence_tier": "T1",
            "confidence": conf,
            "review_status": "needs_review" if (health and not resolved) else "accepted",
            "linked_asset_ids": [],
        })
    return rows


# ── merge + write ─────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], sdwis: list[dict]) -> list[dict]:
    """Preserve non-SDWIS events; replace EPA-SDWIS rows (idempotent by event_id)."""
    kept = [e for e in existing if not str(e.get("source_ref", "")).startswith(SDWIS_SOURCE_PREFIX)]
    by_id = {e["event_id"]: e for e in kept}
    for e in sdwis:
        by_id[e["event_id"]] = e
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", nargs="*", type=Path,
                    help="Offline JSON: <violations.json> [geographic_area.json].")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--muni-geojson", default=str(MUNI_GEOJSON))
    args = ap.parse_args()

    if args.src:
        violations = _read_json_file(args.src[0])
        geo_rows = _read_json_file(args.src[1]) if len(args.src) > 1 else []
        origin = ", ".join(str(p) for p in args.src)
    else:
        try:
            violations = _fetch_table_live("VIOLATION")
            geo_rows = _fetch_table_live("GEOGRAPHIC_AREA")
            origin = "live EPA Envirofacts SDWIS"
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <viol.json> [geo.json]", file=sys.stderr)
            return 1

    geo_by_pwsid = {g.get("pwsid"): g for g in geo_rows if g.get("pwsid")}
    canon = load_muni_canonical(Path(args.muni_geojson))
    events = build_events(violations, geo_by_pwsid, canon)

    out = Path(args.out)
    combined = merge(_read_jsonl(out), events)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in combined))

    health = sum(1 for e in events if "health_based=Y" in (e.get("status_text") or ""))
    review = sum(1 for e in events if e["review_status"] == "needs_review")
    with_muni = sum(1 for e in events if e.get("municipality"))
    print(f"source: {origin}")
    print(f"wrote {len(events)} SDWIS violations ({health} health-based, {review} need review, "
          f"{with_muni} with municipality) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
