"""Candidate review controls, concurrent edits and exact-source preservation."""
import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aguayluz.electricity.evidence import GeneratorClaim, SourceReceipt
from aguayluz.electricity.projection import electricity_projection
from aguayluz.electricity.review import (
    EMPTY_REVISION,
    ReviewError,
    ReviewLedger,
    ReviewRequest,
    claim_identifier,
)
from aguayluz.electricity.store import EvidenceStore

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def seed(root):
    store = EvidenceStore(root)
    raw = b"synthetic candidate source, not an official workbook"
    digest = hashlib.sha256(raw).hexdigest()
    store.capture(raw, SourceReceipt(sha256=digest, byte_count=len(raw),
                  source_url="https://www.eia.gov/electricity/data/eia860m/",
                  retrieved_at=NOW, authority="Synthetic fixture", schema_signature="test-only/v1"))
    base = dict(source_system="EIA-860M", plant_id="1", generator_id="01", valid_from=NOW,
                name="Synthetic fixture", nameplate_mw=1, status="OP", receipt_sha256=digest)
    store.add_claims([GeneratorClaim(**base), GeneratorClaim(**(base | {"nameplate_mw": 2})),
                      GeneratorClaim(**(base | {"generator_id": "1"}))])
    return store


def request(projection, **updates):
    return ReviewRequest(**({"request_id": uuid4().hex, "source_revision": projection["revision"],
                            "expected_review_revision": EMPTY_REVISION,
                            "claim_id": claim_identifier(projection["generator_claims"][0]),
                            "action": "DEFER", "reason_code": "ORIGINAL_REQUIRED"} | updates))


def science(projection):
    return {key: value for key, value in projection.items() if key != "generated_at"}


def test_empty_review_read_never_creates_a_database(tmp_path):
    root = tmp_path / "absent"
    source = electricity_projection(EvidenceStore(root))
    result = ReviewLedger(root).snapshot(source)
    assert result["events"] == result["claims"] == []
    assert result["revision"] == EMPTY_REVISION
    assert not root.exists()


def test_review_reverse_restores_prior_recommendation_without_mutating_science(tmp_path):
    store = seed(tmp_path)
    source = electricity_projection(store)
    ledger = ReviewLedger(tmp_path)
    first = ledger.append(source, request(source))["event"]
    second = ledger.append(source, request(source, expected_review_revision=first["event_id"],
                                          action="RECOMMEND_EXCLUDE"))["event"]
    reverse = ledger.append(source, request(source, action="REVERSE", reverses=second["event_id"],
                                           expected_review_revision=second["event_id"]))["event"]
    active = next(c for c in ledger.snapshot(source)["claims"] if c["claim_id"] == first["claim_id"])
    assert active["active_recommendation"] == first["event_id"]
    ledger.append(source, request(source, action="REVERSE", reverses=first["event_id"],
                                 expected_review_revision=reverse["event_id"]))
    result = ledger.snapshot(source)
    assert all(c["active_action"] is None for c in result["claims"])
    assert len(result["events"]) == 4
    assert all(e["review_state"] == "AUDIT_ONLY" and e["canonical_promotion"] == "BLOCKED" for e in result["events"])
    assert science(electricity_projection(store)) == science(source)
    assert len(source["generator_claims"]) == 3 and source["contradictions"]


def test_full_claim_hash_distinguishes_rows_sharing_receipt_and_literal_identifiers(tmp_path):
    source = electricity_projection(seed(tmp_path))
    claims = ReviewLedger(tmp_path).snapshot(source)["claims"]
    assert len({c["claim_id"] for c in claims}) == 3
    assert len({c["receipt_sha256"] for c in claims}) == 1
    assert {c["source_identity"] for c in claims} == {"EIA-860M:1:01", "EIA-860M:1:1"}


@pytest.mark.parametrize("updates", [
    {"action": "PROMOTE"}, {"reason_code": "unbounded secret text"}, {"actor": "administrator"},
    {"claim_id": "../x"}, {"source_revision": None}, {"request_id": "bad"},
    {"action": "REVERSE"}, {"reverses": "b" * 64}, {"canonical_promotion": "PASS"},
])
def test_review_request_rejects_unsafe_or_unsupported_fields(tmp_path, updates):
    source = electricity_projection(seed(tmp_path))
    with pytest.raises(ValidationError):
        request(source, **updates)


def test_idempotent_retry_survives_later_source_and_review_appends(tmp_path):
    store = seed(tmp_path)
    source = electricity_projection(store)
    ledger = ReviewLedger(tmp_path)
    body = request(source)
    first = ledger.append(source, body)
    ledger.append(source, request(source, expected_review_revision=first["event"]["event_id"]))
    store.record_attempt("EIA_RETRY_EXHAUSTED")
    retry = ledger.append(electricity_projection(store), body)
    assert retry == {"event": first["event"], "replayed": True}
    assert len(ledger.snapshot(electricity_projection(store))["events"]) == 2
    with pytest.raises(ReviewError, match="REQUEST_ID_CONFLICT"):
        ledger.append(source, body.model_copy(update={"reason_code": "STATUS_CONFLICT"}))


@pytest.mark.parametrize("updates,code", [
    ({"source_revision": "f" * 64}, "SOURCE_REVISION_STALE"),
    ({"expected_review_revision": "f" * 64}, "REVIEW_REVISION_STALE"),
    ({"claim_id": "f" * 64}, "CLAIM_UNKNOWN"),
    ({"action": "REVERSE", "reverses": "f" * 64}, "REVERSAL_NOT_ACTIVE"),
])
def test_stale_unknown_and_inactive_writes_are_refused(tmp_path, updates, code):
    source = electricity_projection(seed(tmp_path))
    ledger = ReviewLedger(tmp_path)
    with pytest.raises(ReviewError, match=code):
        ledger.append(source, request(source, **updates))
    assert ledger.snapshot(source)["events"] == []


def test_cannot_reverse_another_claim_or_an_overridden_recommendation(tmp_path):
    source = electricity_projection(seed(tmp_path))
    ledger = ReviewLedger(tmp_path)
    first = ledger.append(source, request(source))["event"]
    second = ledger.append(source, request(source, expected_review_revision=first["event_id"]))["event"]
    for identifier in [first["claim_id"], claim_identifier(source["generator_claims"][-1])]:
        with pytest.raises(ReviewError, match="REVERSAL_NOT_ACTIVE"):
            ledger.append(source, request(source, claim_id=identifier, action="REVERSE",
                                         reverses=first["event_id"], expected_review_revision=second["event_id"]))


def test_concurrent_operators_with_same_expected_head_allow_one_append(tmp_path):
    source = electricity_projection(seed(tmp_path))
    def submit(_):
        try:
            return ReviewLedger(tmp_path).append(source, request(source))["event"]["sequence"]
        except ReviewError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(submit, range(8)))
    assert outcomes.count(1) == 1
    assert outcomes.count("REVIEW_REVISION_STALE") == 7
    assert len(ReviewLedger(tmp_path).snapshot(source)["events"]) == 1


def test_review_immutable_and_checksum_fail_closed_on_corrupt_payload(tmp_path):
    source = electricity_projection(seed(tmp_path))
    ledger = ReviewLedger(tmp_path)
    ledger.append(source, request(source))
    with sqlite3.connect(ledger.path) as db:
        for statement in ["DELETE FROM review_events", "UPDATE review_events SET event_id='changed'"]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(statement)
        db.execute("DROP TRIGGER review_no_update")
        db.execute("UPDATE review_events SET event_id=?", ("f" * 64,))
    with pytest.raises(ValueError, match="integrity"):
        ledger.snapshot(source)
    with pytest.raises(ValueError, match="integrity"):
        ledger.append(source, request(source))


def test_review_detects_orphan_claim_and_refuses_database_symlink(tmp_path):
    source = electricity_projection(seed(tmp_path / "source"))
    ledger = ReviewLedger(tmp_path / "source")
    ledger.append(source, request(source))
    with pytest.raises(ValueError, match="integrity"):
        ledger.snapshot(source | {"generator_claims": []})
    alias = tmp_path / "alias"
    alias.mkdir()
    (alias / "reviews.sqlite3").symlink_to(ledger.path)
    with pytest.raises(ValueError, match="symlinks"):
        ReviewLedger(alias).snapshot(source)
    with pytest.raises(ValueError, match="symlinks"):
        ReviewLedger(alias).append(source, request(source))


def test_insert_failure_rolls_back_and_retry_can_complete(tmp_path):
    source = electricity_projection(seed(tmp_path))
    ledger = ReviewLedger(tmp_path)
    with closing(ledger._connect()) as db, db:
        db.execute("CREATE TRIGGER reject_test BEFORE INSERT ON review_events BEGIN SELECT RAISE(ABORT, 'test write failure'); END")
    body = request(source)
    with pytest.raises(sqlite3.IntegrityError, match="test write failure"):
        ledger.append(source, body)
    assert ledger.snapshot(source)["events"] == []
    with sqlite3.connect(ledger.path) as db:
        db.execute("DROP TRIGGER reject_test")
    assert ledger.append(source, body)["event"]["sequence"] == 1


def test_review_api_auth_conflict_integrity_and_original_contract(tmp_path, monkeypatch):
    from server.backend import electricity_api
    from server.backend.app import app
    monkeypatch.setattr(electricity_api.legacy, "DATA", tmp_path)
    store = seed(tmp_path / "electricity")
    client = TestClient(app)
    path = "/electricity/v1/reviews"
    source = client.get("/electricity/v1/projection").json()
    body = request(source).model_dump(mode="json")
    monkeypatch.delenv("API_SECRET_KEY", raising=False)
    assert client.post(path, json=body).status_code == 503
    monkeypatch.setenv("API_SECRET_KEY", "synthetic-review-role")
    assert client.post(path, json=body).status_code == 401
    headers = {"Authorization": "Bearer synthetic-review-role"}
    assert client.post(path, json=body | {"actor": "forged"}, headers=headers).status_code == 422
    assert client.post(path, json=body | {"source_revision": "f" * 64}, headers=headers).status_code == 409
    success = client.post(path, json=body, headers=headers)
    assert success.status_code == 200
    assert success.json()["event"]["actor"] == "SHARED_OPERATOR_KEY"
    assert client.post(path, json=body, headers=headers).json()["replayed"] is True
    result = client.get(path).json()
    schema = json.loads((Path(__file__).parents[1] / "schemas/electricity_reviews.v1.schema.json").read_text())
    jsonschema.validate(result, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result | {"canonical_promotion": "PASS"}, schema)
    assert science(client.get("/electricity/v1/projection").json()) == science(source)
    assert science(electricity_projection(store)) == science(source)
    (store.root / "raw" / source["sources"][0]["sha256"]).write_bytes(b"broken source")
    assert client.get(path).status_code == 503
    assert client.post(path, json=body, headers=headers).status_code == 503
    assert "broken source" not in client.get(path).text


def test_restore_both_ledgers_preserves_review_and_scientific_revisions(tmp_path):
    live = tmp_path / "live"
    store = seed(live)
    source = electricity_projection(store)
    ledger = ReviewLedger(live)
    first = ledger.append(source, request(source))
    expected = ledger.snapshot(source)
    backup = tmp_path / "restored"
    backup.mkdir()
    # Writers are quiescent. Back up both databases before comparing raw bytes.
    for name in ["ledger.sqlite3", "reviews.sqlite3"]:
        with sqlite3.connect(live / name) as original, sqlite3.connect(backup / name) as restored:
            original.backup(restored)
    shutil.copytree(live / "raw", backup / "raw")
    ledger.append(source, request(source, expected_review_revision=first["event"]["event_id"]))
    restored_source = electricity_projection(EvidenceStore(backup))
    assert science(restored_source) == science(source)
    assert ReviewLedger(backup).snapshot(restored_source) == expected
    assert len(ledger.snapshot(source)["events"]) == 2
