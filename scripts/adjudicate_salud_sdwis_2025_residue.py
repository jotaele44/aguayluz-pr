#!/usr/bin/env python3
"""Adjudicate the frozen 2025 Puerto Rico SDWIS unresolved-row manifestation.

This is deliberately a downstream adjudication layer. It never rewrites the
certified predecessor JSONL or changes the source-byte receipt that produced it.

Evidence policy:
- An enforcement-only row may be terminally excluded from the violation-row
  denominator only when PWSID and ENFORCEMENT_ID are present, VIOLATION_ID is
  absent, and all violation-defining fields are empty.
- A row with an invalid end-date token can still be excluded from calendar-year
  overlap when its valid begin date is strictly after the target year.
- The literal "--->" end-date token is not interpreted as NULL/open-ended until
  an authoritative source definition binds that literal representation.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

VIOLATION_FIELDS = (
    "VIOLATION_ID",
    "VIOLATION_CODE",
    "VIOLATION_CATEGORY_CODE",
    "CONTAMINANT_CODE",
    "NON_COMPL_PER_BEGIN_DATE",
    "NON_COMPL_PER_END_DATE",
    "VIOLATION_STATUS",
    "VIOL_FIRST_REPORTED_DATE",
    "VIOL_LAST_REPORTED_DATE",
)


def sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _value(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def adjudicate(item: dict[str, Any], target_year: int) -> tuple[str, str]:
    reason = str(item.get("reason") or "")
    row = item.get("source_row")
    if not isinstance(row, dict):
        return "UNRESOLVED", "MISSING_STRUCTURED_SOURCE_ROW"

    if reason == "MISSING_PWSID_OR_VIOLATION_ID":
        pwsid = _value(row, "PWSID")
        enforcement_id = _value(row, "ENFORCEMENT_ID")
        violation_id = _value(row, "VIOLATION_ID")
        other_violation_fields = tuple(
            key for key in VIOLATION_FIELDS if key != "VIOLATION_ID" and _value(row, key)
        )
        if pwsid and enforcement_id and not violation_id and not other_violation_fields:
            return "RESOLVED_EXCLUDED", "ENFORCEMENT_ONLY_WITHOUT_VIOLATION_ID"
        return "UNRESOLVED", "MISSING_ID_PATTERN_NOT_PROVEN_ENFORCEMENT_ONLY"

    if reason == "INVALID_END_DATE":
        begin = _date(_value(row, "NON_COMPL_PER_BEGIN_DATE"))
        if begin is not None and begin.year > target_year:
            return "RESOLVED_EXCLUDED", "NONCOMPLIANCE_BEGINS_AFTER_TARGET_YEAR"
        if _value(row, "NON_COMPL_PER_END_DATE") == "--->":
            return "UNRESOLVED", "UNVERIFIED_LITERAL_END_DATE_SENTINEL"
        return "UNRESOLVED", "INVALID_END_DATE_SEMANTICS_UNBOUND"

    return "UNRESOLVED", f"UNADJUDICATED_PREDECESSOR_REASON:{reason or 'EMPTY'}"


def run(
    unresolved_path: Path,
    output_path: Path,
    *,
    target_year: int,
    expected_input_sha256: str | None = None,
    predecessor_source_rows: int | None = None,
    predecessor_retained: int | None = None,
    predecessor_excluded: int | None = None,
) -> dict[str, Any]:
    input_sha = sha256_file(unresolved_path)
    if expected_input_sha256 and input_sha != expected_input_sha256:
        raise ValueError(
            f"predecessor unresolved JSONL hash drift: {input_sha} != {expected_input_sha256}"
        )

    source = 0
    dispositions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    predecessor_reasons: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    sentinel_keys: Counter[tuple[str, str]] = Counter()

    with unresolved_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("unresolved JSONL contains non-object row")
            source += 1
            predecessor_reason = str(item.get("reason") or "")
            predecessor_reasons[predecessor_reason] += 1
            disposition, reason = adjudicate(item, target_year)
            dispositions[disposition] += 1
            reasons[reason] += 1
            row = item.get("source_row") if isinstance(item.get("source_row"), dict) else {}
            if reason == "UNVERIFIED_LITERAL_END_DATE_SENTINEL":
                sentinel_keys[(_value(row, "PWSID"), _value(row, "VIOLATION_ID"))] += 1
            rows.append(
                {
                    "source_line": item.get("source_line"),
                    "source_row_sha256": item.get("source_row_sha256"),
                    "predecessor_reason": predecessor_reason,
                    "disposition": disposition,
                    "adjudication_reason": reason,
                    "pwsid": _value(row, "PWSID") or None,
                    "violation_id": _value(row, "VIOLATION_ID") or None,
                    "enforcement_id": _value(row, "ENFORCEMENT_ID") or None,
                }
            )

    resolved_excluded = dispositions["RESOLVED_EXCLUDED"]
    unresolved = dispositions["UNRESOLVED"]
    if source != resolved_excluded + unresolved:
        raise ValueError("adjudication row conservation failed")

    revised_source_arithmetic = None
    if None not in (predecessor_source_rows, predecessor_retained, predecessor_excluded):
        revised_excluded = int(predecessor_excluded) + resolved_excluded
        revised_source_arithmetic = {
            "source": int(predecessor_source_rows),
            "retained": int(predecessor_retained),
            "excluded": revised_excluded,
            "unresolved": unresolved,
            "accounted": int(predecessor_retained) + revised_excluded + unresolved,
        }
        revised_source_arithmetic["delta"] = (
            revised_source_arithmetic["source"] - revised_source_arithmetic["accounted"]
        )
        revised_source_arithmetic["state"] = (
            "PASS" if revised_source_arithmetic["delta"] == 0 else "FAIL"
        )
        if revised_source_arithmetic["state"] != "PASS":
            raise ValueError(f"revised source arithmetic failed: {revised_source_arithmetic}")

    receipt = {
        "schema_version": "aguayluz.water_health.sdwis_unresolved_adjudication/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_year": target_year,
        "predecessor": {
            "unresolved_jsonl_sha256": input_sha,
            "row_count": source,
            "preserved_immutable": True,
        },
        "predecessor_reason_counts": dict(sorted(predecessor_reasons.items())),
        "adjudication": {
            "resolved_excluded": resolved_excluded,
            "unresolved": unresolved,
            "disposition_counts": dict(sorted(dispositions.items())),
            "reason_counts": dict(sorted(reasons.items())),
            "row_conservation_delta": source - resolved_excluded - unresolved,
            "sentinel_unique_pwsid_violation_keys": len(sentinel_keys),
            "sentinel_key_multiplicity": dict(
                sorted(Counter(sentinel_keys.values()).items())
            ),
        },
        "revised_source_arithmetic": revised_source_arithmetic,
        "certification_state": "PASS" if unresolved == 0 else "OPEN",
        "guardrails": [
            "The certified predecessor unresolved JSONL is never rewritten.",
            "ENFORCEMENT_ID does not substitute for VIOLATION_ID.",
            "Literal '--->' is not normalized to NULL without an authoritative binding.",
            "A valid begin date after the target year is sufficient to exclude target-year overlap.",
        ],
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unresolved_jsonl", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--target-year", type=int, default=2025)
    parser.add_argument("--expected-input-sha256")
    parser.add_argument("--predecessor-source-rows", type=int)
    parser.add_argument("--predecessor-retained", type=int)
    parser.add_argument("--predecessor-excluded", type=int)
    args = parser.parse_args()
    receipt = run(
        args.unresolved_jsonl,
        args.output_json,
        target_year=args.target_year,
        expected_input_sha256=args.expected_input_sha256,
        predecessor_source_rows=args.predecessor_source_rows,
        predecessor_retained=args.predecessor_retained,
        predecessor_excluded=args.predecessor_excluded,
    )
    print(json.dumps({k: receipt[k] for k in (
        "predecessor_reason_counts",
        "adjudication",
        "revised_source_arithmetic",
        "certification_state",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
