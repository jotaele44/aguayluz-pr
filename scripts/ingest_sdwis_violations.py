#!/usr/bin/env python3
"""Freeze EPA SDWIS Puerto Rico violations and project them into AguaYLuz.

One acquisition stack serves two consumers:
1. the canonical hazard/advisory plane, with immutable source manifestations,
   source arithmetic, stable PWSID + violation identity, and revision history;
2. the legacy service_events projection retained for compatibility.

A SDWIS violation is a regulatory EVENT. Even a Tier-1 microbial health-based
violation is not promoted to a boil-water/do-not-drink/do-not-use ADVISORY
without an explicit authoritative advisory manifestation from the responsible
authority.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from aguayluz import DATA_DIR
from aguayluz.hazard_adapters.epa_sdwis import normalize
from aguayluz.hazard_plane import HazardRecord, Manifestation, current_records, source_arithmetic

EFSERVICE = "https://data.epa.gov/efservice"
PAGE = 10000
REPO = Path(__file__).resolve().parent.parent
MUNI_GEOJSON = REPO / "data" / "geo" / "pr_municipios.geojson"
SDWIS_SOURCE_PREFIX = "EPA SDWIS VIOLATION"
USER_AGENT = "aguayluz-pr/0.1 EPA-SDWIS-freeze (github.com/jotaele44/aguayluz-pr)"


@dataclass(frozen=True)
class FrozenPage:
    table: str
    url: str
    raw: bytes
    headers: dict[str, str]
    start: int
    end: int


@dataclass(frozen=True)
class OutputPaths:
    raw_root: Path
    records: Path
    manifestations: Path
    ledger: Path
    receipt: Path


def _output_paths(output_root: Path | None) -> OutputPaths:
    if output_root is None:
        return OutputPaths(
            raw_root=DATA_DIR / "hazard_source_snapshots" / "epa_sdwis",
            records=DATA_DIR / "hazard_records.jsonl",
            manifestations=DATA_DIR / "hazard_manifestations.jsonl",
            ledger=DATA_DIR / "hazard_source_accounting.jsonl",
            receipt=DATA_DIR / "epa_sdwis_source_receipt.json",
        )
    return OutputPaths(
        raw_root=output_root / "raw",
        records=output_root / "hazard_records.jsonl",
        manifestations=output_root / "hazard_manifestations.jsonl",
        ledger=output_root / "hazard_source_accounting.jsonl",
        receipt=output_root / "receipt.json",
    )


def _fetch_table_live(
    client: httpx.Client,
    table: str,
    *,
    page_size: int = PAGE,
    max_pages: int = 100,
) -> list[FrozenPage]:
    pages: list[FrozenPage] = []
    start = 0
    for _ in range(max_pages):
        end = start + page_size - 1
        url = f"{EFSERVICE}/{table}/PWSID/BEGINNING/PR/ROWS/{start}:{end}/JSON"
        response = client.get(url)
        response.raise_for_status()
        raw = response.content
        if not raw:
            raise ValueError(f"empty EPA SDWIS response: {url}")
        page = FrozenPage(
            table=table,
            url=str(response.url),
            raw=raw,
            headers={key.lower(): value for key, value in response.headers.items()},
            start=start,
            end=end,
        )
        pages.append(page)
        rows = _parse_rows(page)
        if len(rows) < page_size:
            return pages
        start += page_size
    raise ValueError(f"EPA SDWIS pagination did not exhaust within max_pages={max_pages}")


def _read_json_file(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, list):
        doc = [doc]
    if not all(isinstance(row, dict) for row in doc):
        raise ValueError(f"{path} must contain JSON object rows")
    return doc


def _offline_page(path: Path, table: str) -> FrozenPage:
    raw = path.read_bytes()
    page = FrozenPage(
        table=table,
        url=f"file://{path.resolve()}",
        raw=raw,
        headers={},
        start=0,
        end=max(len(_read_json_file(path)) - 1, 0),
    )
    _parse_rows(page)
    return page


def _parse_rows(page: FrozenPage) -> list[dict[str, Any]]:
    try:
        doc = json.loads(page.raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"EPA SDWIS returned non-JSON bytes for {page.url}") from exc
    if not isinstance(doc, list):
        raise ValueError(f"EPA SDWIS page is not a JSON list: {page.url}")
    if not all(isinstance(row, dict) for row in doc):
        raise ValueError(f"EPA SDWIS page contains non-object rows: {page.url}")
    return doc


def _schema_signature(rows: list[dict[str, Any]]) -> str:
    payload = {
        "container_type": "list",
        "row_keys": sorted({key for row in rows for key in row}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _manifestation(page: FrozenPage, retrieved_at: datetime, ordinal: int) -> Manifestation:
    rows = _parse_rows(page)
    page_sha = sha256(page.raw).hexdigest()
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    return Manifestation(
        manifestation_id=(
            f"EPA_SDWIS:{stamp}:{page.table}:{ordinal:04d}:{page_sha[:20]}"
        ),
        source_authority="U.S. EPA",
        source_system="EPA Envirofacts SDWIS public API",
        source_record_id=f"{page.table}:ROWS:{page.start}:{page.end}",
        source_url=page.url,
        retrieval_query=f"PWSID BEGINNING PR; rows {page.start}:{page.end}",
        retrieved_at_utc=retrieved_at,
        byte_sha256=page_sha,
        schema_signature=_schema_signature(rows),
        record_count=len(rows),
        http_etag=page.headers.get("etag"),
        http_last_modified=page.headers.get("last-modified"),
    )


def _freeze_raw(paths: OutputPaths, page: FrozenPage, manifestation: Manifestation) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", manifestation.manifestation_id)
    target = paths.raw_root / f"{safe}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != page.raw:
        raise ValueError(f"raw snapshot collision at {target}")
    target.write_bytes(page.raw)
    return target.name


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _append_unique_jsonl(path: Path, rows: list[dict[str, Any]], key: str) -> int:
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
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ordered),
        encoding="utf-8",
    )
    return len(by_key) - before


def _existing_current_by_event(path: Path) -> dict[str, HazardRecord]:
    records = [HazardRecord.model_validate(row) for row in _read_jsonl(path)]
    result: dict[str, HazardRecord] = {}
    for row in current_records(records):
        prior = result.get(row.canonical_event_id)
        if prior is not None and prior.record_id != row.record_id:
            raise ValueError(f"multiple current revisions for {row.canonical_event_id}")
        result[row.canonical_event_id] = row
    return result


def classify_violation_row(row: dict[str, Any]) -> tuple[str, str]:
    pwsid = str(row.get("pwsid") or "").strip().upper()
    violation_id = str(row.get("violation_id") or "").strip()
    if not pwsid or not violation_id:
        return "UNRESOLVED", "MISSING_PWSID_OR_VIOLATION_ID"
    if not pwsid.startswith("PR"):
        return "EXCLUDED", "PWSID_OUTSIDE_PUERTO_RICO_PREFIX"
    return "RETAINED", "PR_PWSID_AND_VIOLATION_ID_PRESENT"


# ── municipality resolution retained only for the legacy projection ──────────
def _unaccent(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(char)
    ).strip().upper()


def load_muni_canonical(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for feature in doc.get("features", []):
        name = (feature.get("properties") or {}).get("name")
        if name:
            out[_unaccent(name)] = name
    return out


def municipality_from_geo(
    geo_row: dict[str, Any],
    canon: dict[str, str],
) -> str | None:
    counties = (geo_row or {}).get("county_served") or ""
    for raw in counties.split(","):
        name = raw.strip()
        if name.upper().endswith(" MUNICIPIO"):
            name = name[: -len(" Municipio")].strip()
        canonical = canon.get(_unaccent(name))
        if canonical:
            return canonical
    return None


def _confidence() -> int:
    try:
        sys.path.insert(0, str(REPO / "src"))
        from aguayluz.confidence import score

        return int(score("T1", has_coords=True))
    except Exception:
        return 80


def _isodate(raw: Any) -> str | None:
    """Preserve historical legacy shape while recording DATE_ONLY canonically."""
    text = str(raw or "").strip()
    if not text or text.casefold() == "null":
        return None
    text = text.replace(" ", "T")
    if "T" not in text:
        text += "T00:00:00"
    return text + "Z"


def build_events(
    violations: list[dict[str, Any]],
    geo_by_pwsid: dict[str, dict[str, Any]],
    canon: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the compatibility service_event projection without advisory inference."""
    confidence = _confidence()
    rows: list[dict[str, Any]] = []
    for violation in violations:
        disposition, _ = classify_violation_row(violation)
        if disposition != "RETAINED":
            continue
        pwsid = str(violation.get("pwsid") or "").strip().upper()
        violation_id = str(violation.get("violation_id") or "").strip()
        begin = _isodate(violation.get("compl_per_begin_date"))
        day = (begin or "")[:10].replace("-", "")
        if len(day) != 8:
            continue
        geo = geo_by_pwsid.get(pwsid, {})
        municipality = municipality_from_geo(geo, canon)
        affected = (
            geo.get("city_served") or geo.get("county_served") or pwsid
        ).strip() or pwsid
        health = str(violation.get("is_health_based_ind") or "").strip().upper() == "Y"
        resolved = (
            str(violation.get("compliance_status_code") or "").strip().upper() == "R"
        )
        try:
            population = int(float(violation.get("population_served_count")))
        except (TypeError, ValueError):
            population = None
        rows.append(
            {
                "event_id": f"AYL_EVT_{day}_{pwsid}_{violation_id}",
                "event_type": "water_quality_violation",
                "affected_area": affected,
                "municipality": municipality,
                "zone": None,
                "status_text": (
                    f"viol={violation.get('violation_code')}/"
                    f"{violation.get('violation_category_code')} "
                    f"contaminant={violation.get('contaminant_code')} "
                    f"health_based={violation.get('is_health_based_ind')} "
                    f"pn_tier={violation.get('public_notification_tier')} "
                    f"compliance={violation.get('compliance_status_code')} "
                    "advisory=not_established_by_sdwis_violation_alone"
                ),
                "start_time": begin,
                "end_time": _isodate(violation.get("compl_per_end_date")),
                "reported_customers_or_users": population,
                "source_ref": (
                    f"{SDWIS_SOURCE_PREFIX} pwsid={pwsid} violation_id={violation_id}"
                ),
                "source_hash": None,
                "evidence_tier": "T1",
                "confidence": confidence,
                "review_status": "needs_review" if (health and not resolved) else "accepted",
                "linked_asset_ids": [],
            }
        )
    return rows


def merge(existing: list[dict[str, Any]], sdwis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [
        event
        for event in existing
        if not str(event.get("source_ref", "")).startswith(SDWIS_SOURCE_PREFIX)
    ]
    by_id = {event["event_id"]: event for event in kept}
    for event in sdwis:
        by_id[event["event_id"]] = event
    return list(by_id.values())


def process_pages(
    violation_pages: list[FrozenPage],
    geography_pages: list[FrozenPage],
    *,
    output_root: Path | None,
    retrieved_at: datetime,
    require_zero_unresolved: bool,
    write_legacy: bool,
    legacy_out: Path,
    muni_geojson: Path,
) -> dict[str, Any]:
    paths = _output_paths(output_root)
    existing_current = _existing_current_by_event(paths.records)
    current_in_snapshot: dict[str, str] = {}
    manifestations: list[Manifestation] = []
    new_records: list[HazardRecord] = []
    classifications: list[dict[str, Any]] = []
    retained_rows: list[dict[str, Any]] = []
    geo_rows: list[dict[str, Any]] = []
    frozen_files: list[dict[str, Any]] = []

    ordinal = 0
    page_manifestations: dict[tuple[str, int, int], Manifestation] = {}
    for page in [*violation_pages, *geography_pages]:
        ordinal += 1
        manifestation = _manifestation(page, retrieved_at, ordinal)
        manifestations.append(manifestation)
        page_manifestations[(page.table, page.start, page.end)] = manifestation
        raw_file = _freeze_raw(paths, page, manifestation)
        frozen_files.append(
            {
                "manifestation_id": manifestation.manifestation_id,
                "table": page.table,
                "source_url": manifestation.source_url,
                "byte_sha256": manifestation.byte_sha256,
                "record_count": manifestation.record_count,
                "raw_file": raw_file,
            }
        )
        if page.table == "GEOGRAPHIC_AREA":
            geo_rows.extend(_parse_rows(page))

    for page in violation_pages:
        manifestation = page_manifestations[(page.table, page.start, page.end)]
        for source_ordinal, source_row in enumerate(_parse_rows(page), start=page.start):
            disposition, reason = classify_violation_row(source_row)
            classification: dict[str, Any] = {
                "source_ordinal": source_ordinal,
                "manifestation_id": manifestation.manifestation_id,
                "pwsid": source_row.get("pwsid"),
                "violation_id": source_row.get("violation_id"),
                "source_row_sha256": sha256(
                    json.dumps(
                        source_row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "disposition": disposition,
                "reason": reason,
            }
            if disposition != "RETAINED":
                classifications.append(classification)
                continue

            try:
                candidate = normalize(source_row, manifestation.manifestation_id)
            except (TypeError, ValueError) as exc:
                classification["disposition"] = "UNRESOLVED"
                classification["reason"] = f"NORMALIZATION_FAILED:{type(exc).__name__}"
                classifications.append(classification)
                continue

            snapshot_record_id = current_in_snapshot.get(candidate.canonical_event_id)
            if snapshot_record_id is not None and snapshot_record_id != candidate.record_id:
                classification["disposition"] = "UNRESOLVED"
                classification["reason"] = "CONFLICTING_DUPLICATE_IDENTITY_IN_SNAPSHOT"
                classifications.append(classification)
                continue

            previous = existing_current.get(candidate.canonical_event_id)
            if previous is not None and previous.record_id != candidate.record_id:
                candidate = normalize(
                    source_row,
                    manifestation.manifestation_id,
                    supersedes_record_id=previous.record_id,
                )

            current_in_snapshot[candidate.canonical_event_id] = candidate.record_id
            retained_rows.append(source_row)
            classifications.append(classification)

            if previous is not None and previous.record_id == candidate.record_id:
                continue
            if not any(row.record_id == candidate.record_id for row in new_records):
                new_records.append(candidate)
                existing_current[candidate.canonical_event_id] = candidate

    retained = sum(row["disposition"] == "RETAINED" for row in classifications)
    excluded = sum(row["disposition"] == "EXCLUDED" for row in classifications)
    unresolved = sum(row["disposition"] == "UNRESOLVED" for row in classifications)
    accounting = source_arithmetic(len(classifications), retained, excluded, unresolved)
    receipt = {
        "schema_version": "aguayluz.epa_sdwis_source_freeze/v1",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "source_endpoint": EFSERVICE,
        "query_scope": "VIOLATION rows where PWSID begins with PR",
        "source_denominator": "every returned VIOLATION row in the bounded live snapshot",
        "violation_pages_frozen": len(violation_pages),
        "geography_pages_frozen": len(geography_pages),
        "manifestations_frozen": len(manifestations),
        "new_record_revisions": len(new_records),
        "unique_current_events_in_snapshot": len(current_in_snapshot),
        "frozen_files": frozen_files,
        "source_arithmetic": accounting,
        "certification_state": (
            "PASS" if accounting["state"] == "PASS" and unresolved == 0 else "OPEN"
        ),
        "semantic_guardrails": {
            "sdwis_violation_is_advisory": False,
            "tier1_microbial_implies_boil_water_advisory": False,
            "pwsid_is_authoritative_water_system_identity": True,
            "municipality_text_is_canonical_binding": False,
            "absence_of_reported_violation_proves_safety": False,
        },
        "classifications": classifications,
    }
    if accounting["state"] != "PASS":
        raise ValueError(f"source arithmetic failed: {accounting}")

    _append_unique_jsonl(
        paths.manifestations,
        [row.model_dump(mode="json") for row in manifestations],
        "manifestation_id",
    )
    _append_unique_jsonl(
        paths.records,
        [row.model_dump(mode="json") for row in new_records],
        "record_id",
    )
    paths.ledger.parent.mkdir(parents=True, exist_ok=True)
    with paths.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    paths.receipt.parent.mkdir(parents=True, exist_ok=True)
    paths.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if write_legacy:
        geo_by_pwsid = {
            str(row.get("pwsid") or "").strip().upper(): row
            for row in geo_rows
            if row.get("pwsid")
        }
        canon = load_muni_canonical(muni_geojson)
        legacy_events = build_events(retained_rows, geo_by_pwsid, canon)
        combined = merge(_read_jsonl(legacy_out), legacy_events)
        legacy_out.parent.mkdir(parents=True, exist_ok=True)
        legacy_out.write_text(
            "".join(json.dumps(row) + "\n" for row in combined),
            encoding="utf-8",
        )
        receipt["legacy_projection"] = {
            "path": str(legacy_out),
            "sdwis_events": len(legacy_events),
            "total_events": len(combined),
            "boil_water_advisories_inferred": 0,
        }
        paths.receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if require_zero_unresolved and unresolved:
        raise ValueError(f"EPA SDWIS source denominator has {unresolved} unresolved row(s)")
    return receipt


def run(
    *,
    output_root: Path | None,
    max_pages: int,
    require_zero_unresolved: bool,
    write_legacy: bool,
    legacy_out: Path,
    muni_geojson: Path,
    offline_sources: list[Path] | None = None,
) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    if offline_sources:
        violation_pages = [_offline_page(offline_sources[0], "VIOLATION")]
        geography_pages = (
            [_offline_page(offline_sources[1], "GEOGRAPHIC_AREA")]
            if len(offline_sources) > 1
            else []
        )
    else:
        with httpx.Client(
            timeout=120,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            violation_pages = _fetch_table_live(
                client,
                "VIOLATION",
                max_pages=max_pages,
            )
            geography_pages = _fetch_table_live(
                client,
                "GEOGRAPHIC_AREA",
                max_pages=max_pages,
            )
    return process_pages(
        violation_pages,
        geography_pages,
        output_root=output_root,
        retrieved_at=retrieved_at,
        require_zero_unresolved=require_zero_unresolved,
        write_legacy=write_legacy,
        legacy_out=legacy_out,
        muni_geojson=muni_geojson,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        nargs="*",
        type=Path,
        help="Offline JSON: <violations.json> [geographic_area.json].",
    )
    parser.add_argument("--out", type=Path, default=Path("data/service_events.jsonl"))
    parser.add_argument("--muni-geojson", type=Path, default=MUNI_GEOJSON)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--require-zero-unresolved", action="store_true")
    parser.add_argument("--no-legacy", action="store_true")
    args = parser.parse_args()

    try:
        receipt = run(
            output_root=args.output_root,
            max_pages=args.max_pages,
            require_zero_unresolved=args.require_zero_unresolved,
            write_legacy=not args.no_legacy,
            legacy_out=args.out,
            muni_geojson=args.muni_geojson,
            offline_sources=args.src,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"EPA SDWIS ingestion failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
