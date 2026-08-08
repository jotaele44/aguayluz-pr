"""Design-only Patillas stage-area and hourly QPE transform v0.5.1.

No complete water balance, provider polling, persistence, alerting, or control action occurs here.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

INCH_TO_M = 0.0254


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_frozen_bytes(encoded_path: Path, receipt: dict[str, Any]) -> bytes:
    raw = base64.b64decode(encoded_path.read_text(encoding="ascii"))
    if len(raw) != receipt["bytes"]["size"]:
        raise ValueError("source_size_mismatch")
    if hashlib.sha256(raw).hexdigest() != receipt["bytes"]["sha256"]:
        raise ValueError("source_sha256_mismatch")
    return raw


def stage_area_m2(stage_m: float, model: dict[str, Any]) -> float:
    plateau = model["published_plateau"]
    if plateau["lower_stage_m"] <= stage_m <= plateau["upper_stage_m"]:
        raise ValueError("stage_area_undefined_on_published_zero_storage_plateau")
    domain = model["valid_stage_domain_m_prvd02"]
    if not (domain["min"] <= stage_m <= domain["max"]):
        raise ValueError("stage_area_out_of_range")
    points = [p for p in model["points"] if p["area_m2"] is not None]
    for point in points:
        if abs(point["stage_m_prvd02"] - stage_m) < 1e-9:
            return float(point["area_m2"])
    for left, right in zip(points, points[1:], strict=False):
        if left["stage_m_prvd02"] < stage_m < right["stage_m_prvd02"]:
            fraction = (stage_m - left["stage_m_prvd02"]) / (right["stage_m_prvd02"] - left["stage_m_prvd02"])
            return float(left["area_m2"] + fraction * (right["area_m2"] - left["area_m2"]))
    raise ValueError("stage_area_not_resolved")


def qpe_volume_from_fragments(
    fragments: list[dict[str, float]],
    geometry_area_m2: float,
    *,
    qpe_uncertainty_fraction: float | None,
    area_tolerance_m2: float = 0.05,
) -> dict[str, Any]:
    if not fragments:
        raise ValueError("missing_qpe_fragments")
    area_sum = 0.0
    volume_m3 = 0.0
    for fragment in fragments:
        depth_in = fragment.get("depth_in")
        area_m2 = fragment.get("intersection_area_m2")
        if not isinstance(depth_in, (int, float)) or not isinstance(area_m2, (int, float)):
            raise ValueError("invalid_qpe_fragment")
        if depth_in <= -1e30:
            raise ValueError("qpe_nodata")
        if area_m2 < 0:
            raise ValueError("negative_intersection_area")
        area_sum += area_m2
        volume_m3 += depth_in * INCH_TO_M * area_m2
    if abs(area_sum - geometry_area_m2) > area_tolerance_m2:
        raise ValueError("geometry_area_mismatch")
    weighted_depth_m = volume_m3 / geometry_area_m2
    if qpe_uncertainty_fraction is None:
        status = "computed_not_admitted"
        uncertainty_m3 = None
    elif qpe_uncertainty_fraction < 0:
        raise ValueError("invalid_qpe_uncertainty")
    else:
        status = "transform_only_not_balance"
        uncertainty_m3 = abs(volume_m3) * qpe_uncertainty_fraction
    return {
        "status": status,
        "precipitation_volume_m3": volume_m3,
        "area_weighted_depth_m": weighted_depth_m,
        "qpe_uncertainty_m3": uncertainty_m3,
        "real_balance_executed": False,
        "root_cause_claim": None,
    }


def replay_public_sample(root: Path) -> dict[str, Any]:
    receipt = load_json(root / "noaa_stageiv_pr_20260808T000000Z.receipt.json")
    fixture = load_json(root / "qpe_replay_fixture.json")["public_byte_replay"]
    verify_frozen_bytes(root / "noaa_stageiv_pr_20260808T000000Z.tif.b64", receipt)
    if fixture["stage_m_prvd02"] != 67.55:
        raise ValueError("stage_specific_geometry_required")
    result = qpe_volume_from_fragments(fixture["cells"], fixture["geometry_area_m2"], qpe_uncertainty_fraction=None)
    result["source_sha256"] = receipt["bytes"]["sha256"]
    result["geometry_binding"] = fixture["geometry_binding"]
    result["admission_status"] = fixture["admission_status"]
    return result


def require_stage_geometry(stage_m: float, geometry_binding: str | None) -> None:
    if stage_m != 67.55 and not geometry_binding:
        raise ValueError("stage_specific_geometry_required")
