"""Fault injection at the immutable source publication boundary, synthetic inputs only."""
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

import aguayluz.electricity.store as storage
from aguayluz.electricity.evidence import SourceReceipt
from aguayluz.electricity.store import EvidenceStore

RAW = b"synthetic source bytes for acquisition recovery" * 4096
DIGEST = hashlib.sha256(RAW).hexdigest()


@pytest.fixture
def receipt():
    return SourceReceipt(sha256=DIGEST, byte_count=len(RAW),
                         source_url="https://www.eia.gov/electricity/data/eia860m/",
                         authority="Synthetic recovery test, not an official source",
                         retrieved_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                         schema_signature="synthetic/recovery-v1")


@pytest.mark.parametrize("failure", ["disk_full", "short_write", "flush", "fsync"])
def test_interrupted_capture_is_retriable_without_partial_published_blob(tmp_path, receipt, monkeypatch, failure):
    store = EvidenceStore(tmp_path / "evidence")
    real_fdopen = storage.os.fdopen

    class FaultyWrite:
        def __init__(self, descriptor, mode):
            self.handle = real_fdopen(descriptor, mode)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.handle.close()

        def write(self, raw):
            if failure in {"disk_full", "short_write"}:
                count = self.handle.write(raw[:17])
                if failure == "disk_full":
                    raise OSError("synthetic disk-full interruption")
                return count
            return self.handle.write(raw)

        def flush(self):
            if failure == "flush":
                raise OSError("synthetic flush interruption")
            return self.handle.flush()

        def fileno(self):
            return self.handle.fileno()

    with monkeypatch.context() as injected:
        injected.setattr(storage.os, "fdopen", FaultyWrite)
        if failure == "fsync":
            def refuse_sync(_):
                raise OSError("synthetic fsync interruption")
            injected.setattr(storage.os, "fsync", refuse_sync)
        with pytest.raises(OSError):
            store.capture(RAW, receipt)

    assert not (store.root / "raw" / DIGEST).exists()
    assert not list((store.root / "raw").glob(".capture-*"))
    assert store.snapshot() == {"sources": [], "measurements": [], "claims": [], "attempts": []}
    identifier = store.capture(RAW, receipt)
    assert store.read_raw(DIGEST) == RAW
    assert identifier == store.capture(RAW, receipt)
    assert len(store.snapshot()["sources"]) == 1


def test_concurrent_identical_captures_publish_one_verified_blob(tmp_path, receipt):
    store = EvidenceStore(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as workers:
        identifiers = list(workers.map(lambda _: store.capture(RAW, receipt), range(24)))
    assert len(set(identifiers)) == 1
    assert sorted(p.name for p in (tmp_path / "raw").iterdir()) == [DIGEST]
    assert store.read_raw(DIGEST) == RAW
    assert len(store.snapshot()["sources"]) == 1


def test_existing_corruption_is_preserved_and_refused(tmp_path, receipt):
    store = EvidenceStore(tmp_path)
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / DIGEST).write_bytes(b"existing corrupt bytes")
    with pytest.raises(ValueError, match="integrity mismatch"):
        store.capture(RAW, receipt)
    assert (tmp_path / "raw" / DIGEST).read_bytes() == b"existing corrupt bytes"
    assert not list((tmp_path / "raw").glob(".capture-*"))
    assert not (tmp_path / "ledger.sqlite3").exists()


def test_receipt_failure_after_publication_recovers_without_rewriting_bytes(tmp_path, receipt, monkeypatch):
    store = EvidenceStore(tmp_path)
    with monkeypatch.context() as injected:
        def refuse_database():
            raise sqlite3.OperationalError("synthetic database interruption")
        injected.setattr(store, "_connect", refuse_database)
        with pytest.raises(sqlite3.OperationalError):
            store.capture(RAW, receipt)
    target = tmp_path / "raw" / DIGEST
    original_stat = target.stat()
    assert store.read_raw(DIGEST) == RAW
    store.capture(RAW, receipt)
    assert target.stat().st_ino == original_stat.st_ino
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert len(store.snapshot()["sources"]) == 1
