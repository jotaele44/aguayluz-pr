import json
from pathlib import Path

from operators.culebrinas_frontier_engine import evaluate_packet


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
