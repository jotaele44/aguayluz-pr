"""Content-addressed evidence and transactional append-only source receipts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from aguayluz.electricity.evidence import GeneratorClaim, Measurement, SourceReceipt


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (self.root / "ledger.sqlite3").is_symlink():
            raise ValueError("evidence database symlinks refused")
        connection = sqlite3.connect(self.root / "ledger.sqlite3", timeout=10)
        os.chmod(self.root / "ledger.sqlite3", 0o600)
        connection.executescript("""
          CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS measurements (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS claims (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts
            BEGIN SELECT RAISE(ABORT, 'immutable receipt'); END;
          CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts
            BEGIN SELECT RAISE(ABORT, 'immutable receipt'); END;
          CREATE TRIGGER IF NOT EXISTS measurements_no_update BEFORE UPDATE ON measurements
            BEGIN SELECT RAISE(ABORT, 'immutable measurement'); END;
          CREATE TRIGGER IF NOT EXISTS measurements_no_delete BEFORE DELETE ON measurements
            BEGIN SELECT RAISE(ABORT, 'immutable measurement'); END;
          CREATE TRIGGER IF NOT EXISTS claims_no_update BEFORE UPDATE ON claims
            BEGIN SELECT RAISE(ABORT, 'immutable claim'); END;
          CREATE TRIGGER IF NOT EXISTS claims_no_delete BEFORE DELETE ON claims
            BEGIN SELECT RAISE(ABORT, 'immutable claim'); END;
          CREATE TRIGGER IF NOT EXISTS attempts_no_update BEFORE UPDATE ON attempts
            BEGIN SELECT RAISE(ABORT, 'immutable attempt'); END;
          CREATE TRIGGER IF NOT EXISTS attempts_no_delete BEFORE DELETE ON attempts
            BEGIN SELECT RAISE(ABORT, 'immutable attempt'); END;
        """)
        return connection

    def capture(self, raw: bytes, receipt: SourceReceipt) -> str:
        digest = hashlib.sha256(raw).hexdigest()
        if digest != receipt.sha256 or len(raw) != receipt.byte_count:
            raise ValueError("source integrity mismatch")
        blob_dir = self.root / "raw"
        if blob_dir.is_symlink():
            raise ValueError("evidence directory symlinks refused")
        blob_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = blob_dir / digest
        # Never expose a partial write under the immutable content address. A
        # hard link publishes the complete file atomically without replacing an
        # existing blob; concurrent captures can then verify the winner's bytes.
        descriptor, staging_name = tempfile.mkstemp(prefix=".capture-", dir=blob_dir)
        staging = Path(staging_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                if handle.write(raw) != len(raw):
                    raise OSError("incomplete evidence write")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staging, target)
            except FileExistsError:
                self.read_raw(digest)
            if os.name != "nt":
                directory = os.open(blob_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            staging.unlink(missing_ok=True)
        payload = receipt.model_dump_json()
        receipt_id = hashlib.sha256(payload.encode()).hexdigest()
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO receipts VALUES (?,?)", (receipt_id, payload))
        return receipt_id

    def read_raw(self, digest: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid digest")
        path = self.root / "raw" / digest
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("evidence symlinks refused")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("source integrity mismatch")
        return raw

    def add_measurement(self, measurement: Measurement) -> str:
        self.read_raw(measurement.receipt_sha256)
        payload = measurement.model_dump_json()
        identifier = hashlib.sha256(payload.encode()).hexdigest()
        with closing(self._connect()) as db, db:
            receipts = [json.loads(r[0]) for r in db.execute("SELECT payload FROM receipts")]
            if not any(r["sha256"] == measurement.receipt_sha256 for r in receipts):
                raise ValueError("measurement has no source receipt")
            db.execute("INSERT OR IGNORE INTO measurements VALUES (?,?)", (identifier, payload))
        return identifier

    def snapshot(self) -> dict:
        # A read-only consumer must not create a database merely by opening the GUI.
        ledger = self.root / "ledger.sqlite3"
        if ledger.is_symlink():
            raise ValueError("evidence database symlinks refused")
        if not ledger.exists():
            return {"sources": [], "measurements": [], "claims": [], "attempts": []}
        with closing(sqlite3.connect(f"{ledger.as_uri()}?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            sources = [SourceReceipt.model_validate_json(r[0]) for r in db.execute("SELECT payload FROM receipts ORDER BY id")]
            measurements = [Measurement.model_validate_json(r[0]) for r in db.execute("SELECT payload FROM measurements ORDER BY id")]
            claims = [GeneratorClaim.model_validate_json(r[0]) for r in db.execute("SELECT payload FROM claims ORDER BY id")]
            attempts = [json.loads(r[0]) for r in db.execute("SELECT payload FROM attempts ORDER BY id")]
        known = {s.sha256 for s in sources}
        for source in sources:
            if len(self.read_raw(source.sha256)) != source.byte_count:
                raise ValueError("source byte count mismatch")
        if any(m.receipt_sha256 not in known for m in [*measurements, *claims]):
            raise ValueError("orphan measurement")
        return {"sources": [s.model_dump(mode="json") for s in sources],
                "measurements": [m.model_dump(mode="json") for m in measurements],
                "claims": [c.model_dump(mode="json") for c in claims], "attempts": attempts}

    def record_attempt(self, code: str) -> None:
        # Only bounded error/status identifiers; never persist exception text or request URLs.
        if not re.fullmatch(r"EIA_[A-Z0-9_]{1,80}", code):
            raise ValueError("invalid acquisition status")
        payload = json.dumps({"source": "EIA_OFFICIAL_WORKBOOK", "code": code,
                              "recorded_at": datetime.now(timezone.utc).isoformat()})
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO attempts(payload) VALUES (?)", (payload,))

    def add_claims(self, claims: list[GeneratorClaim]) -> None:
        # Verify every input before committing the batch; partial imports cannot appear.
        snapshot = self.snapshot()
        known = {s["sha256"] for s in snapshot["sources"]}
        if any(c.receipt_sha256 not in known for c in claims):
            raise ValueError("claim has no verified source receipt")
        with closing(self._connect()) as db, db:
            for claim in claims:
                payload = claim.model_dump_json()
                identifier = hashlib.sha256(payload.encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO claims VALUES (?,?)", (identifier, payload))
