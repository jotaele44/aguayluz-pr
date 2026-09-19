import csv
import json
from pathlib import Path

from operators.culebrinas_kvi import calculate

COMPONENTS = [
    "vertical_depth_gap",
    "spatial_resolution_gap",
    "temporal_gap",
    "cross_domain_connectivity_gap",
    "fresh_salt_gap",
    "coastal_sgd_gap",
    "predictive_validation_gap",
]


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _complete_rows(value_a: object = 0.2, value_b: object = 0.8) -> list[dict[str, object]]:
    rows = []
    for cell, value in (("A", value_a), ("B", value_b)):
        row: dict[str, object] = {"cell_id": cell}
        for component in COMPONENTS:
            row[f"{component}_state"] = "MEASURED"
            row[f"{component}_gap_fraction"] = value
        rows.append(row)
    return rows


def _evidence(path: Path) -> None:
    path.write_text(json.dumps({
        "schema_version": "aguayluz.culebrinas-kvi-evidence/v1.0",
        "source_mode": "REAL_AUTHORIZED_OBSERVATIONS",
        "canonical_geometry_bound": True,
        "canonical_geometry_globalid": "TEST-GLOBALID",
        "field_authorization_approved": True,
        "qa_qc_closed": True,
        "all_components_measured": True,
        "withheld_validation_pass": True,
        "zero_material_residue": True,
        "experimental_observation_count": 4,
        "calibration_observation_ids": ["O1", "O2"],
        "withheld_observation_ids": ["O3", "O4"],
        "field_packet_receipt_sha256": "a" * 64,
    }), encoding="utf-8")


def test_kvi_blocks_unmeasured_component(tmp_path: Path) -> None:
    path = tmp_path / "cells.csv"
    _write(path, [{"cell_id": "A", "vertical_depth_gap_state": "UNRESOLVED"}])
    result = calculate(path, allow_test_fixture=True)
    assert result["state"] == "BLOCKED"
    assert result["kvi_measured"] is None


def test_complete_values_without_evidence_do_not_become_measured(tmp_path: Path) -> None:
    path = tmp_path / "cells.csv"
    _write(path, _complete_rows())
    result = calculate(path)
    assert result == {"state": "BLOCKED", "reason": "evidence_manifest_missing", "kvi_measured": None}


def test_explicit_test_fixture_cannot_claim_measured_kvi(tmp_path: Path) -> None:
    path = tmp_path / "cells.csv"
    _write(path, _complete_rows())
    result = calculate(path, allow_test_fixture=True)
    assert result["state"] == "MEASURED_TEST_FIXTURE"
    assert result["maximum_cell_id"] == "B"
    assert result["kvi_measured"] is False
    assert result["test_fixture"] is True


def test_kvi_measured_requires_evidence_receipt(tmp_path: Path) -> None:
    cells = tmp_path / "cells.csv"
    evidence = tmp_path / "evidence.json"
    _write(cells, _complete_rows())
    _evidence(evidence)
    result = calculate(cells, evidence)
    assert result["state"] == "MEASURED"
    assert result["maximum_cell_id"] == "B"
    assert result["maximum_kvi"] > 79.9
    assert result["winner_stability_fraction"] == 1.0
    assert result["kvi_measured"] is True
    assert result["experimental_observation_count"] == 4


def test_kvi_rejects_nonfinite_component(tmp_path: Path) -> None:
    cells = tmp_path / "cells.csv"
    evidence = tmp_path / "evidence.json"
    rows = _complete_rows()
    rows[0]["vertical_depth_gap_gap_fraction"] = "nan"
    _write(cells, rows)
    _evidence(evidence)
    result = calculate(cells, evidence)
    assert result["state"] == "BLOCKED"
    assert result["reason"] == "component_nonfinite:vertical_depth_gap"


def test_kvi_rejects_withheld_calibration_overlap(tmp_path: Path) -> None:
    cells = tmp_path / "cells.csv"
    evidence = tmp_path / "evidence.json"
    _write(cells, _complete_rows())
    _evidence(evidence)
    obj = json.loads(evidence.read_text())
    obj["withheld_observation_ids"] = ["O2", "O4"]
    evidence.write_text(json.dumps(obj), encoding="utf-8")
    result = calculate(cells, evidence)
    assert result["state"] == "BLOCKED"
    assert result["reason"] == "withheld_calibration_overlap"
