from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from prii_export_utils import fid

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "enforce_federation_review_quarantine.py"
    spec = importlib.util.spec_from_file_location("review_quarantine", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path):
    outputs = tmp_path / "outputs"
    fed = outputs / "federation"

    assets = [
        {"asset_id": "A_ACCEPT", "asset_name": "Accepted asset", "review_status": "accepted"},
        {"asset_id": "A_LEGACY", "asset_name": "Legacy accepted asset", "review_status": "approved"},
        {"asset_id": "A_BLOCKED", "asset_name": "Blocked asset", "review_status": "blocked"},
    ]
    events = [
        {"event_id": "E_ACCEPT", "event_type": "outage", "affected_area": "Ponce", "review_status": "accepted"},
        {"event_id": "E_REVIEW", "event_type": "outage", "affected_area": "Ponce", "review_status": "needs_review"},
    ]
    alerts = [
        {"alert_id": "AL_ACCEPT", "review_status": "accepted"},
        {"alert_id": "AL_BLOCKED", "review_status": "blocked"},
    ]
    _json(outputs / "utility_assets.json", assets)
    _json(outputs / "service_events.json", events)
    _json(outputs / "alert_events.json", alerts)

    src = {
        "source_id": "src_" + "a" * 32,
        "source_type": "public_record",
        "source_name": "fixture",
        "source_ref": "fixture",
    }
    asset_ids = {row["asset_id"]: fid("ent", "asset", row["asset_id"]) for row in assets}
    event_ids = {row["event_id"]: fid("ent", "event", row["event_id"]) for row in events}
    op_id = fid("ent", "operator", "fixture-operator")
    muni_id = fid("ent", "municipality", "ponce")

    entities = [
        {
            "entity_id": eid,
            "source_id": src["source_id"],
            "entity_type": "utility_asset",
            "name": rid,
            "attributes": {"review_status": next(a["review_status"] for a in assets if a["asset_id"] == rid)},
        }
        for rid, eid in asset_ids.items()
    ] + [
        {"entity_id": eid, "source_id": src["source_id"], "entity_type": "service_event", "name": rid}
        for rid, eid in event_ids.items()
    ] + [
        {"entity_id": op_id, "source_id": src["source_id"], "entity_type": "utility_operator", "name": "op"},
        {"entity_id": muni_id, "source_id": src["source_id"], "entity_type": "municipality", "name": "Ponce"},
    ]

    def rel(left, kind, right, suffix):
        return {
            "relationship_id": "rel_" + suffix * 32,
            "source_id": src["source_id"],
            "evidence_source_id": src["source_id"],
            "source_entity_id": left,
            "target_entity_id": right,
            "relationship_type": kind,
        }

    relationships = [
        rel(asset_ids["A_ACCEPT"], "operated_by", op_id, "1"),
        rel(asset_ids["A_LEGACY"], "located_in", muni_id, "2"),
        rel(asset_ids["A_BLOCKED"], "operated_by", op_id, "3"),
        rel(asset_ids["A_ACCEPT"], "affected_by", event_ids["E_ACCEPT"], "4"),
        rel(asset_ids["A_ACCEPT"], "affected_by", event_ids["E_REVIEW"], "5"),
    ]

    canonical_alerts = [
        {
            "alert_id": fid("alrt", "AL_ACCEPT"),
            "source_id": src["source_id"],
            "module": "POWER_OPS",
            "alert_type": "outage",
            "severity": 5,
            "status": "active",
            "is_critical": True,
            "attributes": {"review_status": "accepted"},
        },
        {
            "alert_id": fid("alrt", "AL_BLOCKED"),
            "source_id": src["source_id"],
            "module": "POWER_OPS",
            "alert_type": "outage",
            "severity": 5,
            "status": "active",
            "is_critical": True,
            "entity_id": asset_ids["A_BLOCKED"],
            "attributes": {"review_status": "blocked"},
        },
    ]

    _jsonl(fed / "sources.jsonl", [src])
    _jsonl(fed / "entities.jsonl", entities)
    _jsonl(fed / "relationships.jsonl", relationships)
    _jsonl(fed / "alerts.jsonl", canonical_alerts)
    _json(
        fed / "manifest.json",
        {
            "package_id": "pkg_old",
            "producer": "aguayluz-pr",
            "export_contract_version": "1.0.0",
            "mode": "test",
            "files": [],
        },
    )
    return outputs, fed, asset_ids, event_ids


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_quarantine_preserves_evidence_but_admits_only_accepted(tmp_path):
    module = _load_module()
    outputs, fed, asset_ids, event_ids = _fixture(tmp_path)

    receipt = module.enforce(outputs, fed)

    assert receipt["state"] == "PASS"
    assert receipt["raw_counts"] == {"assets": 3, "events": 2, "alerts": 2}
    assert receipt["accepted_input_counts"] == {"assets": 2, "events": 1, "alerts": 1}
    assert receipt["quarantined_input_counts"]["total"] == 3
    assert receipt["legacy_alias_count"] == 1

    assert len(json.loads((outputs / "utility_assets.json").read_text())) == 3
    assert len(json.loads((outputs / "service_events.json").read_text())) == 2

    entities = _read_jsonl(fed / "entities.jsonl")
    entity_ids = {row["entity_id"] for row in entities}
    assert asset_ids["A_ACCEPT"] in entity_ids
    assert asset_ids["A_LEGACY"] in entity_ids
    assert asset_ids["A_BLOCKED"] not in entity_ids
    assert event_ids["E_ACCEPT"] in entity_ids
    assert event_ids["E_REVIEW"] not in entity_ids

    legacy = next(row for row in entities if row["entity_id"] == asset_ids["A_LEGACY"])
    assert legacy["attributes"]["review_status_raw"] == "approved"
    assert legacy["attributes"]["review_status"] == "accepted"
    assert legacy["attributes"]["promotion_eligible"] is True

    relationships = _read_jsonl(fed / "relationships.jsonl")
    assert all(
        row["source_entity_id"] in entity_ids and row["target_entity_id"] in entity_ids
        for row in relationships
    )
    assert not any(row["target_entity_id"] == event_ids["E_REVIEW"] for row in relationships)

    alerts = _read_jsonl(fed / "alerts.jsonl")
    assert [row["alert_id"] for row in alerts] == [fid("alrt", "AL_ACCEPT")]
    assert alerts[0]["attributes"]["review_status"] == "accepted"

    quarantine = json.loads((outputs / "review_quarantine_receipt.json").read_text())
    assert {item["review_status"] for item in quarantine["quarantined"]} == {"blocked", "needs_review"}


def test_unknown_review_state_fails_closed(tmp_path):
    module = _load_module()
    outputs, fed, *_ = _fixture(tmp_path)
    assets = json.loads((outputs / "utility_assets.json").read_text())
    assets[0]["review_status"] = "mystery"
    _json(outputs / "utility_assets.json", assets)

    with pytest.raises(module.QuarantineError, match="missing/unknown"):
        module.enforce(outputs, fed)


def test_blocked_critical_alert_never_survives_canonical_stream(tmp_path):
    module = _load_module()
    outputs, fed, *_ = _fixture(tmp_path)

    module.enforce(outputs, fed)
    alerts = _read_jsonl(fed / "alerts.jsonl")

    blocked = fid("alrt", "AL_BLOCKED")
    assert all(row["alert_id"] != blocked for row in alerts)
    assert all(row["attributes"]["promotion_eligible"] is True for row in alerts)


def test_manifest_recomputed_with_all_four_streams(tmp_path):
    module = _load_module()
    outputs, fed, *_ = _fixture(tmp_path)

    module.enforce(outputs, fed)
    manifest = json.loads((fed / "manifest.json").read_text())

    assert manifest["review_quarantine_policy"] == module.POLICY_VERSION
    assert [entry["stream"] for entry in manifest["files"]] == list(module.STREAM_ORDER)
    for entry in manifest["files"]:
        path = fed / entry["filename"]
        assert path.is_file()
        assert entry["record_count"] == len(_read_jsonl(path))
