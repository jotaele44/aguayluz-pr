"""Shape checks for the PRASA production OSINT inventory (research/prasa_production_osint_v0_1).

The inventory is evidence that open sources were swept before any public-records request,
so the properties that matter are: every source ends in a declared terminal state, every
document that was reached and is a stable file carries its SHA-256, nothing claims
completeness, and no request is recorded as sent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "research" / "prasa_production_osint_v0_1"
RECEIPTS = json.loads((HERE / "public_source_receipts.json").read_text(encoding="utf-8"))
MATRIX = json.loads((HERE / "source_coverage_matrix.json").read_text(encoding="utf-8"))
SHA = re.compile(r"^[0-9a-f]{64}$")


def test_nothing_is_claimed_complete_and_no_request_was_sent():
    assert RECEIPTS["completeness_claimed"] is False
    assert RECEIPTS["records_requests_sent"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", RECEIPTS["origin_main_sha"])


def test_every_source_has_a_unique_id_and_a_declared_terminal_state():
    sources = RECEIPTS["sources"]
    ids = [s["source_id"] for s in sources]
    assert len(ids) == len(set(ids)) and len(ids) >= 40
    assert {s["terminal_state"] for s in sources} <= set(RECEIPTS["terminal_states"])
    assert set(RECEIPTS["terminal_state_meaning"]) == set(RECEIPTS["terminal_states"])


def test_hashes_are_well_formed_and_blocked_sources_claim_nothing():
    for source in RECEIPTS["sources"]:
        if source["sha256"] is not None:
            assert SHA.match(source["sha256"]), source["source_id"]
            assert source["reached"] is True, source["source_id"]
        if source["terminal_state"] == "BLOCKED":
            assert source["reached"] is False and source["supports"] == [], source["source_id"]
        if not source["reached"]:
            assert source["sha256"] is None, source["source_id"]
        if source["reached"] and source["sha256"] is None:
            # Live APIs and regenerated metadata: the note must say why there is no hash.
            assert "hash" in source["quality_note"].lower() or "second-hand" in source["quality_note"].lower()


def test_matrix_sources_exist_and_only_unpublished_metrics_are_requested():
    ids = {s["source_id"] for s in RECEIPTS["sources"]}
    for row in MATRIX["metrics"]:
        assert row["primary_classification"] in MATRIX["classifications"], row["metric"]
        assert set(row["best_public_source"]) <= ids, row["metric"]
        if row["coverage_status"] == "covered":
            # Ley 141-2019 Art. 4: what is already published free online is outside the request.
            assert row["included_in_request"] is False, row["metric"]
        if row["coverage_status"] == "not_published":
            assert row["included_in_request"] is True and row["blockers"], row["metric"]
