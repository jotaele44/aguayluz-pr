#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(seed: dict[str, Any], registry: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_ids = {source["source_id"] for source in registry["sources"]}
    manifestations: list[dict[str, Any]] = []
    for group in seed["groups"]:
        if group["source_id"] not in source_ids:
            raise RuntimeError(f"manifestation source missing from registry: {group['source_id']}")
        for index, record in enumerate(group["records"], start=1):
            name, municipality = record[0], record[1]
            kind = record[2] if len(record) > 2 else group["manifestation_kind"]
            candidate_key = f"{normalize(municipality)}|{normalize(name.replace('#', ''))}"
            payload = "|".join(
                [group["source_id"], str(group.get("project_id") or ""), str(index), name, municipality]
            )
            manifestations.append(
                {
                    "manifestation_id": "EBAS_MAN_" + hashlib.sha256(payload.encode()).hexdigest()[:20],
                    "source_id": group["source_id"],
                    "project_id": group.get("project_id"),
                    "name_raw": name,
                    "municipality": municipality,
                    "manifestation_kind": kind,
                    "canonical_term_id": seed["canonical_term_id"],
                    "identity_candidate_key": candidate_key,
                    "identity_state": "CANDIDATE_NOT_IDENTITY",
                    "identity_effect": "none",
                }
            )

    key_counts = Counter(row["identity_candidate_key"] for row in manifestations)
    repeated = sorted(key for key, count in key_counts.items() if count > 1)
    expected_repeated = sorted(seed["binding_policy"]["exact_repeated_candidate_keys_expected"])
    if repeated != expected_repeated:
        raise RuntimeError(f"EBAS repeated-candidate drift: observed={repeated!r} expected={expected_repeated!r}")

    candidates = len(key_counts)
    enum = registry["enumerator_certification"]
    if enum["aaa_bounded_current_denominator"] != "OPEN" or enum["pr_wide_denominator"] != "OPEN":
        raise RuntimeError("denominator must remain OPEN until an eligible enumerator is fully retrieved")

    report = {
        "manifestation_count": len(manifestations),
        "identity_candidate_key_count": candidates,
        "repeated_candidate_keys": repeated,
        "candidate_not_identity_count": len(manifestations),
        "authoritative_project_manifestations_present": True,
        "aaa_bounded_current_denominator": enum["aaa_bounded_current_denominator"],
        "aaa_bounded_historical_denominator": enum["aaa_bounded_historical_denominator"],
        "pr_wide_denominator": enum["pr_wide_denominator"],
        "enumerator_candidates": sum(
            source["eligibility"] in {"AUTHORITATIVE_BOUNDED_ENUMERATOR_CANDIDATE", "AUTHORITATIVE_ARCHIVE_CANDIDATE"}
            for source in registry["sources"]
        ),
        "certified_enumerators": sum(source["denominator_effect"] == "CERTIFIED" for source in registry["sources"]),
        "identity_effect": "none",
        "physical_asset_count_claimed": False,
        "pr_wide_exhaustion_claimed": False,
    }
    expected = {
        "manifestation_count": 44,
        "identity_candidate_key_count": 42,
        "candidate_not_identity_count": 44,
        "enumerator_candidates": 2,
        "certified_enumerators": 0,
    }
    observed = {key: report[key] for key in expected}
    if observed != expected:
        raise RuntimeError(f"EBAS audit drift: observed={observed!r} expected={expected!r}")
    return report, manifestations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifestations", type=Path, required=True)
    args = parser.parse_args()
    report, manifestations = audit(load(args.seed), load(args.registry))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with args.manifestations.open("w", encoding="utf-8") as handle:
        for row in manifestations:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
