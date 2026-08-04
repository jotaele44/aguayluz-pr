from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from operators.laguna_cartagena_probe.http_client import neon_data_url
from operators.laguna_cartagena_probe.model import (
    ALL_USGS_SITE_IDS,
    FetchReceipt,
    build_observation,
)
from operators.laguna_cartagena_probe.replay import (
    run_replay_matrix,
    validate_replay_matrix,
)
from operators.laguna_cartagena_probe.runner import _assert_secret_absent
from operators.laguna_cartagena_probe.usgs import (
    parse_usgs_iv,
    parse_usgs_ogc,
    parse_wqx3_csv,
)
from server.backend.water_disruption import WaterIncidentService

NOW = datetime(2026, 8, 4, 21, 0, tzinfo=timezone.utc)


def receipt(source_id: str, sha: str = "a" * 64) -> FetchReceipt:
    return FetchReceipt(
        source_id=source_id,
        provider="USGS",
        url="https://example.invalid",
        retrieved_at=NOW.isoformat(),
        http_status=200,
        content_type="application/json",
        etag=None,
        last_modified=None,
        byte_count=1,
        sha256=sha,
        raw_path=f"raw/{source_id}.bin",
        error=None,
    )


def test_exact_acquisition_universe() -> None:
    assert ALL_USGS_SITE_IDS == (
        "50129899",
        "50129900",
        "180046067053700",
        "50128905",
        "50128940",
    )
    assert "GUIL" not in ALL_USGS_SITE_IDS


def test_neon_token_is_header_only() -> None:
    url = neon_data_url("DP1.00044.001", "2026-08")
    assert "token" not in url.lower()
    assert "key" not in url.lower()


def test_usgs_iv_mapping_is_canonical() -> None:
    observed = "2026-08-04T20:00:00.000-04:00"
    document = {
        "value": {
            "timeSeries": [
                {
                    "sourceInfo": {"siteCode": [{"value": "50128905"}]},
                    "variable": {
                        "variableCode": [{"value": "00060"}],
                        "unit": {"unitCode": "ft3/s"},
                    },
                    "values": [
                        {
                            "value": [
                                {
                                    "value": "30",
                                    "dateTime": observed,
                                    "qualifiers": ["P"],
                                }
                            ]
                        }
                    ],
                },
                {
                    "sourceInfo": {"siteCode": [{"value": "50128940"}]},
                    "variable": {
                        "variableCode": [{"value": "00060"}],
                        "unit": {"unitCode": "ft3/s"},
                    },
                    "values": [
                        {
                            "value": [
                                {
                                    "value": "20",
                                    "dateTime": observed,
                                    "qualifiers": ["A"],
                                }
                            ]
                        }
                    ],
                },
            ]
        }
    }
    rows = parse_usgs_iv(json.dumps(document).encode(), receipt("iv"))
    assert [row["metric"] for row in rows] == ["canal_release", "terminal_flow"]
    assert {row["unit"] for row in rows} == {"ft3/s"}
    assert all(row["shadow_mode"] for row in rows)


def test_usgs_ogc_parser_accepts_exact_fresh_feature() -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "feature-1",
                "type": "Feature",
                "properties": {
                    "monitoring_location_id": "USGS-50129900",
                    "parameter_code": "00060",
                    "time": "2026-08-04T20:15:00Z",
                    "value": 4.5,
                    "unit_of_measure": "ft3/s",
                    "approval_status": "Approved",
                },
            }
        ],
    }
    rows = parse_usgs_ogc(json.dumps(document).encode(), receipt("ogc", "c" * 64))
    assert len(rows) == 1
    assert rows[0]["metric"] == "outflow_discharge"
    assert rows[0]["qa_status"] == "accepted"
    assert rows[0]["direct_or_proxy"] == "direct"


def test_wqx3_exact_site_and_characteristic_mapping() -> None:
    body = (
        "MonitoringLocationIdentifier,CharacteristicName,ActivityStartDate,"
        "ActivityStartTime/Time,ResultMeasureValue,ResultMeasure/MeasureUnitCode,"
        "ResultIdentifier\n"
        "USGS-50129899,Specific conductance,2026-08-04,12:00:00,500,uS/cm,R1\n"
        "USGS-OTHER,pH,2026-08-04,12:00:00,7.1,std units,R2\n"
    ).encode()
    rows = parse_wqx3_csv(body, receipt("wqx", "b" * 64), "50129899")
    assert len(rows) == 1
    assert rows[0]["metric"] == "specific_conductance"
    assert rows[0]["location_id"] == "50129899"
    assert rows[0]["direct_or_proxy"] == "direct"


def test_replay_matrix_preserves_fail_closed_invariants() -> None:
    matrix = run_replay_matrix(NOW)
    assert validate_replay_matrix(matrix) == []
    assert matrix["stale_direct"]["eligible_flags"] == [False]
    assert "guil_not_lajas_groundwater_substitute" in (
        matrix["guil_substitution"]["eligibility_reasons"][0]
    )
    assert matrix["unsynchronized_balance"]["water_balance_status"] == "not_computed"
    assert matrix["mixed_unit_balance"]["water_balance_status"] == "not_computed"
    assert matrix["negative_residual"]["water_balance_status"] == (
        "contradictory_negative_residual"
    )
    assert matrix["positive_residual"]["water_balance_status"] == (
        "unexplained_positive_residual"
    )
    assert matrix["positive_residual"]["root_cause_claim"] is None


def test_secret_absence_guard() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "safe.json").write_text('{"ok": true}', encoding="utf-8")
        _assert_secret_absent(root, "super-secret-token")
        (root / "bad.bin").write_bytes(b"prefix-super-secret-token-suffix")
        with pytest.raises(RuntimeError, match="secret_materialized"):
            _assert_secret_absent(root, "super-secret-token")


def test_stale_live_candidate_remains_ineligible() -> None:
    row = build_observation(
        source_id="test",
        source_record_id="stale-canal",
        source_hash="d" * 64,
        provider="USGS",
        location_id="50128905",
        metric="canal_release",
        value=30,
        unit="ft3/s",
        observed_at=NOW - timedelta(days=7),
        window_id="STALE_CANAL",
        qa_status="accepted",
    )
    with tempfile.TemporaryDirectory() as tmp:
        service = WaterIncidentService(Path(tmp))
        result = service.intake(row, "stale-canal")
    assert result["current_condition_eligible"] is False
    assert "stale_observation" in result["eligibility_reasons"]
