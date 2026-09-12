"""Durability, isolation, and rollback gates for local diagnostic state."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest
from server.backend.operator_state import OperatorState, OperatorStateError


def test_empty_reads_do_not_create_database(tmp_path):
    path = tmp_path / "state" / "operator.sqlite"
    store = OperatorState(path)
    assert store.snapshot("asset") == {}
    assert store.status()["state"] == "not_initialized"
    assert not path.parent.exists()


def test_reopen_keeps_namespaces_and_merges_fields(tmp_path):
    path = tmp_path / "operator.sqlite"
    OperatorState(path).update("asset", "same-id", {"status": "inactive"})
    OperatorState(path).update("asset", "same-id", {"review_status": "needs_review"})
    OperatorState(path).update("event", "same-id", {"resolution_status": "acknowledged"})
    OperatorState(path).update("review", "same-id", {"decision": "accept", "source_binding": "a" * 64})
    reopened = OperatorState(path)
    assert reopened.snapshot("asset")["same-id"]["values"] == {"status": "inactive", "review_status": "needs_review"}
    assert reopened.snapshot("event")["same-id"]["values"] == {"resolution_status": "acknowledged"}
    assert reopened.snapshot("review")["same-id"]["values"] == {"decision": "accept", "source_binding": "a" * 64}
    assert reopened.status()["saved_records"] == 3
    assert reopened.status()["audit_entries"] == 4


def test_concurrent_disjoint_edits_do_not_lose_fields(tmp_path):
    path = tmp_path / "operator.sqlite"
    barrier = Barrier(2)

    def write(patch):
        barrier.wait(timeout=30)
        OperatorState(path).update("asset", "A", patch)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(write, patch) for patch in [{"status": "damaged"}, {"review_status": "blocked"}]]
        for result in results:
            result.result(timeout=60)
    assert OperatorState(path).snapshot("asset")["A"]["values"] == {"status": "damaged", "review_status": "blocked"}
    assert OperatorState(path).status()["audit_entries"] == 2


def test_audit_failure_rolls_back_override(tmp_path):
    path = tmp_path / "operator.sqlite"
    store = OperatorState(path)
    store.update("asset", "A", {"status": "active"})
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON operator_audit BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
    with pytest.raises(OperatorStateError, match="could not be saved"):
        store.update("asset", "A", {"status": "damaged"})
    assert store.snapshot("asset")["A"]["values"] == {"status": "active"}
    assert store.status()["audit_entries"] == 1


@pytest.mark.parametrize("patch", [{}, [], {"status": None}, {"status": "made_up"}, {"asset_id": "other"}])
def test_invalid_patches_do_not_create_state(tmp_path, patch):
    store = OperatorState(tmp_path / "operator.sqlite")
    with pytest.raises(ValueError):
        store.update("asset", "A", patch)
    assert not store.path.exists()


def test_corrupted_database_is_not_silently_reset(tmp_path):
    path = tmp_path / "operator.sqlite"
    path.write_bytes(b"preserve this invalid database")
    store = OperatorState(path)
    with pytest.raises(OperatorStateError):
        store.snapshot("asset")
    with pytest.raises(OperatorStateError):
        store.update("asset", "A", {"status": "active"})
    assert path.read_bytes() == b"preserve this invalid database"


def test_invalid_stored_fields_cannot_replace_identity(tmp_path):
    path = tmp_path / "operator.sqlite"
    store = OperatorState(path)
    store.update("asset", "A", {"status": "active"})
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE operator_overrides SET payload=?", (json.dumps({"asset_id": "B"}),))
    with pytest.raises(OperatorStateError):
        store.snapshot("asset")
