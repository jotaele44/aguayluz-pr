#!/usr/bin/env python3
"""Freeze Salud drinking-water artifacts and reconcile official EPA SDWIS violations.

This script deliberately keeps two evidence planes separate:

* Puerto Rico Department of Health annual-report artifacts are historical state
  manifestations.  They are never synthesized when bytes are unavailable.
* EPA SDWIS is a versioned federal reconciliation snapshot.  A later federal row can
  revise status or enforcement metadata without rewriting a frozen Salud publication.

The script can run before the large Salud PDFs are available.  In that case their exact
official locators remain BLOCKED_ACQUISITION in the receipt and no Manifestation object
is fabricated.  Once files are supplied, exact bytes are frozen and hashed.

SDWIS input is the official SDWA_VIOLATIONS_ENFORCEMENT CSV (or a byte-identical
extraction of that member from an official EPA archive).  The supplied file itself is
the bounded denominator: every row is RETAINED, EXCLUDED, or UNRESOLVED.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from aguayluz import DATA_DIR
from aguayluz.hazard_adapters.sdwa_drinking_water import canonical_event_id, normalize
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
        "default_state": "SOURCE_PRESENT_BYTES_NOT_FROZEN",
    },
    "10748": {
        "role": "ANEJOS_APENDICES_2025",
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
        "default_state": "SOURCE_PRESENT_BYTES_NOT_FROZEN",
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
    """Classify one supplied SDWIS row without assuming it belongs in Salud's report."""
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
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
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
    if target.exists() and target.read_bytes() != raw:
        raise ValueError(f"raw snapshot collision at {target}")
    if not target.exists():
        shutil.copyfile(path, target)
    return manifestation, {
        "source_record_id": source_record_id,
        "source_url": source_url,
        "status": "FROZEN",
        "byte_sha256": digest,
        "byte_length": len(raw),
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


def _process_sdwis(
    path: Path,
    *,
    source_url: str,
    year: int,
    retrieved_at: datetime,
    raw_root: Path,
    records_path: Path,
    scope_pws_prefix: str | None = None,
) -> tuple[Manifestation, list[HazardRecord], dict[str, Any], list[dict[str, Any]]]:
    digest = _sha256_file(path)
    manifestation_id = (
        f"EPA_SDWIS_VIOLATIONS:{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}:{digest[:20]}"
    )
    existing_current = _existing_current_by_event(records_path)
    retained: list[HazardRecord] = []
    classifications: list[dict[str, Any]] = []
    excluded = 0
    unresolved = 0
    manifestation_records = 0
    scoped_records = 0
    submission_year_quarters: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("SDWIS CSV has no header")
        normalized_fields = {field.strip().upper() for field in reader.fieldnames if field}
        required = {
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

        scope_upper = scope_pws_prefix.upper() if scope_pws_prefix else None
        for ordinal, raw_row in enumerate(reader, start=2):
            row = dict(raw_row)
            manifestation_records += 1
            quarter = _row_value(row, "SUBMISSIONYEARQUARTER")
            if quarter:
                submission_year_quarters.add(quarter)

            if scope_upper:
                pwsid = _row_value(row, "PWSID").upper()
                if not pwsid.startswith(scope_upper):
                    continue
            scoped_records += 1

            disposition, reason = classify_sdwis_row(row, year)
            classifications.append(
                {
                    "source_line": ordinal,
                    "pwsid": _row_value(row, "PWSID") or None,
                    "violation_id": _row_value(row, "VIOLATION_ID") or None,
                    "disposition": disposition,
                    "reason": reason,
                }
            )
            if disposition == "EXCLUDED":
                excluded += 1
                continue
            if disposition == "UNRESOLVED":
                unresolved += 1
                continue
            candidate = normalize(row, manifestation_id)
            prior = existing_current.get(canonical_event_id(row))
            if prior is not None:
                if prior.record_id == candidate.record_id:
                    continue
                candidate = normalize(
                    row,
                    manifestation_id,
                    supersedes_record_id=prior.record_id,
                )
            retained.append(candidate)
            existing_current[candidate.canonical_event_id] = candidate

    manifestation = Manifestation(
        manifestation_id=manifestation_id,
        source_authority="US EPA",
        source_system="SDWA_VIOLATIONS_ENFORCEMENT.csv",
        source_record_id="SDWA_VIOLATIONS_ENFORCEMENT.csv",
        source_url=source_url,
        retrieval_query=(
            f"reconciliation_year={year};scope_pws_prefix={scope_pws_prefix}"
            if scope_pws_prefix
            else f"reconciliation_year={year};scope=supplied_manifestation"
        ),
        retrieved_at_utc=retrieved_at,
        byte_sha256=digest,
        schema_signature=schema_signature,
        record_count=manifestation_records,
    )
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / f"SDWA_VIOLATIONS_ENFORCEMENT-{digest}.csv"
    if target.exists() and _sha256_file(target) != digest:
        raise ValueError(f"raw snapshot collision at {target}")
    if not target.exists():
        shutil.copyfile(path, target)

    source_denominator = scoped_records if scope_pws_prefix else manifestation_records
    retained_source = source_denominator - excluded - unresolved
    accounting = source_arithmetic(
        source_denominator,
        retained_source,
        excluded,
        unresolved,
    )
    if scope_pws_prefix:
        ordered_quarters = sorted(submission_year_quarters)
        accounting.update(
            {
                "scope_pws_prefix": scope_pws_prefix,
                "manifestation_record_count": manifestation_records,
                "scoped_record_count": scoped_records,
                "submission_year_quarters": ordered_quarters,
                "latest_submission_year_quarter": ordered_quarters[-1] if ordered_quarters else None,
            }
        )
    if accounting["state"] != "PASS":
        raise ValueError(f"SDWIS source arithmetic failed: {accounting}")
    return manifestation, retained, accounting, classifications


def run(
    *,
    year: int,
    output_root: Path,
    salud_public_notice: Path | None = None,
    salud_report: Path | None = None,
    salud_annex: Path | None = None,
    sdwis_violations: Path | None = None,
    sdwis_source_url: str | None = None,
    sdwis_scope_pws_prefix: str | None = None,
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
    sdwis_classifications: list[dict[str, Any]] = []
    if sdwis_violations is not None:
        if not sdwis_source_url or not sdwis_source_url.startswith("https://"):
            raise ValueError("--sdwis-source-url with an exact HTTPS source locator is required")
        sdwis_manifestation, records, sdwis_accounting, sdwis_classifications = _process_sdwis(
            sdwis_violations,
            source_url=sdwis_source_url,
            year=year,
            retrieved_at=retrieved_at,
            raw_root=raw_root / "epa_sdwis",
            records_path=records_path,
            scope_pws_prefix=sdwis_scope_pws_prefix,
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
        "schema_version": "aguayluz.salud_sdwis_water/v1",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "target_calendar_year": year,
        "salud_artifacts": salud_artifacts,
        "salud_artifact_arithmetic": salud_arithmetic,
        "sdwis_schema_url": EPA_SCHEMA_URL,
        "sdwis_source_arithmetic": sdwis_accounting,
        "sdwis_classifications": sdwis_classifications,
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
    parser.add_argument("--sdwis-scope-pws-prefix")
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
            sdwis_scope_pws_prefix=args.sdwis_scope_pws_prefix,
            require_zero_unresolved=args.require_zero_unresolved,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Salud/SDWIS ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
