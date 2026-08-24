from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from operators.laguna_cartagena_field_packet import validate_and_ingest  # noqa: E402


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_blank_packet_produces_explicit_gap_receipt(tmp_path: Path) -> None:
    packet = REPO_ROOT / "templates" / "laguna_cartagena" / "v0.4" / "blank_packet"
    receipt = validate_and_ingest(packet, tmp_path / "out")
    assert receipt["outcome"] == "explicit_gap_receipt"
    assert receipt["current_condition_status"] == "unknown"
    assert receipt["ingested_observation_count"] == 0
    assert receipt["automatic_leakage_claim"] is None


def test_complete_synthetic_packet_is_provenance_bound(tmp_path: Path) -> None:
    packet = tmp_path / "packet"
    evidence = packet / "evidence"
    evidence.mkdir(parents=True)
    files = {
        "evidence/authorization.pdf": b"authorized field access",
        "evidence/calibration.pdf": b"calibration certificate",
        "evidence/raw.bin": b"raw observation export",
        "evidence/photo.jpg": b"location photograph",
        "evidence/note.txt": b"field notes",
        "evidence/lab_report.pdf": b"laboratory report",
    }
    for relative, content in files.items():
        path = packet / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(hours=1)
    end = now + timedelta(minutes=30)
    manifest = {
        "schema_version": "aguayluz.laguna-cartagena-field-packet-manifest/v0.4",
        "packet_id": "TEST_PACKET",
        "observation_window_id": "TEST_WINDOW",
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "field_authorization_status": "approved",
        "field_authorization_id": "AUTH-1",
        "field_authorization_file": "evidence/authorization.pdf",
        "field_authorization_sha256": _hash(packet / "evidence/authorization.pdf"),
        "qualified_crew_lead": "Qualified Crew Lead",
        "qualified_crew_affiliation": "Test Field Unit",
        "qualified_adult_crew_attestation": True,
        "provider_request_ids": ["AAA-1", "PREPA-1"],
        "shadow_mode": True,
        "notifications_enabled": False,
        "automatic_control_actions_enabled": False,
        "production_promotion_enabled": False,
    }
    (packet / "packet_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    file_rows = [
        {
            "path": relative,
            "sha256": _hash(packet / relative),
            "media_type": "application/octet-stream",
            "record_id": relative,
            "created_at_utc": now.isoformat(),
            "source_system": "test",
        }
        for relative in files
    ]
    _write_csv(
        packet / "file_manifest.csv",
        ["path", "sha256", "media_type", "record_id", "created_at_utc", "source_system"],
        file_rows,
    )
    calibration = {
        "calibration_record_id": "CAL-1",
        "instrument_id": "INST-1",
        "calibrated_at": (now - timedelta(days=1)).isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "standard_lot": "LOT-1",
        "certificate_file": "evidence/calibration.pdf",
        "certificate_sha256": _hash(packet / "evidence/calibration.pdf"),
        "performed_by": "Qualified Technician",
        "signature": "SIGNED",
    }
    _write_csv(
        packet / "instrument_calibrations.csv",
        list(calibration),
        [calibration],
    )
    custody_rows = []
    for metric in ("nitrate", "ammonia", "phosphorus", "fecal_indicator"):
        sample_id = f"SAMPLE-{metric}"
        custody_rows.append(
            {
                "sample_id": sample_id,
                "collection_utc": now.isoformat(),
                "collector": "Qualified Collector",
                "transfer_utc": now.isoformat(),
                "from_custodian": "Field Unit",
                "to_custodian": "Laboratory",
                "condition": "sealed",
                "seal_id": f"SEAL-{metric}",
                "lab_receipt_utc": now.isoformat(),
                "lab_report_file": "evidence/lab_report.pdf",
                "lab_report_sha256": _hash(packet / "evidence/lab_report.pdf"),
                "signature": "SIGNED",
            }
        )
    _write_csv(packet / "chain_of_custody.csv", list(custody_rows[0]), custody_rows)

    direct_specs = [
        ("lagoon_stage", "50129899", "1.0", "ft", "18.0124634301021", "-67.1087894817786"),
        ("outflow_discharge", "50129900", "5.0", "ft3/s", "18.01246343", "-67.1090673"),
        ("groundwater_level", "180046067053700", "2.0", "ft", "18.01079699", "-67.0932338"),
        ("specific_conductance", "50129899", "500", "uS/cm", "18.0124634301021", "-67.1087894817786"),
        ("water_temperature", "50129899", "28", "degC", "18.0124634301021", "-67.1087894817786"),
        ("dissolved_oxygen", "50129899", "5", "mg/L", "18.0124634301021", "-67.1087894817786"),
        ("ph", "50129899", "7.2", "standard_units", "18.0124634301021", "-67.1087894817786"),
        ("turbidity", "50129899", "10", "NTU", "18.0124634301021", "-67.1087894817786"),
        ("nitrate", "50129899", "0.4", "mg/L", "18.0124634301021", "-67.1087894817786"),
        ("ammonia", "50129899", "0.1", "mg/L", "18.0124634301021", "-67.1087894817786"),
        ("phosphorus", "50129899", "0.2", "mg/L", "18.0124634301021", "-67.1087894817786"),
        ("fecal_indicator", "50129899", "12", "count/100mL", "18.0124634301021", "-67.1087894817786"),
    ]
    columns = [
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
    ]
    field_rows = []
    for metric, location, value, unit, latitude, longitude in direct_specs:
        lab = metric in {"nitrate", "ammonia", "phosphorus", "fecal_indicator"}
        field_rows.append(
            {
                "record_id": f"FIELD-{metric}",
                "metric": metric,
                "location_id": location,
                "observed_at": now.isoformat(),
                "value": value,
                "unit": unit,
                "provider": "Authorized Test Field Crew",
                "source_record_id": f"SRC-{metric}",
                "instrument_id": "" if lab else "INST-1",
                "calibration_record_id": "" if lab else "CAL-1",
                "sample_id": f"SAMPLE-{metric}" if lab else "",
                "raw_file": "evidence/lab_report.pdf" if lab else "evidence/raw.bin",
                "photo_file": "evidence/photo.jpg",
                "field_note_file": "evidence/note.txt",
                "qa_status": "accepted",
                "latitude": latitude,
                "longitude": longitude,
                "notes": "synthetic contract test",
            }
        )
    _write_csv(packet / "field_observations.csv", columns, field_rows)

    operator_specs = [
        ("canal_release", "50128905", "100"),
        ("treatment_withdrawal", "50128905", "20"),
        ("agricultural_turnout", "50128905", "30"),
        ("terminal_flow", "50128940", "50"),
    ]
    operator_rows = [
        {
            "record_id": f"OP-{metric}",
            "metric": metric,
            "location_id": location,
            "observed_at": now.isoformat(),
            "value": value,
            "unit": "ft3/s",
            "provider": "Authorized Test Operator",
            "source_record_id": f"OP-SRC-{metric}",
            "instrument_id": "",
            "calibration_record_id": "",
            "sample_id": "",
            "raw_file": "evidence/raw.bin",
            "photo_file": "",
            "field_note_file": "",
            "qa_status": "accepted",
            "latitude": "",
            "longitude": "",
            "notes": "synthetic contract test",
        }
        for metric, location, value in operator_specs
    ]
    _write_csv(packet / "operator_observations.csv", columns, operator_rows)

    receipt = validate_and_ingest(packet, tmp_path / "out")
    assert receipt["rejected_records"] == []
    assert receipt["ingested_observation_count"] == 16
    assert receipt["missing_direct_metrics"] == []
    assert receipt["missing_operational_metrics"] == []
    assert receipt["synchronization_status"] == "synchronized"
    assert receipt["water_balance_status"] == "balanced_within_tolerance"
    assert receipt["root_cause_claim"] is None
    assert receipt["automatic_leakage_claim"] is None
