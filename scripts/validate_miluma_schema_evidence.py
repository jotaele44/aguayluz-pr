#!/usr/bin/env python3
"""Validate the bounded MiLUMA schema-evidence receipt.

This gate deliberately distinguishes a third-party archival transform from current
receipt-verified MiLUMA source bytes. Historical field observations may harden parser
tests, but they cannot promote the live endpoint out of RAW_UNFROZEN.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECEIPT = REPO / "governance" / "miluma_schema_evidence.json"

EXPECTED_RAW_FIELDS = {"name", "totalClients", "totalClientsWithoutService"}
EXPECTED_NORMALIZED_FIELDS = {"region", "total_customers", "affected_customers"}
EXPECTED_REGIONS = {
    "ARECIBO", "BAYAMON", "CAROLINA", "CAGUAS", "MAYAGUEZ", "PONCE", "SAN JUAN"
}


def validate(doc: dict) -> None:
    assert doc["live_schema_state"] == "RAW_UNFROZEN"
    assert doc["historical_schema_state"] == "PROVISIONAL_HISTORICAL_SCHEMA"
    assert doc["certification"] == "PROVISIONAL"

    source = doc["historical_source"]
    assert source["source_type"] == "THIRD_PARTY_ARCHIVAL_TRANSFORM"
    assert source["raw_response_bytes_preserved"] is False
    assert source["transformed_rows_preserved"] is True
    assert set(source["scraper_raw_shape"]["row_fields"]) == EXPECTED_RAW_FIELDS
    assert set(source["normalized_shape"]["row_fields"]) == EXPECTED_NORMALIZED_FIELDS
    assert source["normalized_shape"]["observed_region_count"] == len(EXPECTED_REGIONS)
    assert set(source["normalized_shape"]["observed_regions"]) == EXPECTED_REGIONS

    rules = doc["promotion_rules"]
    assert rules["historical_fields_are_not_live_schema_identity"] is True
    assert rules["live_promotion_requires_receipt_verified_source_bytes"] is True
    assert rules["source_unavailable_is_zero"] is False
    assert rules["snapshot_change_is_restoration"] is False

    preb = doc["preb_comparison"]
    assert preb["live_snapshot_identity"] is False
    assert preb["restoration_event_identity"] is False
    assert preb["preliminary_values_may_be_revised"] is True


def main() -> int:
    doc = json.loads(RECEIPT.read_text(encoding="utf-8"))
    validate(doc)
    print("MILUMA_SCHEMA_EVIDENCE=PASS_PROVISIONAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
