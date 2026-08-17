#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(str(p) for p in parts if p is not None)
    return f"{prefix}_{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def water_id(n: int) -> str:
    return stable_id("LOCAL", "Waterworks_Integrated_v2.csv", n)


def canal_id(n: int) -> str:
    return stable_id("LOCAL", "Canal_de_Riego_features_summary.csv", n)


def replay(decisions: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_id = {str(d["source_record_id"]): d for d in decisions}
    if len(by_id) != len(decisions):
        raise RuntimeError("duplicate source_record_id in source-aware decisions")

    expected_water = {water_id(n) for n in range(1, 3203)}
    expected_canal = {canal_id(n) for n in range(1, 3189)}
    missing_water = sorted(expected_water - by_id.keys())
    missing_canal = sorted(expected_canal - by_id.keys())
    if missing_water or missing_canal:
        raise RuntimeError(
            f"recovered source rows do not reconcile to ledger IDs: "
            f"water_missing={len(missing_water)} canal_missing={len(missing_canal)}"
        )

    output: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for decision in decisions:
        asset_id = str(decision["source_record_id"])
        disposition = "UNRESOLVED"
        term_id = decision.get("canonical_term_id")
        evidence = list(decision.get("evidence_basis") or [])
        manifestation_relation = "NONE"

        if asset_id in {water_id(n) for n in range(1, 11)}:
            disposition = "EXCLUDED_SOURCE_FORMAT_RESIDUE"
            term_id = None
            evidence.append("Recovered Waterworks source row is fully blank across all 31 fields.")
        elif asset_id in {water_id(n) for n in range(11, 3198)}:
            disposition = "DUPLICATE_DERIVED_MANIFESTATION"
            term_id = "AYL_TERM_IRRIGATION_CANAL"
            manifestation_relation = "SAME_SOURCE_FEATURE_DERIVED_MANIFESTATION"
            evidence.append("Recovered Waterworks canal row binds 1:1 to raw canal OBJECTID manifestation.")
        elif asset_id in {water_id(n) for n in (3198, 3199, 3200, 3202)}:
            disposition = "CLASSIFIED_SOURCE_ROW"
            term_id = "AYL_TERM_SURFACE_WATER_GAGE"
            evidence.append("Recovered source Function explicitly states surface-water monitoring (discharge/gage height).")
        elif asset_id == water_id(3201):
            disposition = "UNRESOLVED"
            term_id = None
            evidence.append("Recovered source Function states water-quality sample site; no forced gage mapping.")
        elif asset_id == canal_id(1):
            disposition = "EXCLUDED_PARSER_ARTIFACT"
            term_id = None
            evidence.append("Legacy DictReader consumed blank row as header and emitted true CSV header as data.")
        elif asset_id in {canal_id(n) for n in range(2, 3189)}:
            disposition = "CLASSIFIED_SOURCE_ROW"
            term_id = "AYL_TERM_IRRIGATION_CANAL"
            evidence.append("Recovered nonblank-header canal source row is an irrigation canal feature.")
        elif decision.get("classification_state") in {"pass", "provisional", "candidate_not_identity"}:
            disposition = "CLASSIFIED_SOURCE_ROW"
        elif decision.get("classification_state") == "excluded":
            disposition = "EXCLUDED_SOURCE_FORMAT_RESIDUE"
        elif decision.get("classification_state") == "superseded":
            disposition = "DUPLICATE_DERIVED_MANIFESTATION"
        counts[disposition] += 1
        output.append(
            {
                "decision_id": "AYL_REPLAY_" + hashlib.sha256(asset_id.encode()).hexdigest()[:20],
                "legacy_asset_id": asset_id,
                "source_member": decision.get("source_ref"),
                "source_row_number": None,
                "raw_asset_type": decision.get("legacy_asset_type_raw"),
                "raw_asset_subtype": decision.get("legacy_asset_subtype_raw"),
                "canonical_term_id": term_id,
                "disposition": disposition,
                "manifestation_relation": manifestation_relation,
                "evidence": evidence,
                "identity_effect": "none",
                "certification_state": "PASS" if disposition != "UNRESOLVED" else "UNRESOLVED",
            }
        )

    primary_classified = counts["CLASSIFIED_SOURCE_ROW"]
    duplicates = counts["DUPLICATE_DERIVED_MANIFESTATION"]
    excluded = counts["EXCLUDED_SOURCE_FORMAT_RESIDUE"] + counts["EXCLUDED_PARSER_ARTIFACT"]
    unresolved = counts["UNRESOLVED"]
    report = {
        "source_rows": len(decisions),
        "primary_classified": primary_classified,
        "duplicate_derived_manifestations": duplicates,
        "class_known_source_rows": primary_classified + duplicates,
        "excluded": excluded,
        "unresolved": unresolved,
        "closed_total": primary_classified + duplicates + excluded + unresolved,
        "arithmetic_pass": primary_classified + duplicates + excluded + unresolved == len(decisions),
        "expected": {
            "source_rows": 8475,
            "primary_classified": 5058,
            "duplicate_derived_manifestations": 3187,
            "class_known_source_rows": 8245,
            "excluded": 11,
            "unresolved": 219,
        },
        "identity_effect": "none",
        "physical_asset_count_claimed": False,
        "pr_wide_exhaustion_claimed": False,
    }
    observed = {k: report[k] for k in report["expected"]}
    if not report["arithmetic_pass"] or observed != report["expected"]:
        raise RuntimeError(f"recovered replay count drift: observed={observed!r} expected={report['expected']!r}")
    return report, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-aware-decisions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args()
    report, decisions = replay(load_jsonl(args.source_aware_decisions))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with args.decisions.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            handle.write(json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
