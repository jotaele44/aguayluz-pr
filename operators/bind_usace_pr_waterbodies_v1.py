#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from aguayluz.usace_waterbody_binding import (
    WaterbodyRecord,
    adjudicate,
    bind_with_evidence,
    discover_name_candidates,
)
from aguayluz.usace_corpus import utc_now


def load_waterbodies(path: Path) -> list[WaterbodyRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("waterbody features must be a list")
    out: list[WaterbodyRecord] = []
    ids: set[str] = set()
    for row in features:
        if not isinstance(row, dict) or row.get("group") != "hydro":
            continue
        canonical_id = str(row.get("canonical_id") or "").strip()
        name = str(row.get("canonical_name") or "").strip()
        if not canonical_id or not name:
            continue
        if canonical_id in ids:
            raise ValueError(f"duplicate waterbody canonical_id {canonical_id}")
        ids.add(canonical_id)
        stable_ids = []
        if row.get("gnis_id"):
            stable_ids.append(f"GNIS:{row['gnis_id']}")
        aliases = tuple(str(v) for v in row.get("aliases", []) if str(v).strip())
        out.append(
            WaterbodyRecord(
                canonical_id=canonical_id,
                canonical_name=name,
                stable_ids=tuple(stable_ids),
                aliases=aliases,
                municipality=str(row.get("municipality")) if row.get("municipality") else None,
            )
        )
    return out


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind USACE project candidates to PR waterbodies fail-closed")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--waterbodies", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidates = read_csv(args.candidates)
    waterbodies = load_waterbodies(args.waterbodies)
    by_id = {row.canonical_id: row for row in waterbodies}
    evidence_rows = read_csv(args.evidence) if args.evidence else []
    evidence_by_project: dict[str, list[dict[str, str]]] = {}
    for row in evidence_rows:
        evidence_by_project.setdefault(row.get("project_raw", ""), []).append(row)

    projects = sorted({row.get("project_raw", "") for row in candidates if row.get("project_raw")})
    candidate_out: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    for project in projects:
        discovered = discover_name_candidates(project, waterbodies)
        hard = []
        for evidence in evidence_by_project.get(project, []):
            waterbody_id = evidence.get("waterbody_id", "")
            waterbody = by_id.get(waterbody_id)
            if waterbody is None:
                hard.append(None)
                candidate_out.append(
                    {
                        "project_raw": project,
                        "waterbody_id": waterbody_id,
                        "evidence_type": evidence.get("evidence_type"),
                        "evidence_value": evidence.get("evidence_value"),
                        "state": "UNRESOLVED_UNKNOWN_WATERBODY_ID",
                    }
                )
                continue
            binding = bind_with_evidence(
                project,
                waterbody,
                evidence.get("evidence_type", ""),
                evidence.get("evidence_value", ""),
            )
            hard.append(binding)
        rows = discovered + [row for row in hard if row is not None]
        candidate_out.extend(asdict(row) for row in discovered)
        candidate_out.extend(asdict(row) for row in hard if row is not None)
        result = adjudicate(rows)
        decisions.append(
            {
                "project_raw": project,
                "cardinality": result["cardinality"],
                "state": result["state"],
                "winner_waterbody_id": (result.get("winner") or {}).get("waterbody_id"),
                "candidate_count": len(result.get("candidates", [])),
            }
        )

    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "waterbody_binding_candidates.csv", candidate_out)
    write_csv(args.output / "waterbody_binding_decisions.csv", decisions)
    counts: dict[str, int] = {}
    for row in decisions:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    unresolved = sum(count for state, count in counts.items() if state != "PASS")
    snapshot = {
        "snapshot_version": "1.0.0",
        "created_utc": utc_now(),
        "waterbody_source": str(args.waterbodies),
        "waterbody_count": len(waterbodies),
        "project_count": len(projects),
        "decision_state_counts": counts,
        "unresolved_project_count": unresolved,
        "certification_state": "PASS_IDENTITY_ZERO_RESIDUE" if unresolved == 0 else "OPEN_IDENTITY_RESIDUE",
        "identity_rule": "NAME_ONLY/NORMALIZED_NAME_ONLY never proves identity; tied hard evidence remains unresolved.",
    }
    (args.output / "waterbody_binding_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
