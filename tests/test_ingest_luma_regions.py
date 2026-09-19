"""Tests for the typed MiLUMA regional aggregate snapshot ingest."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ingest_luma_regions  # noqa: E402
from ingest_luma_regions import build_rows, resolve_receipt  # noqa: E402

OBSERVED = "2026-09-19T06:00:00Z"
SOURCE = "https://api.miluma.lumapr.com/miluma-outage-api/outage/regionsWithoutService"

def _payload():
    return {
        "regions": [
            {
                "name": "SAN JUAN",
                "totalClients": 1000,
                "totalClientsWithoutService": 25,
            },
            {
                "name": "PONCE",
                "totalClients": 500,
                "totalClientsWithoutService": 0,
            },
        ]
    }

def test_build_rows_preserves_raw_name_and_closes_customer_arithmetic():
    rows = build_rows(_payload(), OBSERVED, SOURCE, "a" * 64)
    assert len(rows) == 2
    sj = next(row for row in rows if row["region_raw"] == "SAN JUAN")
    assert sj["region_normalized"] == "SAN JUAN"
    assert sj["total_customers"] == 1000
    assert sj["affected_customers"] == 25
    assert sj["affected_pct"] == 2.5
    assert sj["source_hash"] == "a" * 64
    assert len({row["status_id"] for row in rows}) == len(rows)

def test_zero_affected_region_is_retained_as_status_not_dropped():
    rows = build_rows(_payload(), OBSERVED, SOURCE, "b" * 64)
    ponce = next(row for row in rows if row["region_raw"] == "PONCE")
    assert ponce["affected_customers"] == 0
    assert ponce["affected_pct"] == 0.0

def test_affected_greater_than_total_fails_closed():
    doc = _payload()
    doc["regions"][0]["totalClientsWithoutService"] = 1001
    with pytest.raises(ValueError):
        build_rows(doc, OBSERVED, SOURCE, "c" * 64)

def test_duplicate_normalized_region_fails_closed():
    doc = _payload()
    doc["regions"].append(
        {
            "name": "San   Juan",
            "totalClients": 1000,
            "totalClientsWithoutService": 1,
        }
    )
    with pytest.raises(ValueError):
        build_rows(doc, OBSERVED, SOURCE, "d" * 64)

def test_receipt_binds_exact_source_bytes(tmp_path):
    src = tmp_path / "regions.json"
    raw = json.dumps(_payload(), separators=(",", ":")).encode()
    src.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    meta = tmp_path / "manifest.json"
    meta.write_text(
        json.dumps(
            {
                "regions": {
                    "status": "PASS",
                    "retrieval_utc": OBSERVED,
                    "url": SOURCE,
                    "response_sha256": digest,
                }
            }
        )
    )

    assert resolve_receipt(src, meta) == (OBSERVED, SOURCE, digest)

def test_receipt_hash_mismatch_fails_closed(tmp_path):
    src = tmp_path / "regions.json"
    src.write_text(json.dumps(_payload()))
    meta = tmp_path / "manifest.json"
    meta.write_text(
        json.dumps(
            {
                "regions": {
                    "status": "PASS",
                    "retrieval_utc": OBSERVED,
                    "url": SOURCE,
                    "response_sha256": "0" * 64,
                }
            }
        )
    )

    with pytest.raises(ValueError):
        resolve_receipt(src, meta)

def test_non_pass_region_receipt_is_a_clean_source_gap(tmp_path):
    meta = tmp_path / "manifest.json"
    meta.write_text(
        json.dumps(
            {
                "regions": {
                    "status": "SOURCE_UNAVAILABLE",
                    "error": "HTTP 403",
                }
            }
        )
    )

    assert resolve_receipt(tmp_path / "missing.json", meta) is None


def test_region_main_deletes_stale_runtime_output_on_source_gap(monkeypatch, tmp_path):
    out = tmp_path / "luma_region_status.jsonl"
    out.write_text('{"stale":true}\n')
    meta = tmp_path / "manifest.json"
    meta.write_text(
        json.dumps(
            {
                "regions": {
                    "status": "SOURCE_UNAVAILABLE",
                    "error": "HTTP 403",
                }
            }
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_luma_regions.py",
            "--src",
            str(tmp_path / "missing-regions.json"),
            "--snapshot-meta",
            str(meta),
            "--out",
            str(out),
        ],
    )

    assert ingest_luma_regions.main() == 0
    assert not out.exists()
