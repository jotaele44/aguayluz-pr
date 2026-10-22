#!/usr/bin/env python3
"""Freeze Salud artifacts and reconcile a complete official EPA SDWIS member.

The EPA Violations and Enforcement table is streamed so the national denominator can
be closed without loading the complete member into memory.  Source-row arithmetic and
canonical violation-snapshot arithmetic are kept separate because one violation may
have multiple enforcement association rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from aguayluz import DATA_DIR
from aguayluz.hazard_adapters.sdwa_drinking_water import (
    canonical_event_id,
    collapse_violation_rows,
    normalize,
    violation_snapshot_key,
)
from aguayluz.hazard_plane import HazardRecord, Manifestation, current_records, source_arithmetic

SALUD_ARTIFACTS = {
    "10746": {
        "role": "PUBLIC_NOTICE",
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10746",
        "default_state": "SOURCE_PRESENT_BYTES_NOT_FROZEN",
    },
    "10747": {
        "role": "ANNUAL_VIOLATIONS_REPORT_2025",
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
        "default_state": "BLOCKED_ACQUISITION",
    },
    "10748": {
        "role": "ANEJOS_APENDICES_2025",
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
        "default_state": "BLOCKED_ACQUISITION",
    },
}
EPA_SCHEMA_URL = "https://echo.epa.gov/tools/data-downloads/sdwa-download-summary"


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
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
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in sorted(by_key.values(), key=lambda item: str(item[key]))
        ),
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


def _parse_date(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _row_value(row: dict[str, Any], key: str) -> str:
    for raw_key, value in row.items():
        if str(raw_key).strip().upper() == key.upper():
            return str(value or "").strip()
    return ""


def classify_sdwis_row(row: dict[str, Any], year: int) -> tuple[str, str]:
    """Classify one source row against the declared PR/calendar-year denominator."""
    pwsid = _row_value(row, "PWSID")
    violation_id = _row_value(row, "VIOLATION_ID")
    if not pwsid or not violation_id:
        return "UNRESOLVED", "MISSING_PWSID_OR_VIOLATION_ID"
    if not pwsid.upper().startswith("PR"):
        return "EXCLUDED", "NON_PUERTO_RICO_PWSID"

    begin_raw = _row_value(row, "NON_COMPL_PER_BEGIN_DATE")
    end_raw = _row_value(row, "NON_COMPL_PER_END_DATE")
    begin = _parse_date(begin_raw)
    end = _parse_date(end_raw)
    if begin_raw and begin is None:
        return "UNRESOLVED", "INVALID_NONCOMPLIANCE_BEGIN_DATE"
    if end_raw and end is None:
        return "UNRESOLVED", "INVALID_NONCOMPLIANCE_END_DATE"
    if begin is None and end is None:
        return "UNRESOLVED", "NONCOMPLIANCE_PERIOD_MISSING"

    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    effective_begin = begin or datetime.min.replace(tzinfo=timezone.utc)
    effective_end = end or datetime.max.replace(tzinfo=timezone.utc)
    if effective_end < year_start or effective_begin > year_end:
        return "EXCLUDED", f"NO_NONCOMPLIANCE_OVERLAP_{year}"
    return "RETAINED", f"PUERTO_RICO_NONCOMPLIANCE_OVERLAPS_{year}"


def _freeze_file(
    path: Path,
    *,
    source_authority: str,
    source_system: str,
    source_record_id: str,
    source_url: str,
    retrieved_at: datetime,
    raw_root: Path,
) -> tuple[Manifestation, dict[str, Any]]:
    digest = _sha256_file(path)
    manifestation_id = (
        f"{source_system.upper().replace(' ', '_')}:{source_record_id}:"
        f"{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}:{digest[:20]}"
    )
    manifestation = Manifestation(
        manifestation_id=manifestation_id,
        source_authority=source_authority,
        source_system=source_system,
        source_record_id=source_record_id,
        source_url=source_url,
        retrieved_at_utc=retrieved_at,
        byte_sha256=digest,
    )
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / f"{source_record_id}-{digest}{path.suffix.lower()}"
    if target.exists() and _sha256_file(target) != digest:
        raise ValueError(f"raw snapshot collision at {target}")
    if not target.exists():
        shutil.copyfile(path, target)
    return manifestation, {
        "source_record_id": source_record_id,
        "source_url": source_url,
        "status": "FROZEN",
        "byte_sha256": digest,
        "byte_length": path.stat().st_size,
        "raw_file": target.name,
        "manifestation_id": manifestation_id,
    }


def _salud_artifact_receipt(
    supplied: dict[str, Path | None],
    *,
    retrieved_at: datetime,
    raw_root: Path,
) -> tuple[list[Manifestation], list[dict[str, Any]], dict[str, Any]]:
    manifestations: list[Manifestation] = []
    artifacts: list[dict[str, Any]] = []
    for source_id, spec in SALUD_ARTIFACTS.items():
        path = supplied.get(source_id)
        if path is None:
            artifacts.append(
                {
                    "source_record_id": source_id,
                    "role": spec["role"],
                    "source_url": spec["url"],
                    "status": spec["default_state"],
                    "byte_sha256": None,
                    "manifestation_id": None,
                }
            )
            continue
        manifestation, artifact = _freeze_file(
            path,
            source_authority="Puerto Rico Department of Health",
            source_system="PRDOH Drinking Water Annual Violations",
            source_record_id=source_id,
            source_url=spec["url"],
            retrieved_at=retrieved_at,
            raw_root=raw_root / "salud",
        )
        artifact["role"] = spec["role"]
        manifestations.append(manifestation)
        artifacts.append(artifact)

    frozen = sum(row["status"] == "FROZEN" for row in artifacts)
    blocked = sum(row["status"] == "BLOCKED_ACQUISITION" for row in artifacts)
    present_unfrozen = sum(
        row["status"] == "SOURCE_PRESENT_BYTES_NOT_FROZEN" for row in artifacts
    )
    arithmetic = {
        "source": len(artifacts),
        "frozen": frozen,
        "blocked": blocked,
        "present_unfrozen": present_unfrozen,
        "accounted": frozen + blocked + present_unfrozen,
    }
    arithmetic["delta"] = arithmetic["source"] - arithmetic["accounted"]
    arithmetic["state"] = "PASS" if arithmetic["delta"] == 0 else "FAIL"
    return manifestations, artifacts, arithmetic


def _sample_classification(
    samples: list[dict[str, Any]],
    *,
    ordinal: int,
    row: dict[str, Any],
    disposition: str,
    reason: str,
    limit: int = 100,
) -> None:
    if len(samples) >= limit:
        return
    if disposition == "EXCLUDED" and len(samples) >= 20:
        return
    samples.append(
        {
            "source_line": ordinal,
            "submission_year_quarter": _row_value(row, "SUBMISSIONYEARQUARTER") or None,
            "pwsid": _row_value(row, "PWSID") or None,
            "violation_id": _row_value(row, "VIOLATION_ID") or None,
            "disposition": disposition,
            "reason": reason,
        }
    )


def _process_sdwis(
    path: Path,
    *,
    source_url: str,
    year: int,
    retrieved_at: datetime,
    raw_root: Path,
    records_path: Path,
    parent_archive_sha256: str | None = None,
    archive_member: str | None = None,
) -> tuple[
    Manifestation,
    list[HazardRecord],
    dict[str, Any],
    dict[str, int],
    list[dict[str, Any]],
    dict[str, Any],
]:
    digest = _sha256_file(path)
    source_count = 0
    excluded = 0
    unresolved = 0
    retained_source_rows = 0
    stage1_reasons: Counter[str] = Counter()
    classification_samples: list[dict[str, Any]] = []
    retained_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("SDWIS CSV has no header")
        normalized_fields = {field.strip().upper() for field in reader.fieldnames if field}
        required = {
            "SUBMISSIONYEARQUARTER",
            "PWSID",
            "VIOLATION_ID",
            "NON_COMPL_PER_BEGIN_DATE",
            "NON_COMPL_PER_END_DATE",
        }
        missing = sorted(required - normalized_fields)
        if missing:
            raise ValueError(f"SDWIS CSV missing required fields: {missing}")

        schema_signature = sha256(
            _canonical_json_bytes({"fieldnames": sorted(normalized_fields)})
        ).hexdigest()

        for ordinal, row in enumerate(reader, start=2):
            source_count += 1
            disposition, reason = classify_sdwis_row(row, year)
            stage1_reasons[f"{disposition}:{reason}"] += 1
            _sample_classification(
                classification_samples,
                ordinal=ordinal,
                row=row,
                disposition=disposition,
                reason=reason,
            )
            if disposition == "EXCLUDED":
                excluded += 1
                continue
            if disposition == "UNRESOLVED":
                unresolved += 1
                continue
            retained_source_rows += 1
            retained_groups[violation_snapshot_key(row)].append(row)

    collapsed_snapshots: list[dict[str, Any]] = []
    collapse_conflicts: list[dict[str, Any]] = []
    for key in sorted(retained_groups):
        source_rows = retained_groups[key]
        try:
            collapsed_snapshots.append(collapse_violation_rows(source_rows))
        except ValueError as exc:
            retained_source_rows -= len(source_rows)
            unresolved += len(source_rows)
            collapse_conflicts.append(
                {
                    "snapshot_key": list(key),
                    "source_rows": len(source_rows),
                    "reason": str(exc),
                }
            )

    accounting = source_arithmetic(
        source_count,
        retained_source_rows,
        excluded,
        unresolved,
    )
    if accounting["state"] != "PASS":
        raise ValueError(f"SDWIS source arithmetic failed: {accounting}")

    retrieval_bits = [
        f"reconciliation_year={year}",
        "scope=complete_supplied_member",
    ]
    if archive_member:
        retrieval_bits.append(f"archive_member={archive_member}")
    manifestation_id = (
        f"EPA_SDWIS_VIOLATIONS:{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}:{digest[:20]}"
    )
    manifestation = Manifestation(
        manifestation_id=manifestation_id,
        source_authority="US EPA",
        source_system="SDWA_VIOLATIONS_ENFORCEMENT.csv",
        source_record_id=archive_member or path.name,
        source_url=source_url,
        retrieval_query=";".join(retrieval_bits),
        retrieved_at_utc=retrieved_at,
        byte_sha256=digest,
        schema_signature=schema_signature,
        record_count=source_count,
    )
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / f"SDWA_VIOLATIONS_ENFORCEMENT-{digest}.csv"
    if target.exists() and _sha256_file(target) != digest:
        raise ValueError(f"raw snapshot collision at {target}")
    if not target.exists():
        shutil.copyfile(path, target)

    existing_current = _existing_current_by_event(records_path)
    created: list[HazardRecord] = []
    material_duplicates_skipped = 0
    for snapshot in sorted(
        collapsed_snapshots,
        key=lambda row: (
            _row_value(row, "SUBMISSIONYEARQUARTER"),
            canonical_event_id(row),
        ),
    ):
        candidate = normalize(snapshot, manifestation_id)
        prior = existing_current.get(candidate.canonical_event_id)
        if prior is not None:
            if prior.record_id == candidate.record_id:
                material_duplicates_skipped += 1
                continue
            candidate = normalize(
                snapshot,
                manifestation_id,
                supersedes_record_id=prior.record_id,
            )
        created.append(candidate)
        existing_current[candidate.canonical_event_id] = candidate

    snapshot_accounting = {
        "retained_source_rows": retained_source_rows,
        "normalized_violation_snapshots": len(collapsed_snapshots),
        "source_row_to_snapshot_collapse_delta": retained_source_rows - len(collapsed_snapshots),
        "material_duplicate_snapshots_skipped": material_duplicates_skipped,
        "canonical_record_revisions_created": len(created),
        "collapse_conflict_groups": len(collapse_conflicts),
        "collapse_conflict_source_rows": sum(item["source_rows"] for item in collapse_conflicts),
        "current_event_count_after_ingest": len(existing_current),
    }
    provenance = {
        "member_sha256": digest,
        "member_byte_length": path.stat().st_size,
        "parent_archive_sha256": parent_archive_sha256,
        "archive_member": archive_member,
        "schema_signature": schema_signature,
    }
    return (
        manifestation,
        created,
        accounting,
        dict(sorted(stage1_reasons.items())),
        classification_samples,
        {
            "snapshot_accounting": snapshot_accounting,
            "collapse_conflicts": collapse_conflicts,
            "provenance": provenance,
        },
    )


def run(
    *,
    year: int,
    output_root: Path,
    salud_public_notice: Path | None = None,
    salud_report: Path | None = None,
    salud_annex: Path | None = None,
    sdwis_violations: Path | None = None,
    sdwis_source_url: str | None = None,
    sdwis_parent_archive_sha256: str | None = None,
    sdwis_archive_member: str | None = None,
    require_zero_unresolved: bool = False,
) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    raw_root = output_root / "raw"
    records_path = output_root / "hazard_records.jsonl"
    manifestations_path = output_root / "hazard_manifestations.jsonl"
    ledger_path = output_root / "hazard_source_accounting.jsonl"
    receipt_path = output_root / "salud_sdwis_water_receipt.json"

    manifestations, salud_artifacts, salud_arithmetic = _salud_artifact_receipt(
        {
            "10746": salud_public_notice,
            "10747": salud_report,
            "10748": salud_annex,
        },
        retrieved_at=retrieved_at,
        raw_root=raw_root,
    )
    new_records: list[HazardRecord] = []
    sdwis_accounting = None
    sdwis_reason_counts: dict[str, int] = {}
    sdwis_classification_samples: list[dict[str, Any]] = []
    sdwis_details: dict[str, Any] | None = None
    if sdwis_violations is not None:
        if not sdwis_source_url or not sdwis_source_url.startswith("https://"):
            raise ValueError("--sdwis-source-url with an exact HTTPS source locator is required")
        (
            sdwis_manifestation,
            records,
            sdwis_accounting,
            sdwis_reason_counts,
            sdwis_classification_samples,
            sdwis_details,
        ) = _process_sdwis(
            sdwis_violations,
            source_url=sdwis_source_url,
            year=year,
            retrieved_at=retrieved_at,
            raw_root=raw_root / "epa_sdwis",
            records_path=records_path,
            parent_archive_sha256=sdwis_parent_archive_sha256,
            archive_member=sdwis_archive_member,
        )
        manifestations.append(sdwis_manifestation)
        new_records.extend(records)

    output_root.mkdir(parents=True, exist_ok=True)
    _append_unique_jsonl(
        manifestations_path,
        [row.model_dump(mode="json") for row in manifestations],
        "manifestation_id",
    )
    _append_unique_jsonl(
        records_path,
        [row.model_dump(mode="json") for row in new_records],
        "record_id",
    )

    receipt = {
        "schema_version": "aguayluz.salud_sdwis_water/v2",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "target_calendar_year": year,
        "salud_artifacts": salud_artifacts,
        "salud_artifact_arithmetic": salud_arithmetic,
        "sdwis_schema_url": EPA_SCHEMA_URL,
        "sdwis_source_arithmetic": sdwis_accounting,
        "sdwis_classification_reason_counts": sdwis_reason_counts,
        "sdwis_classifications": sdwis_classification_samples,
        "sdwis_classification_samples_truncated": (
            sdwis_accounting is not None
            and sdwis_accounting["source"] > len(sdwis_classification_samples)
        ),
        "sdwis_details": sdwis_details,
        "new_record_revisions": len(new_records),
        "source_universe_completeness_claimed": False,
        "certification_state": (
            "OPEN"
            if any(row["status"] != "FROZEN" for row in salud_artifacts)
            or sdwis_accounting is None
            or sdwis_accounting["unresolved"] > 0
            else "BOUNDED_INPUT_PASS"
        ),
        "guardrails": [
            "A later SDWIS snapshot does not overwrite a frozen Salud annual publication.",
            "Monitoring/reporting/public-notification violations do not establish contaminant exposure.",
            "Multiple enforcement association rows are collapsed into one violation snapshot.",
            "The supplied SDWIS manifestation is a reconciliation denominator, not proof of Salud report membership.",
            "No Manifestation is created for a locator whose bytes were not frozen.",
        ],
    }
    if salud_arithmetic["state"] != "PASS":
        raise ValueError(f"Salud artifact arithmetic failed: {salud_arithmetic}")
    if require_zero_unresolved:
        if any(row["status"] != "FROZEN" for row in salud_artifacts):
            raise ValueError("Salud artifact family is not fully byte-frozen")
        if sdwis_accounting is None:
            raise ValueError("SDWIS reconciliation manifestation is missing")
        if sdwis_accounting["unresolved"]:
            raise ValueError(
                f"SDWIS denominator has {sdwis_accounting['unresolved']} unresolved row(s)"
            )
        if sdwis_details and sdwis_details["snapshot_accounting"]["collapse_conflict_source_rows"]:
            raise ValueError("SDWIS retained rows contain unresolved violation-level conflicts")

    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--output-root", type=Path, default=DATA_DIR / "salud_sdwis_water")
    parser.add_argument("--salud-public-notice", type=Path)
    parser.add_argument("--salud-report", type=Path)
    parser.add_argument("--salud-annex", type=Path)
    parser.add_argument("--sdwis-violations", type=Path)
    parser.add_argument("--sdwis-source-url")
    parser.add_argument("--sdwis-parent-archive-sha256")
    parser.add_argument("--sdwis-archive-member")
    parser.add_argument("--require-zero-unresolved", action="store_true")
    args = parser.parse_args()
    try:
        receipt = run(
            year=args.year,
            output_root=args.output_root,
            salud_public_notice=args.salud_public_notice,
            salud_report=args.salud_report,
            salud_annex=args.salud_annex,
            sdwis_violations=args.sdwis_violations,
            sdwis_source_url=args.sdwis_source_url,
            sdwis_parent_archive_sha256=args.sdwis_parent_archive_sha256,
            sdwis_archive_member=args.sdwis_archive_member,
            require_zero_unresolved=args.require_zero_unresolved,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Salud/SDWIS ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
