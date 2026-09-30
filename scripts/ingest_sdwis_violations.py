#!/usr/bin/env python3
"""Ingest Puerto Rico EPA SDWIS drinking-water violations.

One keyless source acquisition feeds two deliberately different consumers:

* the legacy operational service_events.jsonl projection; and
* the canonical hazard plane, where an SDWIS violation remains a regulatory
  EVENT and is never promoted to an issued boil-water/do-not-drink/do-not-use
  advisory from public-notification tier alone.

The live denominator is every Envirofacts SDWIS VIOLATION row whose PWSID begins
PR plus the supporting GEOGRAPHIC_AREA rows. Exact response bytes are frozen
before normalization, source manifestations retain SHA-256/schema metadata, and
each table closes SOURCE = RETAINED + EXCLUDED + UNRESOLVED.

EPA/ECHO drinking-water compliance data are not real-time and may lag source
events by multiple months. That latency is retained in the canonical record
semantics rather than treated as event time.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from aguayluz.hazard_adapters.epa_sdwis import (
    MICROBIAL_RULE_GROUPS,
    canonical_event_id,
    normalize as normalize_hazard,
)
from aguayluz.hazard_plane import (
    HazardRecord,
    Manifestation,
    current_records,
    source_arithmetic,
)

EFSERVICE = "https://data.epa.gov/efservice"
PAGE = 10000
REPO = Path(__file__).resolve().parent.parent
MUNI_GEOJSON = REPO / "data" / "geo" / "pr_municipios.geojson"
SDWIS_SOURCE_PREFIX = "EPA SDWIS VIOLATION"

HAZARD_RAW_ROOT = REPO / "data" / "hazard_source_snapshots" / "epa_sdwis"
HAZARD_RECORDS_PATH = REPO / "data" / "hazard_records.jsonl"
HAZARD_MANIFESTATIONS_PATH = REPO / "data" / "hazard_manifestations.jsonl"
HAZARD_LEDGER_PATH = REPO / "data" / "hazard_source_accounting.jsonl"

SourcePage = tuple[str, bytes, dict[str, str]]


def _fetch_table_pages(table: str) -> list[SourcePage]:
    import httpx

    pages: list[SourcePage] = []
    start = 0
    while True:
        url = f"{EFSERVICE}/{table}/PWSID/BEGINNING/PR/ROWS/{start}:{start + PAGE - 1}/JSON"
        response = httpx.get(url, timeout=120)
        response.raise_for_status()
        raw = response.content
        batch = json.loads(raw)
        if not isinstance(batch, list):
            raise ValueError(f"{table} response is not a list")
        if not batch:
            break
        pages.append((url, raw, dict(response.headers)))
        if len(batch) < PAGE:
            break
        start += PAGE
    return pages


def _fetch_table_live(table: str) -> list[dict[str, Any]]:
    """Backward-compatible parsed-row helper."""
    return _rows_from_pages(_fetch_table_pages(table), table)


def _offline_pages(path: Path) -> list[SourcePage]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, list):
        payload = [payload]
    canonical = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return [(str(path), canonical, {})]


def _rows_from_pages(pages: list[SourcePage], table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, raw, _ in pages:
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError(f"{table} source page is not a list")
        rows.extend(row for row in payload if isinstance(row, dict))
    return rows


def _read_json_file(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text())
    return doc if isinstance(doc, list) else [doc]


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


def _municipality_candidates(
    geo_rows: list[dict[str, Any]],
    canon: dict[str, str],
) -> list[str]:
    candidates: set[str] = set()
    for geo_row in geo_rows:
        counties = str((geo_row or {}).get("county_served") or "")
        for raw in counties.split(","):
            name = raw.strip()
            if name.upper().endswith(" MUNICIPIO"):
                name = name[: -len(" Municipio")].strip()
            canonical = canon.get(_unaccent(name))
            if canonical:
                candidates.add(canonical)
    return sorted(candidates)


def municipality_from_geo(geo_row: dict[str, Any], canon: dict[str, str]) -> str | None:
    """First county_served entry, mapped to a canonical accented municipio."""
    candidates = _municipality_candidates([geo_row], canon)
    return candidates[0] if candidates else None


def _confidence() -> int:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score

        return int(score("T1", has_coords=True))
    except Exception:
        return 80


def _isodate(raw: Any) -> str | None:
    """Normalize an SDWIS datetime string to UTC ISO text."""
    value = str(raw or "").strip()
    if not value or value.lower() == "null":
        return None
    value = value.replace(" ", "T")
    if "T" not in value:
        value += "T00:00:00"
    return value + "Z"


def build_events(
    violations: list[dict[str, Any]],
    geo_by_pwsid: dict[str, dict[str, Any]],
    canon: dict[str, str],
) -> list[dict]:
    """Preserve the existing legacy operational service-event projection."""
    conf = _confidence()
    rows: list[dict] = []
    for violation in violations:
        pwsid = (violation.get("pwsid") or "").strip()
        violation_id = (violation.get("violation_id") or "").strip()
        if not pwsid or not violation_id:
            continue
        begin = _isodate(violation.get("compl_per_begin_date"))
        day = (begin or "")[:10].replace("-", "")
        if len(day) != 8:
            continue
        geo = geo_by_pwsid.get(pwsid, {})
        muni = municipality_from_geo(geo, canon)
        affected = (
            geo.get("city_served") or geo.get("county_served") or pwsid
        ).strip() or pwsid
        health = (violation.get("is_health_based_ind") or "").strip().upper() == "Y"
        resolved = (violation.get("compliance_status_code") or "").strip().upper() == "R"
        try:
            tier = int(violation.get("public_notification_tier"))
        except (TypeError, ValueError):
            tier = None
        rule_group = str(violation.get("rule_group_code") or "").strip()
        is_boil_water = health and tier == 1 and rule_group in MICROBIAL_RULE_GROUPS
        try:
            pop = int(float(violation.get("population_served_count")))
        except (TypeError, ValueError):
            pop = None
        rows.append(
            {
                "event_id": f"AYL_EVT_{day}_{pwsid}_{violation_id}",
                "event_type": "boil_water" if is_boil_water else "water_quality_violation",
                "affected_area": affected,
                "municipality": muni,
                "zone": None,
                "status_text": (
                    f"viol={violation.get('violation_code')}/{violation.get('violation_category_code')} "
                    f"contaminant={violation.get('contaminant_code')} "
                    f"health_based={violation.get('is_health_based_ind')} "
                    f"pn_tier={violation.get('public_notification_tier')} "
                    f"compliance={violation.get('compliance_status_code')}"
                ),
                "start_time": begin,
                "end_time": _isodate(violation.get("compl_per_end_date")),
                "reported_customers_or_users": pop,
                "source_ref": (
                    f"{SDWIS_SOURCE_PREFIX} pwsid={pwsid} violation_id={violation_id}"
                ),
                "source_hash": None,
                "evidence_tier": "T1",
                "confidence": conf,
                "review_status": "needs_review" if (health and not resolved) else "accepted",
                "linked_asset_ids": [],
            }
        )
    return rows


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"non-object JSONL row in {path}")
        rows.append(row)
    return rows


def _append_unique_jsonl(
    path: Path,
    rows: list[dict[str, Any]],
    key: str,
) -> int:
    existing = _read_jsonl(path)
    by_key = {str(row[key]): row for row in existing if row.get(key) is not None}
    before = len(by_key)
    for row in rows:
        row_key = str(row[key])
        prior = by_key.get(row_key)
        if prior is not None and prior != row:
            raise ValueError(f"identity collision for {key}={row_key}")
        by_key[row_key] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(by_key.values(), key=lambda row: str(row[key]))
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in ordered
        ),
        encoding="utf-8",
    )
    return len(by_key) - before


def _existing_current_by_event() -> dict[str, HazardRecord]:
    records = [
        HazardRecord.model_validate(row)
        for row in _read_jsonl(HAZARD_RECORDS_PATH)
    ]
    result: dict[str, HazardRecord] = {}
    for row in current_records(records):
        prior = result.get(row.canonical_event_id)
        if prior is not None and prior.record_id != row.record_id:
            raise ValueError(f"multiple current revisions for {row.canonical_event_id}")
        result[row.canonical_event_id] = row
    return result


def _manifestation(
    *,
    table: str,
    page_number: int,
    url: str,
    raw: bytes,
    headers: dict[str, str],
    retrieved_at: datetime,
    stamp: str,
) -> Manifestation:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError(f"{table} source page is not a list")
    row_keys = sorted(
        {
            key
            for row in payload
            if isinstance(row, dict)
            for key in row
        }
    )
    page_sha = sha256(raw).hexdigest()
    return Manifestation(
        manifestation_id=f"EPA_SDWIS:{table}:{stamp}:P{page_number:04d}:{page_sha[:20]}",
        source_authority="EPA",
        source_system="Envirofacts SDWIS",
        source_record_id=f"{table}:page-{page_number}",
        source_url=url,
        retrieval_query=url,
        retrieved_at_utc=retrieved_at,
        byte_sha256=page_sha,
        schema_signature=sha256(_canonical_json_bytes(row_keys)).hexdigest(),
        record_count=len(payload),
        http_etag=headers.get("etag"),
        http_last_modified=headers.get("last-modified"),
    )


def _freeze_page(
    table: str,
    page_number: int,
    raw: bytes,
    stamp: str,
) -> None:
    page_sha = sha256(raw).hexdigest()
    path = (
        HAZARD_RAW_ROOT
        / stamp
        / table.lower()
        / f"page-{page_number:04d}-{page_sha}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f"snapshot collision at {path}")
    path.write_bytes(raw)


def _row_disposition(row: Any, *, require_violation_id: bool) -> str:
    if not isinstance(row, dict):
        return "UNRESOLVED"
    pwsid = str(row.get("pwsid") or "").strip().upper()
    if not pwsid:
        return "UNRESOLVED"
    if not pwsid.startswith("PR"):
        return "EXCLUDED"
    if require_violation_id and not str(row.get("violation_id") or "").strip():
        return "UNRESOLVED"
    return "RETAINED"


def materialize_hazard_plane(
    violation_pages: list[SourcePage],
    geo_pages: list[SourcePage],
    canon: dict[str, str],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    existing_current = _existing_current_by_event()
    manifestations: list[Manifestation] = []
    records: list[HazardRecord] = []

    geo_rows_by_pwsid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    geo_manifestations_by_pwsid: dict[str, list[str]] = defaultdict(list)

    geo_counts = {"source": 0, "retained": 0, "excluded": 0, "unresolved": 0}
    for page_number, (url, raw, headers) in enumerate(geo_pages, start=1):
        manifest = _manifestation(
            table="GEOGRAPHIC_AREA",
            page_number=page_number,
            url=url,
            raw=raw,
            headers=headers,
            retrieved_at=retrieved_at,
            stamp=stamp,
        )
        manifestations.append(manifest)
        if not dry_run:
            _freeze_page("GEOGRAPHIC_AREA", page_number, raw, stamp)
        payload = json.loads(raw)
        for row in payload:
            geo_counts["source"] += 1
            disposition = _row_disposition(row, require_violation_id=False)
            geo_counts[disposition.lower()] += 1
            if disposition != "RETAINED":
                continue
            pwsid = str(row["pwsid"]).strip().upper()
            geo_rows_by_pwsid[pwsid].append(row)
            geo_manifestations_by_pwsid[pwsid].append(manifest.manifestation_id)

    violation_counts = {"source": 0, "retained": 0, "excluded": 0, "unresolved": 0}
    seen_rows: set[str] = set()
    for page_number, (url, raw, headers) in enumerate(violation_pages, start=1):
        manifest = _manifestation(
            table="VIOLATION",
            page_number=page_number,
            url=url,
            raw=raw,
            headers=headers,
            retrieved_at=retrieved_at,
            stamp=stamp,
        )
        manifestations.append(manifest)
        if not dry_run:
            _freeze_page("VIOLATION", page_number, raw, stamp)
        payload = json.loads(raw)
        for row in payload:
            violation_counts["source"] += 1
            disposition = _row_disposition(row, require_violation_id=True)
            violation_counts[disposition.lower()] += 1
            if disposition != "RETAINED":
                continue
            row_sha = sha256(_canonical_json_bytes(row)).hexdigest()
            if row_sha in seen_rows:
                raise ValueError(f"duplicate SDWIS violation source row: {row_sha}")
            seen_rows.add(row_sha)

            pwsid = str(row["pwsid"]).strip().upper()
            geo_rows = geo_rows_by_pwsid.get(pwsid, [])
            municipality_candidates = _municipality_candidates(geo_rows, canon)
            municipality_name = (
                municipality_candidates[0]
                if len(municipality_candidates) == 1
                else None
            )
            geo_manifestation_ids = geo_manifestations_by_pwsid.get(pwsid, [])
            candidate = normalize_hazard(
                row,
                manifest.manifestation_id,
                geo_rows=geo_rows,
                municipality_name=municipality_name,
                geography_manifestation_ids=geo_manifestation_ids,
            )
            candidate.raw_attributes["municipality_candidates"] = municipality_candidates
            candidate.raw_attributes["geography_binding_state"] = (
                "1:1"
                if len(municipality_candidates) == 1
                else "1:N"
                if municipality_candidates
                else "UNRESOLVED"
            )

            event_id = canonical_event_id(row)
            previous = existing_current.get(event_id)
            if previous is not None:
                if previous.record_id == candidate.record_id:
                    continue
                candidate = normalize_hazard(
                    row,
                    manifest.manifestation_id,
                    geo_rows=geo_rows,
                    municipality_name=municipality_name,
                    geography_manifestation_ids=geo_manifestation_ids,
                    supersedes_record_id=previous.record_id,
                )
                candidate.raw_attributes["municipality_candidates"] = municipality_candidates
                candidate.raw_attributes["geography_binding_state"] = (
                    "1:1"
                    if len(municipality_candidates) == 1
                    else "1:N"
                    if municipality_candidates
                    else "UNRESOLVED"
                )
            records.append(candidate)
            existing_current[event_id] = candidate

    arithmetic = {
        "VIOLATION": source_arithmetic(
            violation_counts["source"],
            violation_counts["retained"],
            violation_counts["excluded"],
            violation_counts["unresolved"],
        ),
        "GEOGRAPHIC_AREA": source_arithmetic(
            geo_counts["source"],
            geo_counts["retained"],
            geo_counts["excluded"],
            geo_counts["unresolved"],
        ),
    }
    if any(item["state"] != "PASS" for item in arithmetic.values()):
        raise ValueError(f"SDWIS source arithmetic failed: {arithmetic}")

    result = {
        "source_family": "EPA_DRINKING_WATER_HEALTH",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "source_arithmetic": arithmetic,
        "new_record_revisions": len(records),
        "manifestations": len(manifestations),
        "advisory_issuance_claimed": False,
        "enforcement_action_denominator_closed": False,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    _append_unique_jsonl(
        HAZARD_MANIFESTATIONS_PATH,
        [row.model_dump(mode="json") for row in manifestations],
        "manifestation_id",
    )
    _append_unique_jsonl(
        HAZARD_RECORDS_PATH,
        [row.model_dump(mode="json") for row in records],
        "record_id",
    )
    HAZARD_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HAZARD_LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return result


def merge(existing: list[dict], sdwis: list[dict]) -> list[dict]:
    """Preserve non-SDWIS events; replace EPA-SDWIS rows by event_id."""
    kept = [
        event
        for event in existing
        if not str(event.get("source_ref", "")).startswith(SDWIS_SOURCE_PREFIX)
    ]
    by_id = {event["event_id"]: event for event in kept}
    for event in sdwis:
        by_id[event["event_id"]] = event
    return list(by_id.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        nargs="*",
        type=Path,
        help="Offline JSON: <violations.json> [geographic_area.json].",
    )
    parser.add_argument("--out", default="data/service_events.jsonl")
    parser.add_argument("--muni-geojson", default=str(MUNI_GEOJSON))
    parser.add_argument("--no-hazard-plane", action="store_true")
    parser.add_argument("--hazard-dry-run", action="store_true")
    args = parser.parse_args()

    if args.src:
        violation_pages = _offline_pages(args.src[0])
        geo_pages = _offline_pages(args.src[1]) if len(args.src) > 1 else []
        origin = ", ".join(str(path) for path in args.src)
    else:
        try:
            violation_pages = _fetch_table_pages("VIOLATION")
            geo_pages = _fetch_table_pages("GEOGRAPHIC_AREA")
            origin = "live EPA Envirofacts SDWIS"
        except Exception as exc:  # noqa: BLE001
            print(
                f"live fetch failed ({exc}); pass --src <viol.json> [geo.json]",
                file=sys.stderr,
            )
            return 1

    violations = _rows_from_pages(violation_pages, "VIOLATION")
    geo_rows = _rows_from_pages(geo_pages, "GEOGRAPHIC_AREA")
    geo_by_pwsid = {
        row.get("pwsid"): row
        for row in geo_rows
        if row.get("pwsid")
    }
    canon = load_muni_canonical(Path(args.muni_geojson))
    events = build_events(violations, geo_by_pwsid, canon)

    out = Path(args.out)
    combined = merge(_read_jsonl(out), events)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(row) + "\n" for row in combined),
        encoding="utf-8",
    )

    hazard_result: dict[str, Any] | None = None
    if not args.no_hazard_plane:
        hazard_result = materialize_hazard_plane(
            violation_pages,
            geo_pages,
            canon,
            dry_run=args.hazard_dry_run,
        )

    health = sum(
        1
        for event in events
        if "health_based=Y" in (event.get("status_text") or "")
    )
    review = sum(1 for event in events if event["review_status"] == "needs_review")
    with_muni = sum(1 for event in events if event.get("municipality"))
    print(f"source: {origin}")
    print(
        f"wrote {len(events)} SDWIS violations "
        f"({health} health-based, {review} need review, "
        f"{with_muni} with municipality) -> {out}"
    )
    print(f"  total events in file: {len(combined)}")
    if hazard_result is not None:
        print(json.dumps(hazard_result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
