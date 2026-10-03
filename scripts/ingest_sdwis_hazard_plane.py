#!/usr/bin/env python3
"""Freeze and ingest EPA SDWIS Puerto Rico drinking-water violation observations.

The bounded source universe is the authoritative SDWIS VIOLATION query for PWSIDs
beginning "PR". Exact response bytes are frozen before normalization. A target
calendar year is then classified without using text search:

SOURCE = RETAINED + EXCLUDED + UNRESOLVED

Only health-based target-year violations are retained in the canonical hazard plane.
They are OBSERVATION records, never inferred boil-water/do-not-drink/do-not-use
ADVISORY records. Public-notification tier remains source metadata only.
"""
from __future__ import annotations

import argparse
import json
import sys
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
TABLE = "VIOLATION"
PAGE = 10000
USER_AGENT = "aguayluz-pr/0.1 SDWIS-hazard-freeze (github.com/jotaele44/aguayluz-pr)"


@dataclass(frozen=True)
class FrozenPage:
    url: str
    raw: bytes
    headers: dict[str, str]
    start: int


@dataclass(frozen=True)
class OutputPaths:
    raw_root: Path
    records: Path
    manifestations: Path
    ledger: Path
    receipt: Path


def _page_url(start: int, page_size: int = PAGE) -> str:
    end = start + page_size - 1
    return f"{EFSERVICE}/{TABLE}/PWSID/BEGINNING/PR/ROWS/{start}:{end}/JSON"


def _decode_rows(raw: bytes) -> list[dict[str, Any]]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("SDWIS VIOLATION response must be a JSON array")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"SDWIS row {index} is not a JSON object")
        rows.append(row)
    return rows


def fetch_pages(
    client: httpx.Client,
    *,
    page_size: int = PAGE,
    max_pages: int = 1000,
) -> list[FrozenPage]:
    """Fetch the complete PR VIOLATION query and detect mutation during pagination."""
    pages: list[FrozenPage] = []
    start = 0
    for _ in range(max_pages):
        url = _page_url(start, page_size)
        response = client.get(url)
        response.raise_for_status()
        raw = response.content
        rows = _decode_rows(raw)
        pages.append(FrozenPage(url=url, raw=raw, headers=dict(response.headers), start=start))
        if len(rows) < page_size:
            break
        start += len(rows)
    else:
        raise ValueError(f"SDWIS pagination exceeded max_pages={max_pages}")

    if not pages:
        raise ValueError("SDWIS source returned no page")
    first_check = client.get(pages[0].url)
    first_check.raise_for_status()
    if sha256(first_check.content).hexdigest() != sha256(pages[0].raw).hexdigest():
        raise ValueError("SDWIS source changed during pagination; retry from a fresh snapshot")
    return pages


def load_offline(paths: list[Path]) -> list[FrozenPage]:
    pages: list[FrozenPage] = []
    for index, path in enumerate(paths):
        raw = path.read_bytes()
        _decode_rows(raw)
        pages.append(FrozenPage(url=str(path), raw=raw, headers={}, start=index * PAGE))
    if not pages:
        raise ValueError("at least one offline source page is required")
    return pages


def _parse_begin_year(row: dict[str, Any]) -> int | None:
    raw = str(row.get("compl_per_begin_date") or "").strip()
    if not raw or raw.casefold() == "null":
        return None
    try:
        return int(raw[:4])
    except (TypeError, ValueError):
        return None


def classify_row(row: dict[str, Any], target_year: int) -> tuple[str, str]:
    """Classify one authoritative source row into the bounded target-year denominator."""
    pwsid = str(row.get("pwsid") or "").strip().upper()
    violation_id = str(row.get("violation_id") or "").strip()
    if not pwsid or not violation_id:
        return "UNRESOLVED", "MISSING_STABLE_SOURCE_ID"
    if not pwsid.startswith("PR"):
        return "UNRESOLVED", "QUERY_SCOPE_VIOLATION_NON_PR_PWSID"

    begin_year = _parse_begin_year(row)
    if begin_year is None:
        return "UNRESOLVED", "COMPLIANCE_BEGIN_DATE_UNRESOLVED"
    if begin_year != target_year:
        return "EXCLUDED", "OUTSIDE_TARGET_YEAR"

    health = str(row.get("is_health_based_ind") or "").strip().upper()
    if health == "Y":
        return "RETAINED", "TARGET_YEAR_HEALTH_BASED_VIOLATION"
    if health == "N":
        return "EXCLUDED", "TARGET_YEAR_NON_HEALTH_BASED_VIOLATION"
    return "UNRESOLVED", "TARGET_YEAR_HEALTH_CLASS_UNRESOLVED"


def _schema_signature(rows: list[dict[str, Any]]) -> str:
    keys = sorted({key for row in rows for key in row})
    payload = json.dumps({"row_keys": keys}, sort_keys=True, separators=(",", ":")).encode()
    return sha256(payload).hexdigest()


def _output_paths(output_root: Path | None) -> OutputPaths:
    if output_root is None:
        return OutputPaths(
            raw_root=DATA_DIR / "hazard_source_snapshots" / "epa_sdwis_violations",
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


def process_pages(
    pages: list[FrozenPage],
    *,
    year: int,
    output_root: Path | None = None,
    require_zero_unresolved: bool = False,
) -> dict[str, Any]:
    paths = _output_paths(output_root)
    retrieved_at = datetime.now(timezone.utc)
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    existing_current = _existing_current_by_event(paths.records)

    manifestations: list[Manifestation] = []
    new_records: list[HazardRecord] = []
    frozen_files: list[dict[str, Any]] = []
    source_count = 0
    retained_source = 0
    excluded = 0
    unresolved = 0
    classifications: dict[str, int] = {}
    seen_source_ids: set[tuple[str, str]] = set()

    for page_number, page in enumerate(pages, start=1):
        rows = _decode_rows(page.raw)
        page_sha = sha256(page.raw).hexdigest()
        source_count += len(rows)

        manifestation_id = f"EPA_SDWIS:{stamp}:P{page_number:04d}:{page_sha[:20]}"
        manifestation = Manifestation(
            manifestation_id=manifestation_id,
            source_authority="EPA",
            source_system="SDWIS/Fed Envirofacts VIOLATION",
            source_record_id=f"VIOLATION-page-{page_number}",
            source_url=page.url,
            retrieval_query="PWSID begins PR",
            retrieved_at_utc=retrieved_at,
            byte_sha256=page_sha,
            schema_signature=_schema_signature(rows),
            record_count=len(rows),
            http_etag=page.headers.get("etag"),
            http_last_modified=page.headers.get("last-modified"),
        )
        manifestations.append(manifestation)

        raw_path = paths.raw_root / stamp / f"page-{page_number:04d}-{page_sha}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists() and raw_path.read_bytes() != page.raw:
            raise ValueError(f"snapshot collision at {raw_path}")
        raw_path.write_bytes(page.raw)
        frozen_files.append({
            "manifestation_id": manifestation_id,
            "byte_sha256": page_sha,
            "raw_file": str(raw_path),
            "record_count": len(rows),
            "source_url": page.url,
        })

        for source_row in rows:
            pwsid = str(source_row.get("pwsid") or "").strip().upper()
            violation_id = str(source_row.get("violation_id") or "").strip()
            if pwsid and violation_id:
                source_id = (pwsid, violation_id)
                if source_id in seen_source_ids:
                    raise ValueError(f"duplicate SDWIS source identity across pages: {pwsid}:{violation_id}")
                seen_source_ids.add(source_id)

            disposition, reason = classify_row(source_row, year)
            classifications[reason] = classifications.get(reason, 0) + 1
            if disposition == "EXCLUDED":
                excluded += 1
                continue
            if disposition == "UNRESOLVED":
                unresolved += 1
                continue

            retained_source += 1
            candidate = normalize(source_row, manifestation_id)
            previous = existing_current.get(candidate.canonical_event_id)
            if previous is not None:
                if previous.record_id == candidate.record_id:
                    continue
                candidate = normalize(
                    source_row,
                    manifestation_id,
                    supersedes_record_id=previous.record_id,
                )
            new_records.append(candidate)
            existing_current[candidate.canonical_event_id] = candidate

    accounting = source_arithmetic(source_count, retained_source, excluded, unresolved)
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

    certification_state = "PASS" if unresolved == 0 else "OPEN"
    receipt = {
        "schema_version": "aguayluz.epa_sdwis_hazard_source_freeze/v1",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "target_year": year,
        "source_scope": "SDWIS VIOLATION rows where PWSID begins PR",
        "pages_frozen": len(pages),
        "manifestations_frozen": len(manifestations),
        "frozen_files": frozen_files,
        "new_record_revisions": len(new_records),
        "source_arithmetic": accounting,
        "classifications": dict(sorted(classifications.items())),
        "canonical_semantics": "HEALTH_BASED_VIOLATION_OBSERVATION",
        "consumer_action_semantics": "UNRESOLVED_WITHOUT_EXPLICIT_PUBLIC_NOTICE",
        "boil_water_inference_permitted": False,
        "certification_state": certification_state,
    }
    paths.ledger.parent.mkdir(parents=True, exist_ok=True)
    with paths.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    paths.receipt.parent.mkdir(parents=True, exist_ok=True)
    paths.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if require_zero_unresolved and unresolved:
        raise ValueError(f"SDWIS source denominator has {unresolved} unresolved row(s)")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--src", nargs="*", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--page-size", type=int, default=PAGE)
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--require-zero-unresolved", action="store_true")
    args = parser.parse_args()

    try:
        if args.src:
            pages = load_offline(args.src)
        else:
            with httpx.Client(
                timeout=120,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                pages = fetch_pages(
                    client,
                    page_size=args.page_size,
                    max_pages=args.max_pages,
                )
        receipt = process_pages(
            pages,
            year=args.year,
            output_root=args.output_root,
            require_zero_unresolved=args.require_zero_unresolved,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"EPA SDWIS hazard ingestion failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
