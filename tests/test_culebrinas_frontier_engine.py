import csv
import hashlib
import json
from pathlib import Path

from operators.culebrinas_frontier_engine import evaluate_packet


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packet(tmp_path: Path, *, unresolved_h: str | None = None, omit_h_evidence: str | None = None) -> Path:
    packet = tmp_path / "packet"
    packet.mkdir()
    observation_ids = [f"O{i}" for i in range(1, 11)]
    _write_csv(
        packet / "observations.csv",
        ["observation_id", "station_id", "evidence_state"],
        [{"observation_id": oid, "station_id": "S1", "evidence_state": "OBSERVED"} for oid in observation_ids],
    )
    _write_csv(packet / "station_manifest.csv", ["station_id"], [{"station_id": "S1"}])
    _write_csv(packet / "instrument_calibrations.csv", ["calibration_id"], [{"calibration_id": "C1"}])
    _write_csv(packet / "chain_of_custody.csv", ["coc_id"], [{"coc_id": "COC1"}])

    h_states = {hid: "SUPPORTED" for hid in ("H1", "H2", "H3", "H4", "H5")}
    if unresolved_h:
        h_states[unresolved_h] = "UNRESOLVED"
    h_evidence = {}
    for i, hid in enumerate(("H1", "H2", "H3", "H4", "H5")):
        if hid == omit_h_evidence:
            continue
        h_evidence[hid] = {
            "positive_evidence_ids": [observation_ids[i * 2]],
            "falsifier_test_ids": [observation_ids[i * 2 + 1]],
            "independent_methods": ["METHOD_A", "METHOD_B"],
            "falsifier_triggered": False,
        }

    readiness = {gate: True for gate in (
        "canonical_aquifer_feature_bound",
        "subsurface_census_closed",
        "usace_boring_geometry_closed",
        "uprm_seismic_interpretation_recovered",
        "head_ec_network_complete",
        "gain_loss_repeated",
        "fresh_salt_directly_observed",
        "sgd_two_independent_methods",
        "qa_qc_closed",
        "withheld_validation_set_defined",
    )}
    manifest = {
        "source_mode": "REAL_AUTHORIZED_OBSERVATIONS",
        "canonical_aquifer_feature_bound": True,
        "canonical_aquifer_globalid": "TEST-GLOBALID",
        "field_authorization_status": "approved",
        "kvi_readiness": readiness,
        "hypothesis_adjudication": h_states,
        "hypothesis_evidence": h_evidence,
        "withheld_validation_pass": True,
        "zero_material_residue": True,
        "green_federation_ci": True,
        "kvi_measured": {
            "state": "MEASURED",
            "kvi_measured": True,
            "method_version": "aguayluz.culebrinas-kvi-method/v1.0",
            "maximum_cell_id": "CELL-1",
            "maximum_kvi": 80.0,
            "ensemble_min": 78.0,
            "ensemble_max": 82.0,
            "winner_stability_fraction": 1.0,
            "evidence_schema_version": "aguayluz.culebrinas-kvi-evidence/v1.0",
            "experimental_observation_count": len(observation_ids),
            "canonical_geometry_globalid": "TEST-GLOBALID",
            "field_packet_receipt_sha256": "a" * 64,
        },
    }
    (packet / "packet_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    protected = [
        "packet_manifest.json",
        "observations.csv",
        "instrument_calibrations.csv",
        "chain_of_custody.csv",
        "station_manifest.csv",
    ]
    _write_csv(
        packet / "file_manifest.csv",
        ["path", "sha256"],
        [{"path": name, "sha256": _hash(packet / name)} for name in protected],
    )
    return packet


def test_missing_packet_fails_closed(tmp_path: Path) -> None:
    receipt = evaluate_packet(tmp_path)
    assert receipt["outcome"] == "explicit_gap_receipt"
    assert receipt["kvi_measured"] is None
    assert receipt["certification_candidate"] is False
    assert receipt["production_promotion_enabled"] is False
    assert receipt["fail_closed"] is True


def test_config_prohibits_synthetic_kvi() -> None:
    cfg = json.loads(Path("config/culebrinas_field_operator_packet.v1.json").read_text())
    assert cfg["preserve"]["no_synthetic_kvi"] is True
    assert cfg["preserve"]["no_proximity_identity"] is True
    assert cfg["canonical_geometry_required_for_new_station_binding"] is True
    assert len(cfg["kvi_readiness_gates"]) == 10


def test_hypotheses_have_required_campaigns() -> None:
    cfg = json.loads(Path("config/culebrinas_field_operator_packet.v1.json").read_text())
    assert set(cfg["campaigns"]) == {"H1", "H2", "H3", "H4", "H5"}
    assert len(cfg["campaigns"]["H5"]) >= 2


def test_unresolved_hypothesis_blocks_certification_candidate(tmp_path: Path) -> None:
    receipt = evaluate_packet(_packet(tmp_path, unresolved_h="H3"))
    assert receipt["outcome"] == "explicit_gap_receipt"
    assert "hypothesis_materially_unresolved:H3" in receipt["reasons"]
    assert receipt["certification_candidate"] is False


def test_hypothesis_without_evidence_blocks(tmp_path: Path) -> None:
    receipt = evaluate_packet(_packet(tmp_path, omit_h_evidence="H2"))
    assert receipt["outcome"] == "explicit_gap_receipt"
    assert "hypothesis_evidence_missing:H2" in receipt["reasons"]
    assert receipt["certification_candidate"] is False


def test_fully_evidenced_fixture_can_reach_candidate_only_not_promotion(tmp_path: Path) -> None:
    receipt = evaluate_packet(_packet(tmp_path))
    assert receipt["outcome"] == "experimental_evidence_complete"
    assert receipt["certification_candidate"] is True
    assert receipt["production_promotion_enabled"] is False
