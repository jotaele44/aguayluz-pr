#!/usr/bin/env python3
"""Fail-closed Culebrinas frontier readiness/KVI/hypothesis engine.

No experimental certification may be produced from proposed, synthetic,
self-asserted, unresolved, or un-hashed evidence.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "culebrinas_field_operator_packet.v1.json"
REAL_SOURCE_MODE = "REAL_AUTHORIZED_OBSERVATIONS"


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


def _gap_receipt(cfg: dict[str, Any], reasons: list[str], observations: int = 0) -> dict[str, Any]:
    return {
        "schema_version": "aguayluz.culebrinas-frontier-receipt/v1.1",
        "outcome": "explicit_gap_receipt",
        "reasons": sorted(set(reasons)),
        "observation_count": observations,
        "kvi_measured": None,
        "hypothesis_adjudication": {h: "OPEN" for h in ("H1", "H2", "H3", "H4", "H5")},
        "certification_candidate": False,
        "production_promotion_enabled": False,
        "fail_closed": bool(cfg["preserve"]["fail_closed"]),
    }


def _hypothesis_errors(
    manifest: dict[str, Any], observation_ids: set[str]
) -> tuple[dict[str, str], list[str]]:
    states = dict(manifest.get("hypothesis_adjudication", {}))
    evidence = dict(manifest.get("hypothesis_evidence", {}))
    errors: list[str] = []
    for hid in ("H1", "H2", "H3", "H4", "H5"):
        state = states.get(hid)
        if state not in {"SUPPORTED", "FALSIFIED", "UNRESOLVED"}:
            errors.append(f"hypothesis_not_adjudicated:{hid}")
            continue
        if state == "UNRESOLVED":
            errors.append(f"hypothesis_materially_unresolved:{hid}")
            continue
        receipt = evidence.get(hid)
        if not isinstance(receipt, dict):
            errors.append(f"hypothesis_evidence_missing:{hid}")
            continue
        positive_ids = receipt.get("positive_evidence_ids", [])
        falsifier_ids = receipt.get("falsifier_test_ids", [])
        methods = receipt.get("independent_methods", [])
        if not isinstance(positive_ids, list) or not isinstance(falsifier_ids, list) or not isinstance(methods, list):
            errors.append(f"hypothesis_evidence_invalid:{hid}")
            continue
        referenced = set(positive_ids) | set(falsifier_ids)
        unknown = sorted(referenced - observation_ids)
        if unknown:
            errors.append(f"hypothesis_unknown_observation:{hid}:{','.join(unknown)}")
        if not falsifier_ids:
            errors.append(f"hypothesis_falsifier_test_missing:{hid}")
        if state == "SUPPORTED":
            if not positive_ids:
                errors.append(f"hypothesis_positive_evidence_missing:{hid}")
            if len(set(methods)) < 2:
                errors.append(f"hypothesis_method_independence_missing:{hid}")
        if state == "FALSIFIED" and not receipt.get("falsifier_triggered") is True:
            errors.append(f"hypothesis_falsifier_not_triggered:{hid}")
    return states, errors


def evaluate_packet(packet_dir: Path) -> dict[str, Any]:
    cfg = _load_json(CONFIG)
    required = list(cfg["required_packet_files"])
    missing = [name for name in required if not (packet_dir / name).is_file()]
    if missing:
        return _gap_receipt(cfg, [f"packet_file_missing:{name}" for name in missing])

    manifest = _load_json(packet_dir / "packet_manifest.json")
    if manifest.get("source_mode") != REAL_SOURCE_MODE:
        return _gap_receipt(cfg, ["source_mode_not_real_authorized_observations"])
    if manifest.get("canonical_aquifer_feature_bound") is not True:
        return _gap_receipt(cfg, ["canonical_aquifer_feature_not_bound"])
    canonical_globalid = manifest.get("canonical_aquifer_globalid")
    if not isinstance(canonical_globalid, str) or not canonical_globalid.strip():
        return _gap_receipt(cfg, ["canonical_aquifer_globalid_missing"])
    if manifest.get("field_authorization_status") != "approved":
        return _gap_receipt(cfg, ["field_authorization_not_approved"])

    file_rows = _read_csv(packet_dir / "file_manifest.csv")
    file_manifest: dict[str, str] = {}
    for row in file_rows:
        relative, digest = row.get("path", ""), row.get("sha256", "").lower()
        if relative and digest:
            if relative in file_manifest:
                return _gap_receipt(cfg, [f"file_manifest_duplicate_path:{relative}"])
            file_manifest[relative] = digest
    evidence_errors: list[str] = []
    for relative, expected in sorted(file_manifest.items()):
        path = (packet_dir / relative).resolve()
        if packet_dir.resolve() not in path.parents:
            evidence_errors.append(f"path_escape:{relative}")
            continue
        if not path.is_file():
            evidence_errors.append(f"file_missing:{relative}")
            continue
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            evidence_errors.append(f"invalid_sha256:{relative}")
            continue
        if _sha256(path) != expected:
            evidence_errors.append(f"hash_mismatch:{relative}")
    if evidence_errors:
        return _gap_receipt(cfg, evidence_errors)

    observations = _read_csv(packet_dir / "observations.csv")
    if not observations:
        return _gap_receipt(cfg, ["no_experimental_observations"])
    ids = [r.get("observation_id", "") for r in observations]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        return _gap_receipt(cfg, ["observation_id_missing_or_duplicate"])
    if any(r.get("evidence_state", "OBSERVED") != "OBSERVED" for r in observations):
        return _gap_receipt(cfg, ["nonobserved_row_in_experimental_packet"], observations=len(observations))

    station_manifest = _read_csv(packet_dir / "station_manifest.csv")
    station_ids = [r.get("station_id", "") for r in station_manifest]
    if any(not x for x in station_ids) or len(station_ids) != len(set(station_ids)):
        return _gap_receipt(cfg, ["station_id_missing_or_duplicate"], observations=len(observations))
    station_set = set(station_ids)
    unknown_stations = sorted({r.get("station_id", "") for r in observations} - station_set)
    if unknown_stations:
        return _gap_receipt(cfg, [f"observation_unknown_station:{x}" for x in unknown_stations], observations=len(observations))

    gate_state = dict(manifest.get("kvi_readiness", {}))
    configured = list(cfg["kvi_readiness_gates"])
    unresolved = [gate for gate in configured if gate_state.get(gate) is not True]
    if unresolved:
        return _gap_receipt(cfg, [f"kvi_gate_open:{gate}" for gate in unresolved], observations=len(observations))

    hypothesis_state, h_errors = _hypothesis_errors(manifest, set(ids))
    if h_errors:
        return _gap_receipt(cfg, h_errors, observations=len(observations))

    measured = manifest.get("kvi_measured")
    if not isinstance(measured, dict) or measured.get("state") != "MEASURED" or measured.get("kvi_measured") is not True:
        return _gap_receipt(cfg, ["kvi_measured_missing"], observations=len(observations))
    required_kvi = {
        "method_version",
        "maximum_cell_id",
        "maximum_kvi",
        "ensemble_min",
        "ensemble_max",
        "winner_stability_fraction",
        "evidence_schema_version",
        "experimental_observation_count",
        "canonical_geometry_globalid",
        "field_packet_receipt_sha256",
    }
    missing_kvi = sorted(required_kvi - set(measured))
    if missing_kvi:
        return _gap_receipt(cfg, ["kvi_measured_incomplete:" + ",".join(missing_kvi)], observations=len(observations))
    if measured.get("experimental_observation_count") != len(observations):
        return _gap_receipt(cfg, ["kvi_observation_count_mismatch"], observations=len(observations))
    if measured.get("canonical_geometry_globalid") != canonical_globalid:
        return _gap_receipt(cfg, ["kvi_canonical_globalid_mismatch"], observations=len(observations))
    if manifest.get("withheld_validation_pass") is not True:
        return _gap_receipt(cfg, ["withheld_validation_not_passed"], observations=len(observations))
    if manifest.get("zero_material_residue") is not True:
        return _gap_receipt(cfg, ["material_residue_open"], observations=len(observations))
    if manifest.get("green_federation_ci") is not True:
        return _gap_receipt(cfg, ["green_federation_ci_not_proven"], observations=len(observations))

    return {
        "schema_version": "aguayluz.culebrinas-frontier-receipt/v1.1",
        "outcome": "experimental_evidence_complete",
        "observation_count": len(observations),
        "canonical_aquifer_globalid": canonical_globalid,
        "kvi_measured": measured,
        "hypothesis_adjudication": hypothesis_state,
        "certification_candidate": True,
        "production_promotion_enabled": False,
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
