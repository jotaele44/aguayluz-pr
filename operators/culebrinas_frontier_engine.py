#!/usr/bin/env python3
"""Fail-closed Culebrinas frontier readiness/KVI/hypothesis engine.

This module never fabricates KVI_MEASURED. It produces an explicit gap receipt
until every configured readiness gate is independently evidenced.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "culebrinas_field_operator_packet.v1.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"csv_missing_header:{path.name}")
        return [{str(k): str(v or "") for k, v in row.items()} for row in reader]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_packet(packet_dir: Path) -> dict[str, Any]:
    cfg = _load_json(CONFIG)
    required = list(cfg["required_packet_files"])
    missing = [name for name in required if not (packet_dir / name).is_file()]
    if missing:
        return _gap_receipt(cfg, [f"packet_file_missing:{name}" for name in missing])

    manifest = _load_json(packet_dir / "packet_manifest.json")
    if manifest.get("canonical_aquifer_feature_bound") is not True:
        return _gap_receipt(cfg, ["canonical_aquifer_feature_not_bound"])
    if manifest.get("field_authorization_status") != "approved":
        return _gap_receipt(cfg, ["field_authorization_not_approved"])

    file_manifest = {r["path"]: r["sha256"].lower() for r in _read_csv(packet_dir / "file_manifest.csv") if r.get("path") and r.get("sha256")}
    evidence_errors: list[str] = []
    for relative, expected in sorted(file_manifest.items()):
        path = (packet_dir / relative).resolve()
        if packet_dir.resolve() not in path.parents:
            evidence_errors.append(f"path_escape:{relative}")
            continue
        if not path.is_file():
            evidence_errors.append(f"file_missing:{relative}")
            continue
        if _sha256(path) != expected:
            evidence_errors.append(f"hash_mismatch:{relative}")
    if evidence_errors:
        return _gap_receipt(cfg, evidence_errors)

    observations = _read_csv(packet_dir / "observations.csv")
    station_manifest = _read_csv(packet_dir / "station_manifest.csv")
    ids = [r.get("observation_id", "") for r in observations]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        return _gap_receipt(cfg, ["observation_id_missing_or_duplicate"])
    station_ids = [r.get("station_id", "") for r in station_manifest]
    if any(not x for x in station_ids) or len(station_ids) != len(set(station_ids)):
        return _gap_receipt(cfg, ["station_id_missing_or_duplicate"])

    gate_state = dict(manifest.get("kvi_readiness", {}))
    configured = list(cfg["kvi_readiness_gates"])
    unresolved = [gate for gate in configured if gate_state.get(gate) is not True]
    if unresolved:
        return _gap_receipt(cfg, [f"kvi_gate_open:{gate}" for gate in unresolved], observations=len(observations))

    hypothesis_state = dict(manifest.get("hypothesis_adjudication", {}))
    h_errors: list[str] = []
    for hid in ("H1", "H2", "H3", "H4", "H5"):
        state = hypothesis_state.get(hid)
        if state not in {"SUPPORTED", "FALSIFIED", "UNRESOLVED"}:
            h_errors.append(f"hypothesis_not_adjudicated:{hid}")
    if h_errors:
        return _gap_receipt(cfg, h_errors, observations=len(observations))

    measured = manifest.get("kvi_measured")
    if not isinstance(measured, dict) or measured.get("state") != "MEASURED":
        return _gap_receipt(cfg, ["kvi_measured_missing"], observations=len(observations))
    if "value" not in measured or "method_version" not in measured or "withheld_validation" not in measured:
        return _gap_receipt(cfg, ["kvi_measured_incomplete"], observations=len(observations))
    if measured.get("withheld_validation") != "PASS":
        return _gap_receipt(cfg, ["withheld_validation_not_passed"], observations=len(observations))

    return {
        "schema_version": "aguayluz.culebrinas-frontier-receipt/v1.0",
        "outcome": "experimental_evidence_complete",
        "observation_count": len(observations),
        "kvi_measured": measured,
        "hypothesis_adjudication": hypothesis_state,
        "certification_candidate": True,
        "production_promotion_enabled": False,
    }


def _gap_receipt(cfg: dict[str, Any], reasons: list[str], observations: int = 0) -> dict[str, Any]:
    return {
        "schema_version": "aguayluz.culebrinas-frontier-receipt/v1.0",
        "outcome": "explicit_gap_receipt",
        "reasons": sorted(set(reasons)),
        "observation_count": observations,
        "kvi_measured": None,
        "hypothesis_adjudication": {h: "OPEN" for h in ("H1", "H2", "H3", "H4", "H5")},
        "certification_candidate": False,
        "production_promotion_enabled": False,
        "fail_closed": bool(cfg["preserve"]["fail_closed"]),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("packet_dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    receipt = evaluate_packet(args.packet_dir)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
