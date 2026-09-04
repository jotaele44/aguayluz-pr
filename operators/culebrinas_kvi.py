#!/usr/bin/env python3
"""Calculate Culebrinas KVI only from fully measured component inputs."""
from __future__ import annotations

import csv
import itertools
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
METHOD = ROOT / "config" / "culebrinas_kvi_method.v1.json"


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
    total = sum(weights.values())
    if total <= 0:
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
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"component_out_of_range:{component}")
        values[component] = value
    weights = _normalized(weights)
    return 100.0 * sum(values[k] * weights[k] for k in weights)


def _ensemble(weights: dict[str, float]) -> list[dict[str, float]]:
    names = list(weights)
    variants: list[dict[str, float]] = []
    for signs in itertools.product((0.8, 1.2), repeat=len(names)):
        variants.append(_normalized({name: weights[name] * factor for name, factor in zip(names, signs)}))
    return variants


def calculate(cells_csv: Path) -> dict[str, Any]:
    cfg = _method()
    rows = _read_cells(cells_csv)
    if not rows:
        return {"state": "BLOCKED", "reason": "no_cells", "kvi_measured": None}
    ids = [row.get("cell_id", "") for row in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        return {"state": "BLOCKED", "reason": "cell_id_missing_or_duplicate", "kvi_measured": None}
    base_weights = _weights(cfg)
    try:
        baseline = {row["cell_id"]: _score(row, base_weights) for row in rows}
    except (ValueError, TypeError) as exc:
        return {"state": "BLOCKED", "reason": str(exc), "kvi_measured": None}

    ensemble_scores: dict[str, list[float]] = {cell_id: [] for cell_id in baseline}
    winner_counts: dict[str, int] = {cell_id: 0 for cell_id in baseline}
    ensemble = _ensemble(base_weights)
    for variant in ensemble:
        scores = {row["cell_id"]: _score(row, variant) for row in rows}
        max_score = max(scores.values())
        winners = sorted([cell for cell, score in scores.items() if abs(score - max_score) < 1e-12])
        for cell, score in scores.items():
            ensemble_scores[cell].append(score)
        if len(winners) == 1:
            winner_counts[winners[0]] += 1

    maximum = max(baseline.values())
    baseline_winners = sorted([cell for cell, score in baseline.items() if abs(score - maximum) < 1e-12])
    if len(baseline_winners) != 1:
        return {
            "state": "UNRESOLVED",
            "reason": "tied_baseline_maximum",
            "candidate_cells": baseline_winners,
            "kvi_measured": baseline,
        }
    winner = baseline_winners[0]
    return {
        "state": "MEASURED",
        "method_version": cfg["schema_version"],
        "cell_count": len(rows),
        "maximum_cell_id": winner,
        "maximum_kvi": baseline[winner],
        "ensemble_min": min(ensemble_scores[winner]),
        "ensemble_max": max(ensemble_scores[winner]),
        "winner_stability_fraction": winner_counts[winner] / len(ensemble),
        "baseline_scores": baseline,
        "kvi_measured": True,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("cells_csv", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = calculate(args.cells_csv)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
