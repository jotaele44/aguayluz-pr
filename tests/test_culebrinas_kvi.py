import csv
from pathlib import Path

from operators.culebrinas_kvi import calculate


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_kvi_blocks_unmeasured_component(tmp_path: Path) -> None:
    path = tmp_path / "cells.csv"
    _write(path, [{"cell_id": "A", "vertical_depth_gap_state": "UNRESOLVED"}])
    result = calculate(path)
    assert result["state"] == "BLOCKED"
    assert result["kvi_measured"] is None


def test_kvi_measured_unique_winner(tmp_path: Path) -> None:
    components = [
        "vertical_depth_gap",
        "spatial_resolution_gap",
        "temporal_gap",
        "cross_domain_connectivity_gap",
        "fresh_salt_gap",
        "coastal_sgd_gap",
        "predictive_validation_gap",
    ]
    rows = []
    for cell, value in (("A", 0.2), ("B", 0.8)):
        row: dict[str, object] = {"cell_id": cell}
        for component in components:
            row[f"{component}_state"] = "MEASURED"
            row[f"{component}_gap_fraction"] = value
        rows.append(row)
    path = tmp_path / "cells.csv"
    _write(path, rows)
    result = calculate(path)
    assert result["state"] == "MEASURED"
    assert result["maximum_cell_id"] == "B"
    assert result["maximum_kvi"] > 79.9
    assert result["winner_stability_fraction"] == 1.0
