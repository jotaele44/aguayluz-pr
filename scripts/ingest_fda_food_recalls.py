#!/usr/bin/env python3
"""Freeze and ingest FDA food enforcement records into the hazard plane.

The source denominator is a report-date interval, not a Puerto Rico text search.
That choice is deliberate: text search is discovery and can miss Puerto Rico records
whose distribution wording uses unexpected vocabulary. Every source row in the bounded
interval is classified RETAINED, EXCLUDED, or UNRESOLVED and arithmetic must close.

Live use is keyless. API keys are intentionally deferred; openFDA permits unauthenticated
use, while a future credential can increase rate limits without changing semantics.

Examples:

    python scripts/ingest_fda_food_recalls.py --year 2026 --dry-run
    python scripts/ingest_fda_food_recalls.py --year 2026
    python scripts/ingest_fda_food_recalls.py --src frozen_openfda_page.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from aguayluz.hazard_adapters.fda_food import (
    PR_EXPLICIT,
    PR_NATIONAL_CANDIDATE,
    PR_NO_INDICATION,
    canonical_event_id,
    classify_pr_relevance,
    normalize,
)
from aguayluz.hazard_plane import HazardRecord, Manifestation, current_records, source_arithmetic

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
RAW_ROOT = DATA / "hazard_source_snapshots" / "fda_food_enforcement"
RECORDS_PATH = DATA / "hazard_records.jsonl"
MANIFESTATIONS_PATH = DATA / "hazard_manifestations.jsonl"
LEDGER_PATH = DATA / "hazard_source_accounting.jsonl"
BASE_URL = "https://api.fda.gov/food/enforcement.json"
PAGE_LIMIT = 1000
USER_AGENT = "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"


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


def _report_range(year: int) -> str:
    return f"report_date:[{year}0101+TO+{year}1231]"


def _url(search: str, skip: int) -> str:
    return f"{BASE_URL}?{urlencode({'search': search, 'limit': PAGE_LIMIT, 'skip': skip})}"


def fetch_pages(year: int) -> list[tuple[str, bytes, dict[str, str]]]:
    """Retrieve a bounded report year, retaining exact HTTP response bytes per page."""
    search = _report_range(year)
    pages: list[tuple[str, bytes, dict[str, str]]] = []
    skip = 0
    total: int | None = None
    with httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        while total is None or skip < total:
            url = _url(search, skip)
            response = client.get(url)
            response.raise_for_status()
            raw = response.content
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("openFDA response is not an object")
            meta_results = ((payload.get("meta") or {}).get("results") or {})
            page_total = meta_results.get("total")
            if not isinstance(page_total, int) or page_total < 0:
                raise ValueError("openFDA response omitted meta.results.total")
            if total is None:
                total = page_total
            elif total != page_total:
                raise ValueError(f"source total changed during pagination: {total} -> {page_total}")
            results = payload.get("results") or []
            if not isinstance(results, list):
                raise ValueError("openFDA results is not a list")
            if not results and skip < total:
                raise ValueError(f"empty page before source total exhausted at skip={skip}")
            pages.append((url, raw, dict(response.headers)))
            skip += len(results)
            if not results:
                break
    return pages


def load_offline(path: Path) -> list[tuple[str, bytes, dict[str, str]]]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("offline source must be one raw openFDA response object with results[]")
    return [(str(path), raw, {})]


def classify_row(row: dict[str, Any]) -> tuple[str, str]:
    """Return accounting disposition and PR relevance state.

    Recalling-firm state is not distribution proof. It is retained as a distinct PR
    relevance state because a Puerto Rico recalling firm is independently relevant to the
    island, while rows with no PR/nationwide indication are excluded from this PR plane.
    Missing distribution text remains unresolved rather than silently excluded.
    """
    relevance = classify_pr_relevance(row)
    if relevance in {PR_EXPLICIT, PR_NATIONAL_CANDIDATE}:
        return "RETAINED", relevance
    firm_state = str(row.get("state") or "").strip().upper()
    if firm_state == "PR":
        return "RETAINED", "CONFIRMED_PR_RECALLING_FIRM_NOT_DISTRIBUTION_PROOF"
    distribution = str(row.get("distribution_pattern") or "").strip()
    if not distribution:
        return "UNRESOLVED", "DISTRIBUTION_PATTERN_MISSING"
    if relevance == PR_NO_INDICATION:
        return "EXCLUDED", relevance
    return "UNRESOLVED", relevance


def _existing_current_by_event() -> dict[str, HazardRecord]:
    records = [HazardRecord.model_validate(row) for row in _read_jsonl(RECORDS_PATH)]
    result: dict[str, HazardRecord] = {}
    for row in current_records(records):
        prior = result.get(row.canonical_event_id)
        if prior is not None and prior.record_id != row.record_id:
            raise ValueError(f"multiple current revisions for {row.canonical_event_id}")
        result[row.canonical_event_id] = row
    return result


def process_pages(
    pages: list[tuple[str, bytes, dict[str, str]]],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    existing_current = _existing_current_by_event()
    manifestations: list[Manifestation] = []
    retained: list[HazardRecord] = []
    excluded = 0
    unresolved = 0
    source_count = 0
    seen_source_rows: set[str] = set()

    for page_number, (url, raw, headers) in enumerate(pages, start=1):
        page_sha = sha256(raw).hexdigest()
        payload = json.loads(raw)
        rows = payload.get("results") or []
        if not isinstance(rows, list):
            raise ValueError("results must be a list")
        source_count += len(rows)
        manifestation_id = f"FDA_FOOD:{stamp}:P{page_number:04d}:{page_sha[:20]}"
        manifestation = Manifestation(
            manifestation_id=manifestation_id,
            source_authority="FDA",
            source_system="openFDA food enforcement",
            source_record_id=f"page-{page_number}",
            source_url=url,
            retrieval_query=url.split("?", 1)[1] if "?" in url else None,
            retrieved_at_utc=retrieved_at,
            byte_sha256=page_sha,
            schema_signature=sha256(
                _canonical_json_bytes(sorted(payload.keys()))
            ).hexdigest(),
            record_count=len(rows),
            http_etag=headers.get("etag"),
            http_last_modified=headers.get("last-modified"),
        )
        manifestations.append(manifestation)

        if not dry_run:
            raw_path = RAW_ROOT / stamp / f"page-{page_number:04d}-{page_sha}.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            if raw_path.exists() and raw_path.read_bytes() != raw:
                raise ValueError(f"snapshot collision at {raw_path}")
            raw_path.write_bytes(raw)

        for raw_row in rows:
            if not isinstance(raw_row, dict):
                unresolved += 1
                continue
            row_sha = sha256(_canonical_json_bytes(raw_row)).hexdigest()
            if row_sha in seen_source_rows:
                raise ValueError(f"duplicate source row across pages: {row_sha}")
            seen_source_rows.add(row_sha)
            disposition, relevance = classify_row(raw_row)
            if disposition == "EXCLUDED":
                excluded += 1
                continue
            if disposition == "UNRESOLVED":
                unresolved += 1
                continue

            event_id = canonical_event_id(raw_row)
            candidate = normalize(raw_row, manifestation_id)
            previous = existing_current.get(event_id)
            if previous is not None:
                if previous.record_id == candidate.record_id:
                    # Same logical source row in a newer page manifestation: do not create
                    # a duplicate record. The new raw page manifestation is still frozen.
                    continue
                candidate = normalize(
                    raw_row,
                    manifestation_id,
                    supersedes_record_id=previous.record_id,
                )
            candidate.raw_attributes["pr_relevance"] = relevance
            retained.append(candidate)
            existing_current[event_id] = candidate

    accounting = source_arithmetic(source_count, len(retained) + excluded * 0, excluded, unresolved)
    # Repeated unchanged rows are valid retained source rows even when they do not create
    # a new logical revision. Recompute accounting on dispositions, not inserted records.
    retained_source = source_count - excluded - unresolved
    accounting = source_arithmetic(source_count, retained_source, excluded, unresolved)

    result = {
        "retrieved_at_utc": retrieved_at.isoformat(),
        "pages": len(pages),
        "source_arithmetic": accounting,
        "new_record_revisions": len(retained),
        "manifestations": len(manifestations),
        "dry_run": dry_run,
    }
    if accounting["state"] != "PASS":
        raise ValueError(f"source arithmetic failed: {accounting}")

    if dry_run:
        return result

    _append_unique_jsonl(
        MANIFESTATIONS_PATH,
        [row.model_dump(mode="json") for row in manifestations],
        "manifestation_id",
    )
    _append_unique_jsonl(
        RECORDS_PATH,
        [row.model_dump(mode="json") for row in retained],
        "record_id",
    )
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--year", type=int, help="Bounded report year to fetch live.")
    group.add_argument("--src", type=Path, help="One previously frozen openFDA response page.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        pages = fetch_pages(args.year) if args.year is not None else load_offline(args.src)
        result = process_pages(pages, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"FDA food ingestion failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
