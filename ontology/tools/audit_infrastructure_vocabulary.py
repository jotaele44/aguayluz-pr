#!/usr/bin/env python3
"""Audit legacy utility-asset vocabulary against the versioned infrastructure ontology.

This tool is intentionally read-only with respect to ``data/utility_assets.jsonl``.
It preserves raw strings exactly, computes a bounded denominator from the supplied
JSONL, and classifies only exact ``(asset_type, asset_subtype)`` pairs represented
in the ontology's legacy crosswalk. Unknown pairs remain unresolved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ASSETS = REPO / "data" / "utility_assets.jsonl"
DEFAULT_REGISTRY = REPO / "ontology" / "infrastructure_terms.v0.1.json"
DEFAULT_REPORT = REPO / "reports" / "infrastructure_vocabulary_audit.json"
DEFAULT_DECISIONS = REPO / "reports" / "infrastructure_classification_decisions.jsonl"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(value: Any) -> str | None:
    """Return a comparison-only normalization; never overwrite the raw value."""
    if value is None:
        return None
    raw = str(value)
    if not raw.strip():
        return None
    text = unicodedata.normalize("NFKC", raw).strip().casefold()
    return "_".join(text.replace("-", " ").split())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected object, got {type(value).__name__}")
            value["__line_number"] = line_number
            rows.append(value)
    return rows


def load_registry(path: Path) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError("ontology registry must be a JSON object")
    return registry


def validate_registry(registry: dict[str, Any]) -> dict[str, Any]:
    terms = registry.get("terms") or []
    aliases = registry.get("aliases") or []
    crosswalk = registry.get("legacy_crosswalk") or []

    term_ids = [item.get("term_id") for item in terms]
    labels = [item.get("canonical_label") for item in terms]
    duplicate_term_ids = sorted(k for k, n in Counter(term_ids).items() if n > 1)
    duplicate_labels = sorted(k for k, n in Counter(labels).items() if n > 1)
    known = set(term_ids)

    broken_alias_targets = sorted(
        {item.get("canonical_term_id") for item in aliases if item.get("canonical_term_id") not in known}
    )
    broken_crosswalk_targets = sorted(
        {
            item.get("canonical_term_id")
            for item in crosswalk
            if item.get("canonical_term_id") is not None and item.get("canonical_term_id") not in known
        }
    )

    crosswalk_keys = [
        (item.get("legacy_asset_type"), item.get("legacy_asset_subtype")) for item in crosswalk
    ]
    duplicate_crosswalk_keys = sorted(
        [list(k) for k, n in Counter(crosswalk_keys).items() if n > 1],
        key=lambda pair: (str(pair[0]), str(pair[1])),
    )

    errors = {
        "duplicate_term_ids": duplicate_term_ids,
        "duplicate_canonical_labels": duplicate_labels,
        "broken_alias_targets": broken_alias_targets,
        "broken_crosswalk_targets": broken_crosswalk_targets,
        "duplicate_crosswalk_keys": duplicate_crosswalk_keys,
    }
    errors["pass"] = not any(v for k, v in errors.items() if k != "pass")
    return errors


def crosswalk_index(registry: dict[str, Any]) -> dict[tuple[str | None, str | None], dict[str, Any]]:
    index: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for item in registry.get("legacy_crosswalk") or []:
        key = (item.get("legacy_asset_type"), item.get("legacy_asset_subtype"))
        if key in index:
            raise ValueError(f"duplicate legacy crosswalk key: {key!r}")
        index[key] = item
    return index


def decision_id(asset_id: str, asset_type: Any, asset_subtype: Any, ontology_version: str) -> str:
    payload = json.dumps(
        [asset_id, asset_type, asset_subtype, ontology_version],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "AYL_CLASS_" + hashlib.sha256(payload).hexdigest()[:20]


def classify_rows(
    rows: Iterable[dict[str, Any]], registry: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    version = str(registry.get("ontology_version") or "0.0.0")
    index = crosswalk_index(registry)
    decisions: list[dict[str, Any]] = []
    pair_counts: Counter[tuple[Any, Any]] = Counter()
    state_counts: Counter[str] = Counter()
    subtype_sources: dict[str, Counter[str]] = defaultdict(Counter)
    missing_asset_id = 0

    for row in rows:
        raw_type = row.get("asset_type")
        raw_subtype = row.get("asset_subtype")
        pair_counts[(raw_type, raw_subtype)] += 1
        subtype_sources[str(raw_subtype)][str(row.get("source_ref"))] += 1

        asset_id = row.get("asset_id")
        if not asset_id:
            missing_asset_id += 1
            asset_id = f"LINE_{row.get('__line_number')}"

        mapping = index.get((raw_type, raw_subtype))
        if mapping is None:
            state = "unresolved"
            term_id = None
            evidence = ["No exact legacy crosswalk entry for raw asset_type + asset_subtype pair."]
            notes = "Unmapped raw pair preserved without nearest-type inference."
        else:
            state = str(mapping.get("state") or "unresolved")
            term_id = mapping.get("canonical_term_id")
            evidence = ["Exact legacy asset_type + asset_subtype crosswalk match."]
            notes = mapping.get("reason")

        state_counts[state] += 1
        decisions.append(
            {
                "decision_id": decision_id(str(asset_id), raw_type, raw_subtype, version),
                "source_record_id": str(asset_id),
                "legacy_asset_type_raw": raw_type,
                "legacy_asset_subtype_raw": raw_subtype,
                "normalized_asset_type": normalize(raw_type),
                "normalized_asset_subtype": normalize(raw_subtype),
                "canonical_term_id": term_id,
                "feature_kind": None,
                "classification_state": state,
                "ontology_version": version,
                "evidence_basis": evidence,
                "source_ref": row.get("source_ref"),
                "source_hash": row.get("source_hash"),
                "notes": notes,
            }
        )

    raw_pairs = [
        {
            "asset_type_raw": pair[0],
            "asset_subtype_raw": pair[1],
            "count": count,
            "normalized_asset_type": normalize(pair[0]),
            "normalized_asset_subtype": normalize(pair[1]),
        }
        for pair, count in sorted(pair_counts.items(), key=lambda item: (str(item[0][0]), str(item[0][1])))
    ]
    source_examples = {
        subtype: [
            {"source_ref": source, "count": count}
            for source, count in counts.most_common(10)
        ]
        for subtype, counts in sorted(subtype_sources.items())
    }
    summary = {
        "row_count": len(decisions),
        "unique_raw_pairs": len(pair_counts),
        "state_counts": dict(sorted(state_counts.items())),
        "missing_asset_id": missing_asset_id,
        "raw_pairs": raw_pairs,
        "source_examples_by_raw_subtype": source_examples,
    }
    return decisions, summary


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_report(assets: Path, registry_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    registry = load_registry(registry_path)
    registry_validation = validate_registry(registry)
    if not registry_validation["pass"]:
        raise ValueError(f"ontology registry failed invariants: {registry_validation}")

    rows = load_jsonl(assets)
    decisions, summary = classify_rows(rows, registry)

    classified = sum(
        summary["state_counts"].get(state, 0)
        for state in ("pass", "provisional", "candidate_not_identity")
    )
    unresolved = summary["state_counts"].get("unresolved", 0)
    excluded = summary["state_counts"].get("excluded", 0)
    superseded = summary["state_counts"].get("superseded", 0)
    arithmetic_total = classified + unresolved + excluded + superseded

    report = {
        "audit_schema": "aguayluz.infrastructure-vocabulary-audit/v0.1",
        "scope": "Bounded to rows present in the supplied legacy utility_assets JSONL snapshot.",
        "assets_path": str(assets),
        "assets_sha256": sha256_file(assets),
        "registry_path": str(registry_path),
        "registry_sha256": sha256_file(registry_path),
        "ontology_version": registry.get("ontology_version"),
        "registry_validation": registry_validation,
        "summary": summary,
        "arithmetic": {
            "source_rows": len(rows),
            "classified": classified,
            "unresolved": unresolved,
            "excluded": excluded,
            "superseded": superseded,
            "closed_total": arithmetic_total,
            "pass": arithmetic_total == len(rows),
        },
        "certification_state": "provisional" if unresolved else "pass",
        "universal_exhaustion_claimed": False,
    }
    if not report["arithmetic"]["pass"]:
        raise AssertionError("classification arithmetic failed to close")
    return report, decisions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument(
        "--fail-on-unmapped",
        action="store_true",
        help="Return non-zero when any legacy raw pair remains unresolved.",
    )
    args = parser.parse_args()

    report, decisions = build_report(args.assets, args.registry)
    write_json(args.report, report)
    write_jsonl(args.decisions, decisions)

    unresolved = int(report["summary"]["state_counts"].get("unresolved", 0))
    print(
        f"audited {report['summary']['row_count']} rows; "
        f"{report['summary']['unique_raw_pairs']} raw type/subtype pairs; "
        f"unresolved={unresolved}; arithmetic_pass={report['arithmetic']['pass']}"
    )
    if args.fail_on_unmapped and unresolved:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
