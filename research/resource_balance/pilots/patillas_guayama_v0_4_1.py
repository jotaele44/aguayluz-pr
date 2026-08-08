"""Design-only verifier for the permanent Lago Patillas stage-volume package."""
from __future__ import annotations

import csv
import hashlib
import json
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DATUM = "PRVD02"
ROWS = 24
ANCHOR = (67.55, 12_960_000)
PLATEAU = (44.55, 45.55, 0)


def canonical_json(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_receipt_payload(receipt: Mapping[str, Any]) -> bool:
    expected = str(receipt.get("receipt_payload_sha256", ""))
    payload = {k: v for k, v in receipt.items() if k != "receipt_payload_sha256"}
    return len(expected) == 64 and sha256_bytes(canonical_json(payload)) == expected


def validate_stage_storage_model(model: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "status": "materialized_authoritative_with_declared_precision_plateau",
        "datum": DATUM,
        "stage_unit": "m",
        "storage_unit": "m3",
        "extrapolation_policy": "prohibited",
        "interpolation_policy": "piecewise_linear_except_declared_prohibited_segments",
    }
    errors += [f"invalid_{k}" for k, v in required.items() if model.get(k) != v]
    points = model.get("points")
    if not isinstance(points, list) or len(points) != ROWS:
        return sorted(set(errors + ["truncated_or_extended_table"]))

    prior: tuple[float, int] | None = None
    plateaus: list[tuple[float, float, int]] = []
    for index, point in enumerate(points):
        try:
            current = (float(point["stage_m_prvd02"]), int(point["storage_m3"]))
        except (KeyError, TypeError, ValueError):
            errors.append(f"invalid_point:{index}")
            continue
        if prior:
            if current[0] <= prior[0]:
                errors.append("duplicate_or_decreasing_stage")
            if current[1] < prior[1]:
                errors.append("decreasing_storage")
            elif current[1] == prior[1]:
                plateaus.append((prior[0], current[0], current[1]))
        prior = current

    declared = {
        (float(x["lower_stage_m_prvd02"]), float(x["upper_stage_m_prvd02"]), 0)
        for x in model.get("prohibited_interpolation_segments", [])
    }
    if plateaus != [PLATEAU]:
        errors.append("unexpected_published_precision_plateau")
    if PLATEAU not in declared:
        errors.append("plateau_not_declared")
    anchor = model.get("anchor", {})
    actual = (float(anchor.get("stage_m_prvd02", -1)), int(anchor.get("storage_m3", -1)))
    if actual != ANCHOR:
        errors.append("anchor_mismatch")
    last = points[-1]
    terminal = (float(last.get("stage_m_prvd02", -1)), int(last.get("storage_m3", -1)))
    if terminal != ANCHOR:
        errors.append("terminal_anchor_mismatch")
    return sorted(set(errors))


def stage_to_storage(
    stage_m_prvd02: float,
    model: Mapping[str, Any],
    *,
    observed_datum: str,
    observation_source_sha256: str,
) -> dict[str, Any]:
    errors = validate_stage_storage_model(model)
    if errors:
        raise ValueError(";".join(errors))
    if observed_datum != DATUM:
        raise ValueError("stage_datum_mismatch")
    if len(observation_source_sha256) != 64:
        raise ValueError("observation_source_sha256_required")
    points = model["points"]
    stage = float(stage_m_prvd02)
    minimum = float(points[0]["stage_m_prvd02"])
    maximum = float(points[-1]["stage_m_prvd02"])
    if not minimum <= stage <= maximum:
        raise ValueError("stage_out_of_model_range")

    lower = upper = None
    for point in points:
        if float(point["stage_m_prvd02"]) == stage:
            lower = upper = point
            break
    if lower is None:
        for left, right in zip(points, points[1:], strict=True):
            if float(left["stage_m_prvd02"]) < stage < float(right["stage_m_prvd02"]):
                lower, upper = left, right
                break
    if lower is None or upper is None:
        raise ValueError("stage_bracket_not_found")

    ls, us = float(lower["stage_m_prvd02"]), float(upper["stage_m_prvd02"])
    lv, uv = int(lower["storage_m3"]), int(upper["storage_m3"])
    interpolated = ls != us
    prohibited = any(
        float(x["lower_stage_m_prvd02"]) == ls and float(x["upper_stage_m_prvd02"]) == us
        for x in model["prohibited_interpolation_segments"]
    )
    if interpolated and prohibited:
        raise ValueError("published_precision_plateau_interpolation_prohibited")
    fraction = (stage - ls) / (us - ls) if interpolated else 0.0
    storage = round(lv + fraction * (uv - lv), 6)
    payload = {
        "schema_version": "aguayluz.stage-storage-transform-receipt/v0.4.1",
        "model_id": model["model_id"],
        "model_hash": sha256_bytes(canonical_json(model)),
        "input": {"stage": stage, "unit": "m", "datum": observed_datum},
        "observation_source_sha256": observation_source_sha256,
        "bracket": {
            "lower_stage_m_prvd02": ls,
            "lower_storage_m3": lv,
            "upper_stage_m_prvd02": us,
            "upper_storage_m3": uv,
            "fraction": fraction,
        },
        "output": {"storage": storage, "unit": "m3"},
        "interpolated": interpolated,
        "extrapolated": False,
        "claim_status": "derived",
    }
    receipt_id = f"AYL_STG_{sha256_bytes(canonical_json(payload))[:20]}"
    return {"storage_m3": storage, "receipt": {**payload, "receipt_id": receipt_id}}


def _source_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_evidence_package(root: Path) -> list[str]:
    errors: list[str] = []
    manifest = load_json(root / "evidence_manifest.json")
    for entry in manifest["entries"]:
        path = root / entry["path"]
        if not path.is_file():
            errors.append(f"missing:{entry['path']}")
            continue
        raw = path.read_bytes()
        if len(raw) != entry["size_bytes"]:
            errors.append(f"size:{entry['path']}")
        if sha256_bytes(raw) != entry["sha256"]:
            errors.append(f"sha256:{entry['path']}")

    receipt = load_json(root / "source_receipt.json")
    if not verify_receipt_payload(receipt):
        errors.append("receipt_payload_sha256")
    archive = receipt["archive"]
    if archive["observed_md5"] != archive["published_md5"]:
        errors.append("archive_md5")
    if archive["size_bytes"] != 27_171_688:
        errors.append("archive_size")
    if archive["sha256"] != manifest["source_archive_sha256"]:
        errors.append("archive_sha256_cross_bind")

    rows = _source_rows(root / "source/Patillas2019_volume.source_order.csv")
    if len(rows) != ROWS or [int(x["source_fid"]) for x in rows] != list(range(1, 25)):
        errors.append("source_csv_rows_or_order")
    expected_ends = (("67.55", "12.96"), ("44.55", "0.00"))
    observed_ends = tuple(
        (x["Pool_Elevation_m"], x["Storage_capacity_mcm"]) for x in (rows[0], rows[-1])
    )
    if observed_ends != expected_ends:
        errors.append("source_csv_endpoint_rows")

    component = (root / "source/Patillas_Terrain_2019.gdb/a00000064.gdbtable").read_bytes()
    anchors = ((196, 67.55), (204, 12.96), (679, 44.55))
    if not all(component[o : o + 8] == struct.pack("<d", v) for o, v in anchors):
        errors.append("binary_component_anchor")
    model = load_json(root / "lago_patillas_stage_storage_model.json")
    errors += validate_stage_storage_model(model)
    for key, name in (
        ("parsed_table_sha256", "patillas_stage_volume_table.json"),
        ("model_sha256", "lago_patillas_stage_storage_model.json"),
    ):
        if receipt[key] != sha256_bytes((root / name).read_bytes()):
            errors.append(f"{key}_cross_bind")
    return sorted(set(errors))


def real_window_readiness(root: Path) -> dict[str, Any]:
    readiness = load_json(root / "source_receipt.json")["real_window_readiness"]
    return {**readiness, "stage_storage_verification_errors": verify_evidence_package(root)}
