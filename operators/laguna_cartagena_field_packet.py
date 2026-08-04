#!/usr/bin/env python3
"""Validate and ingest one Laguna Cartagena field/operator packet in shadow mode."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.backend.water_disruption import WaterIncidentService  # noqa: E402

from operators.laguna_cartagena_probe.model import build_observation  # noqa: E402

CONFIG_PATH = REPO_ROOT / "config" / "laguna_cartagena_field_operator_packet.v0.4.json"
LAB_METRICS = {"nitrate", "ammonia", "phosphorus", "fecal_indicator"}
IN_SITU_METRICS = {
    "lagoon_stage",
    "outflow_discharge",
    "groundwater_level",
    "specific_conductance",
    "water_temperature",
    "dissolved_oxygen",
    "ph",
    "turbidity",
}
FIELD_METRICS = IN_SITU_METRICS | LAB_METRICS
OBSERVATION_COLUMNS = {
    "record_id",
    "metric",
    "location_id",
    "observed_at",
    "value",
    "unit",
    "provider",
    "source_record_id",
    "instrument_id",
    "calibration_record_id",
    "sample_id",
    "raw_file",
    "photo_file",
    "field_note_file",
    "qa_status",
    "latitude",
    "longitude",
    "notes",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"csv_missing_header:{path.name}")
        return [{str(key): str(value or "").strip() for key, value in row.items()} for row in reader]


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def _file_manifest(packet_dir: Path) -> dict[str, str]:
    rows = _read_csv(packet_dir / "file_manifest.csv")
    output: dict[str, str] = {}
    for row in rows:
        relative = row.get("path", "")
        digest = row.get("sha256", "").lower()
        if not relative or len(digest) != 64:
            continue
        output[relative] = digest
    return output


def _verify_file(packet_dir: Path, relative: str, manifest: dict[str, str]) -> str:
    if not relative:
        raise ValueError("evidence_file_required")
    path = (packet_dir / relative).resolve()
    if packet_dir.resolve() not in path.parents:
        raise ValueError("evidence_path_escape")
    if not path.is_file():
        raise ValueError(f"evidence_file_missing:{relative}")
    actual = _sha256(path)
    expected = manifest.get(relative)
    if expected != actual:
        raise ValueError(f"evidence_hash_mismatch:{relative}")
    return actual


def _calibrations(packet_dir: Path, file_manifest: dict[str, str]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in _read_csv(packet_dir / "instrument_calibrations.csv"):
        calibration_id = row.get("calibration_record_id", "")
        instrument_id = row.get("instrument_id", "")
        if not calibration_id or not instrument_id:
            continue
        calibrated = _parse_utc(row["calibrated_at"])
        expires = _parse_utc(row["expires_at"])
        if expires <= calibrated:
            raise ValueError(f"invalid_calibration_window:{calibration_id}")
        certificate = row.get("certificate_file", "")
        certificate_hash = _verify_file(packet_dir, certificate, file_manifest)
        if row.get("certificate_sha256", "").lower() != certificate_hash:
            raise ValueError(f"calibration_certificate_hash_mismatch:{calibration_id}")
        output[calibration_id] = row
    return output


def _custody(packet_dir: Path, file_manifest: dict[str, str]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in _read_csv(packet_dir / "chain_of_custody.csv"):
        sample_id = row.get("sample_id", "")
        if not sample_id:
            continue
        required = [
            "collection_utc",
            "collector",
            "seal_id",
            "lab_receipt_utc",
            "lab_report_file",
            "lab_report_sha256",
            "signature",
        ]
        missing = [name for name in required if not row.get(name)]
        if missing:
            raise ValueError(f"custody_missing:{sample_id}:{','.join(missing)}")
        _parse_utc(row["collection_utc"])
        _parse_utc(row["lab_receipt_utc"])
        report_hash = _verify_file(packet_dir, row["lab_report_file"], file_manifest)
        if row["lab_report_sha256"].lower() != report_hash:
            raise ValueError(f"lab_report_hash_mismatch:{sample_id}")
        output[sample_id] = row
    return output


def _gap_receipt(
    *,
    packet_id: str,
    reasons: list[str],
    missing_direct: list[str],
    missing_operational: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "aguayluz.laguna-cartagena-field-packet-receipt/v0.4",
        "packet_id": packet_id,
        "outcome": "explicit_gap_receipt",
        "ingested_observation_count": 0,
        "missing_direct_metrics": missing_direct,
        "missing_operational_metrics": missing_operational,
        "reasons": sorted(set(reasons)),
        "current_condition_status": "unknown",
        "shadow_mode": True,
        "notifications_enabled": False,
        "automatic_control_actions_enabled": False,
        "production_promotion_enabled": False,
        "automatic_leakage_claim": None,
    }


def validate_and_ingest(packet_dir: Path, output_dir: Path) -> dict[str, Any]:
    config = _load_json(CONFIG_PATH)
    required_files = config["required_packet_files"]
    missing_files = [name for name in required_files if not (packet_dir / name).is_file()]
    if missing_files:
        receipt = _gap_receipt(
            packet_id=packet_dir.name,
            reasons=[f"packet_file_missing:{name}" for name in missing_files],
            missing_direct=config["required_direct_metrics"],
            missing_operational=config["required_operational_metrics"],
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "final_receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return receipt

    manifest = _load_json(packet_dir / "packet_manifest.json")
    packet_id = str(manifest.get("packet_id") or packet_dir.name)
    preserve = config["preserve"]
    invariant_pairs = {
        "shadow_mode": preserve["shadow_mode"],
        "notifications_enabled": preserve["notifications_enabled"],
        "automatic_control_actions_enabled": preserve[
            "automatic_control_actions_enabled"
        ],
        "production_promotion_enabled": preserve["production_promotion_enabled"],
    }
    invariant_failures = [
        f"packet_invariant_violation:{key}"
        for key, expected in invariant_pairs.items()
        if manifest.get(key) is not expected
    ]
    if manifest.get("field_authorization_status") != "approved":
        invariant_failures.append("field_authorization_not_approved")
    if manifest.get("qualified_adult_crew_attestation") is not True:
        invariant_failures.append("qualified_adult_crew_attestation_missing")

    try:
        window_start = _parse_utc(str(manifest["window_start_utc"]))
        window_end = _parse_utc(str(manifest["window_end_utc"]))
    except (KeyError, TypeError, ValueError):
        invariant_failures.append("invalid_packet_window")
        window_start = window_end = datetime.now(timezone.utc)
    if window_end <= window_start:
        invariant_failures.append("invalid_packet_window_order")
    if (window_end - window_start).total_seconds() > 24 * 3600:
        invariant_failures.append("packet_window_exceeds_24_hours")

    file_manifest = _file_manifest(packet_dir)
    try:
        authorization_file = str(manifest.get("field_authorization_file", ""))
        authorization_hash = _verify_file(packet_dir, authorization_file, file_manifest)
        if str(manifest.get("field_authorization_sha256", "")).lower() != authorization_hash:
            invariant_failures.append("field_authorization_hash_mismatch")
    except ValueError as exc:
        invariant_failures.append(str(exc))

    try:
        calibrations = _calibrations(packet_dir, file_manifest)
        custody = _custody(packet_dir, file_manifest)
    except ValueError as exc:
        invariant_failures.append(str(exc))
        calibrations = {}
        custody = {}

    if invariant_failures:
        receipt = _gap_receipt(
            packet_id=packet_id,
            reasons=invariant_failures,
            missing_direct=config["required_direct_metrics"],
            missing_operational=config["required_operational_metrics"],
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "final_receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return receipt

    rows: list[dict[str, str]] = []
    for name in ("field_observations.csv", "operator_observations.csv"):
        source_rows = _read_csv(packet_dir / name)
        for row in source_rows:
            missing_columns = OBSERVATION_COLUMNS - row.keys()
            if missing_columns:
                raise ValueError(
                    f"observation_columns_missing:{name}:{','.join(sorted(missing_columns))}"
                )
        rows.extend(source_rows)

    observations: list[dict[str, Any]] = []
    rejected: list[str] = []
    source_ids: set[str] = set()
    for row in rows:
        record_id = row.get("record_id", "") or "unnamed"
        try:
            metric = row["metric"]
            location_id = row["location_id"]
            location = config["fixed_locations"][location_id]
            if metric not in location["metrics"]:
                raise ValueError("metric_location_mismatch")
            if row["unit"] not in config["accepted_units"][metric]:
                raise ValueError("unit_not_accepted")
            observed = _parse_utc(row["observed_at"])
            if not window_start <= observed <= window_end:
                raise ValueError("observation_outside_packet_window")
            source_record_id = row["source_record_id"]
            if not source_record_id or source_record_id in source_ids:
                raise ValueError("source_record_id_missing_or_duplicate")
            source_ids.add(source_record_id)

            latitude = float(row["latitude"]) if row["latitude"] else None
            longitude = float(row["longitude"]) if row["longitude"] else None
            if metric in FIELD_METRICS:
                if latitude is None or longitude is None:
                    raise ValueError("field_coordinate_required")
                distance = _distance_km(
                    latitude,
                    longitude,
                    float(location["latitude"]),
                    float(location["longitude"]),
                )
                if distance > float(config["coordinate_tolerance_km"]):
                    raise ValueError("field_coordinate_outside_tolerance")
                if metric in IN_SITU_METRICS:
                    calibration_id = row["calibration_record_id"]
                    calibration = calibrations.get(calibration_id)
                    if calibration is None:
                        raise ValueError("calibration_record_missing")
                    if calibration["instrument_id"] != row["instrument_id"]:
                        raise ValueError("instrument_calibration_mismatch")
                    if not (
                        _parse_utc(calibration["calibrated_at"])
                        <= observed
                        <= _parse_utc(calibration["expires_at"])
                    ):
                        raise ValueError("calibration_not_valid_at_observation")
                _verify_file(packet_dir, row["photo_file"], file_manifest)
                _verify_file(packet_dir, row["field_note_file"], file_manifest)

            raw_hash = _verify_file(packet_dir, row["raw_file"], file_manifest)
            if metric in LAB_METRICS:
                sample_id = row["sample_id"]
                if not sample_id or sample_id not in custody:
                    raise ValueError("complete_chain_of_custody_required")

            value: float | str | bool
            raw_value = row["value"]
            try:
                value = float(raw_value)
            except ValueError:
                lowered = raw_value.lower()
                value = (
                    lowered == "true"
                    if lowered in {"true", "false"}
                    else raw_value
                )
            observation = build_observation(
                source_id=f"FIELD_PACKET:{packet_id}",
                source_record_id=source_record_id,
                source_hash=raw_hash,
                provider=row["provider"],
                location_id=location_id,
                metric=metric,
                value=value,
                unit=row["unit"],
                observed_at=observed,
                window_id=str(manifest["observation_window_id"]),
                qa_status=row["qa_status"],
                method=(
                    f"instrument={row['instrument_id']};"
                    f"calibration={row['calibration_record_id']};"
                    f"sample={row['sample_id'] or 'none'}"
                ),
                notes=row["notes"] or None,
            )
            observations.append(observation)
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append(f"{record_id}:{exc}")

    service = WaterIncidentService(output_dir / "shadow_store")
    intake_receipts = [
        service.intake(observation, f"FIELD_PACKET:{packet_id}:{observation['observation_id']}")
        for observation in observations
    ]
    summary = service.laguna_cartagena_summary(now=datetime.now(timezone.utc))
    current = summary["current_condition"]
    missing_direct = list(current["missing_required_metrics"])
    missing_operational = list(summary["synchronization"].get("missing_metrics", []))
    outcome = (
        "complete_direct_and_operational_window"
        if not missing_direct
        and summary["synchronization"]["status"] == "synchronized"
        else "partial_packet"
        if observations
        else "explicit_gap_receipt"
    )
    receipt = {
        "schema_version": "aguayluz.laguna-cartagena-field-packet-receipt/v0.4",
        "packet_id": packet_id,
        "outcome": outcome,
        "candidate_observation_count": len(rows),
        "ingested_observation_count": len(observations),
        "rejected_records": rejected,
        "missing_direct_metrics": missing_direct,
        "missing_operational_metrics": missing_operational,
        "current_condition_status": current["status"],
        "synchronization_status": summary["synchronization"]["status"],
        "water_balance_status": summary["water_balance"]["status"],
        "root_cause_claim": summary["water_balance"].get("root_cause_claim"),
        "shadow_mode": True,
        "notifications_enabled": False,
        "automatic_control_actions_enabled": False,
        "production_promotion_enabled": False,
        "automatic_leakage_claim": None,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("candidate_observations.json", observations),
        ("intake_receipts.json", intake_receipts),
        ("control_plane_summary.json", summary),
        ("final_receipt.json", receipt),
    ):
        (output_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet_dir", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/laguna_cartagena_field_packet"),
    )
    args = parser.parse_args()
    receipt = validate_and_ingest(args.packet_dir, args.output_dir)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
