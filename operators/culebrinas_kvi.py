#!/usr/bin/env python3
"""Calculate Culebrinas KVI only from fully measured, evidenced inputs."""
from __future__ import annotations

import csv
import itertools
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
METHOD = ROOT / "config" / "culebrinas_kvi_method.v1.json"
EVIDENCE_SCHEMA = "aguayluz.culebrinas-kvi-evidence/v1.0"
REAL_SOURCE_MODE = "REAL_AUTHORIZED_OBSERVATIONS"


def _method() -> dict[str, Any]:
    return json.loads(METHOD.read_text(encoding="utf-8"))


def _read_cells(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("cells_missing_header")
        return [{str(k): str(v or "") for k, v in row.items()} for row in reader]


def _weights(cfg: dict[str, Any]) -> dict[str, float]:
    return {name: float(spec["weight"]) for name, spec in cfg["components"].items()}


def _normalized(weights: dict[str, float]) -> dict[str, float]:
    if any(not math.isfinite(v) or v < 0 for v in weights.values()):
        raise ValueError("invalid_weight")
    total = sum(weights.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("invalid_weight_total")
    return {k: v / total for k, v in weights.items()}


def _score(row: dict[str, str], weights: dict[str, float]) -> float:
    values: dict[str, float] = {}
    for component in weights:
        state = row.get(f"{component}_state", "")
        raw = row.get(f"{component}_gap_fraction", "")
        if state != "MEASURED" or raw == "":
            raise ValueError(f"component_unmeasured:{component}")
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"component_nonfinite:{component}")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"component_out_of_range:{component}")
        values[component] = value
    weights = _normalized(weights)
    score = 100.0 * sum(values[k] * weights[k] for k in weights)
    if not math.isfinite(score):
        raise ValueError("score_nonfinite")
    return score


def _ensemble(weights: dict[str, float]) -> list[dict[str, float]]:
    names = list(weights)
    return [
        _normalized({name: weights[name] * factor for name, factor in zip(names, signs)})
        for signs in itertools.product((0.8, 1.2), repeat=len(names))
    ]


def _evidence_receipt(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None or not path.is_file():
        return None, "evidence_manifest_missing"
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "evidence_manifest_invalid_json"
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        return None, "evidence_schema_mismatch"
    if evidence.get("source_mode") != REAL_SOURCE_MODE:
        return None, "source_mode_not_real_authorized_observations"
    required_true = (
        "canonical_geometry_bound",
        "field_authorization_approved",
        "qa_qc_closed",
        "all_components_measured",
        "withheld_validation_pass",
        "zero_material_residue",
    )
    missing = [key for key in required_true if evidence.get(key) is not True]
    if missing:
        return None, "evidence_gate_open:" + ",".join(missing)
    count = evidence.get("experimental_observation_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return None, "experimental_observation_count_not_positive"
    calibration_ids = evidence.get("calibration_observation_ids")
    withheld_ids = evidence.get("withheld_observation_ids")
    if not isinstance(calibration_ids, list) or not calibration_ids:
        return None, "calibration_partition_missing"
    if not isinstance(withheld_ids, list) or not withheld_ids:
        return None, "withheld_partition_missing"
    if len(calibration_ids) != len(set(calibration_ids)) or len(withheld_ids) != len(set(withheld_ids)):
        return None, "partition_duplicate_ids"
    if set(calibration_ids) & set(withheld_ids):
        return None, "withheld_calibration_overlap"
    if len(set(calibration_ids) | set(withheld_ids)) > count:
        return None, "partition_count_exceeds_observations"
    globalid = evidence.get("canonical_geometry_globalid")
    if not isinstance(globalid, str) or not globalid.strip():
        return None, "canonical_geometry_globalid_missing"
    packet_hash = evidence.get("field_packet_receipt_sha256")
    if not isinstance(packet_hash, str) or len(packet_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in packet_hash):
        return None, "field_packet_receipt_sha256_invalid"
    return evidence, None


def calculate(cells_csv: Path, evidence_manifest: Path | None = None, *, allow_test_fixture: bool = False) -> dict[str, Any]:
    cfg = _method()
    evidence, evidence_error = _evidence_receipt(evidence_manifest)
    if evidence_error and not allow_test_fixture:
        return {"state": "BLOCKED", "reason": evidence_error, "kvi_measured": None}

    rows = _read_cells(cells_csv)
    if not rows:
        return {"state": "BLOCKED", "reason": "no_cells", "kvi_measured": None}
    ids = [row.get("cell_id", "") for row in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        return {"state": "BLOCKED", "reason": "cell_id_missing_or_duplicate", "kvi_measured": None}
    base_weights = _weights(cfg)
    try:
        baseline = {row["cell_id"]: _score(row, base_weights) for row in rows}
    except (ValueError, TypeError, OverflowError) as exc:
        return {"state": "BLOCKED", "reason": str(exc), "kvi_measured": None}

    ensemble_scores: dict[str, list[float]] = {cell_id: [] for cell_id in baseline}
    winner_counts: dict[str, int] = {cell_id: 0 for cell_id in baseline}
    ensemble = _ensemble(base_weights)
    for variant in ensemble:
        scores = {row["cell_id"]: _score(row, variant) for row in rows}
        max_score = max(scores.values())
        winners = sorted(cell for cell, score in scores.items() if abs(score - max_score) < 1e-12)
        for cell, score in scores.items():
            ensemble_scores[cell].append(score)
        if len(winners) == 1:
            winner_counts[winners[0]] += 1

    maximum = max(baseline.values())
    baseline_winners = sorted(cell for cell, score in baseline.items() if abs(score - maximum) < 1e-12)
    if len(baseline_winners) != 1:
        return {
            "state": "UNRESOLVED",
            "reason": "tied_baseline_maximum",
            "candidate_cells": baseline_winners,
            "kvi_measured": None,
            "test_fixture": bool(allow_test_fixture),
        }
    winner = baseline_winners[0]
    is_test = bool(allow_test_fixture and evidence is None)
    result: dict[str, Any] = {
        "state": "MEASURED_TEST_FIXTURE" if is_test else "MEASURED",
        "method_version": cfg["schema_version"],
        "cell_count": len(rows),
        "maximum_cell_id": winner,
        "maximum_kvi": baseline[winner],
        "ensemble_min": min(ensemble_scores[winner]),
        "ensemble_max": max(ensemble_scores[winner]),
        "winner_stability_fraction": winner_counts[winner] / len(ensemble),
        "baseline_scores": baseline,
        "kvi_measured": not is_test,
        "test_fixture": is_test,
    }
    if evidence is not None:
        result.update({
            "evidence_schema_version": evidence["schema_version"],
            "experimental_observation_count": evidence["experimental_observation_count"],
            "canonical_geometry_globalid": evidence["canonical_geometry_globalid"],
            "field_packet_receipt_sha256": evidence["field_packet_receipt_sha256"].lower(),
        })
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("cells_csv", type=Path)
    parser.add_argument("--evidence-manifest", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = calculate(args.cells_csv, args.evidence_manifest)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
