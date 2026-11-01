"""Durable, fenced, one-request-at-a-time EIA monthly research acquisition."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, model_validator

from aguayluz.electricity.eia import API_ROOT, ROUTES, AcquisitionError, EIAClient
from aguayluz.electricity.evidence import StrictModel
from aguayluz.electricity.store import EvidenceStore


class JobConflict(ValueError):
    """A redacted, retryable operator conflict."""


class MonthlyJobRequest(StrictModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    endpoint: Literal["facility-fuel", "retail-sales"]
    data_column: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    state_facet: Literal["state", "stateid", "plantState"]
    start: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    end: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    page_size: int = Field(default=1000, ge=1, le=5000, strict=True)
    max_pages: int = Field(default=100, ge=1, le=1000, strict=True)

    @model_validator(mode="after")
    def periods(self) -> MonthlyJobRequest:
        if self.start > self.end:
            raise ValueError("start must not follow end")
        return self


class JobCommand(StrictModel):
    expected_version: int = Field(ge=1, strict=True)


class AcquisitionJob(StrictModel):
    spec: MonthlyJobRequest
    version: int = Field(ge=1, strict=True)
    status: Literal["QUEUED", "RUNNING", "FAILED", "CANCELLED", "COMPLETE"]
    phase: Literal["METADATA", "FACET", "PAGES"] = "METADATA"
    receipt_sha256: list[str] = Field(default_factory=list)
    rows: int = Field(default=0, ge=0, le=1_000_000, strict=True)
    total: int | None = Field(default=None, ge=0, le=1_000_000, strict=True)
    error: str | None = Field(default=None, pattern=r"^EIA_[A-Z0-9_]{1,80}$")
    created_at: AwareDatetime
    updated_at: AwareDatetime
    lease_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    lease_until: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def coherent(self) -> AcquisitionJob:
        if (self.status == "RUNNING") != (self.lease_token is not None and self.lease_until > 0):
            raise ValueError("incoherent lease")
        if self.status == "COMPLETE" and (self.total != self.rows or self.phase != "PAGES"):
            raise ValueError("incomplete job cannot be complete")
        return self


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AcquisitionJobs:
    def __init__(self, store: EvidenceStore, *, clock=time.time):
        self.store, self.clock = store, clock
        self.path = store.root / "acquisition.sqlite3"

    def _connect(self, write=False):
        if self.path.is_symlink():
            raise ValueError("job database symlinks refused")
        if not write:
            return sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
        self.store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.path, timeout=10)
        os.chmod(self.path, 0o600)
        db.executescript("""
          CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT, version INTEGER, payload TEXT NOT NULL, digest TEXT NOT NULL,
            PRIMARY KEY(job_id,version));
          CREATE TRIGGER IF NOT EXISTS jobs_no_update BEFORE UPDATE ON jobs
            BEGIN SELECT RAISE(ABORT, 'immutable job event'); END;
          CREATE TRIGGER IF NOT EXISTS jobs_no_delete BEFORE DELETE ON jobs
            BEGIN SELECT RAISE(ABORT, 'immutable job event'); END;
        """)
        return db

    def _read(self, db, identifier):
        job, previous, history = None, "0" * 64, []
        for version, payload, digest in db.execute(
            "SELECT version,payload,digest FROM jobs WHERE job_id=? ORDER BY version", (identifier,)
        ):
            current = AcquisitionJob.model_validate_json(payload)
            value = current.model_dump(mode="json")
            if (current.spec.request_id != identifier or version != len(history) + 1
                    or current.version != version or _hash([previous, value]) != digest
                    or (job is not None and current.spec != job.spec)):
                raise ValueError("job ledger integrity failed")
            previous, job = digest, current
            history.append({"version": version, "status": job.status, "phase": job.phase,
                            "rows": job.rows, "error": job.error, "updated_at": value["updated_at"],
                            "event_sha256": digest})
        return job, history, previous

    def _append(self, db, job, previous):
        value = job.model_dump(mode="json")
        db.execute("INSERT INTO jobs VALUES (?,?,?,?)",
                   (job.spec.request_id, job.version, json.dumps(value), _hash([previous, value])))

    def _public(self, job):
        return {**job.model_dump(mode="json", exclude={"lease_token", "lease_until"}),
                "job_id": job.spec.request_id, "review_state": "AUDIT_ONLY",
                "can_step": job.status in {"QUEUED", "FAILED"} or (job.status == "RUNNING" and self.clock() >= job.lease_until),
                "can_cancel": job.status not in {"COMPLETE", "CANCELLED"},
                "lease_expires_at": datetime.fromtimestamp(job.lease_until, timezone.utc).isoformat() if job.status == "RUNNING" else None,
                "canonical_promotion": "BLOCKED"}

    def create(self, spec: MonthlyJobRequest):
        serialized = spec.model_dump_json()
        if any(value and value in serialized for value in
               (os.environ.get("EIA_API_KEY", ""), os.environ.get("API_SECRET_KEY", ""))):
            raise ValueError("credential values refused in job specification")
        with closing(self._connect(True)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            job, _, previous = self._read(db, spec.request_id)
            if job:
                if job.spec != spec:
                    raise JobConflict("EIA_JOB_REQUEST_CONFLICT")
                return self._public(job)
            now = datetime.fromtimestamp(self.clock(), timezone.utc)
            job = AcquisitionJob(spec=spec, version=1, status="QUEUED", created_at=now, updated_at=now)
            self._append(db, job, previous)
            return self._public(job)

    def _params(self, job):
        spec = job.spec
        return {"frequency": "monthly", "data[0]": spec.data_column,
                f"facets[{spec.state_facet}][]": "PR", "start": spec.start, "end": spec.end,
                "sort[0][column]": "period", "sort[0][direction]": "asc",
                "offset": job.rows, "length": spec.page_size}

    def _validate(self, job, response):
        spec = job.spec
        if job.phase == "METADATA":
            if (not isinstance(response.get("facets"), list) or not isinstance(response.get("frequency"), list)
                    or not isinstance(response.get("data"), dict)
                    or not all(isinstance(x, dict) for x in response["facets"] + response["frequency"])
                    or spec.state_facet not in {f.get("id") for f in response["facets"]}
                    or "monthly" not in {f.get("id") for f in response["frequency"]}
                    or spec.data_column not in response["data"]):
                raise AcquisitionError("EIA_ENDPOINT_SCHEMA_UNSUPPORTED")
            return {"phase": "FACET"}
        if job.phase == "FACET":
            facets = response.get("facets")
            if (not isinstance(facets, list) or not all(isinstance(f, dict) for f in facets)
                    or str(response.get("totalFacets")) != str(len(facets))):
                raise AcquisitionError("EIA_FACET_COVERAGE_UNVERIFIED")
            if not any(f.get("id") == "PR" for f in facets):
                raise AcquisitionError("EIA_PR_NOT_SUPPORTED")
            return {"phase": "PAGES"}
        page, count = response.get("data"), response.get("total")
        if isinstance(count, bool) or not str(count).isdigit() or int(count) > 1_000_000:
            raise AcquisitionError("EIA_TOTAL_INVALID")
        total = int(count)
        if job.total is not None and total != job.total:
            raise AcquisitionError("EIA_PAGINATION_DRIFT")
        if not isinstance(page, list) or len(page) > spec.page_size or (not page and job.rows != total):
            raise AcquisitionError("EIA_PAGE_INCOMPLETE")
        for row in page:
            if (not isinstance(row, dict) or row.get(spec.state_facet) != "PR"
                    or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", str(row.get("period", "")))
                    or not spec.start <= row["period"] <= spec.end or spec.data_column not in row):
                raise AcquisitionError("EIA_ROW_SCOPE_INVALID")
        rows = job.rows + len(page)
        if rows > total:
            raise AcquisitionError("EIA_TOTAL_MISMATCH")
        return {"rows": rows, "total": total, "status": "COMPLETE" if rows == total else "QUEUED"}

    def _verify(self, job):
        try:
            return self._replay(job)
        except (AcquisitionError, KeyError, TypeError) as exc:
            raise ValueError("checkpoint integrity failed") from exc

    def _replay(self, job):
        # Reconstruct each checkpoint from immutable, source-bound bytes. A
        # saved offset alone never authorizes skipping source records.
        sources = self.store.snapshot()["sources"]
        replay = job.model_copy(update={"phase": "METADATA", "rows": 0, "total": None, "status": "QUEUED"})
        fingerprints, row_fingerprints = set(), set()
        for index, digest in enumerate(job.receipt_sha256):
            url, params = self._request_spec(replay)
            if not any(s["sha256"] == digest and s["source_url"] == url
                       and s["request_parameters"] == [list(p) for p in sorted((k, str(v)) for k, v in params.items())]
                       for s in sources):
                raise ValueError("checkpoint receipt binding failed")
            response = json.loads(self.store.read_raw(digest))["response"]
            changes = self._validate(replay, response)
            if index >= 2:
                fingerprint = _hash(response["data"])
                if fingerprint in fingerprints or (replay.status == "COMPLETE"):
                    raise ValueError("checkpoint pagination integrity failed")
                fingerprints.add(fingerprint)
                for row in response["data"]:
                    fingerprint = _hash(row)
                    if fingerprint in row_fingerprints:
                        raise ValueError("checkpoint duplicate row integrity failed")
                    row_fingerprints.add(fingerprint)
            replay = replay.model_copy(update=changes)
        if (replay.phase, replay.rows, replay.total) != (job.phase, job.rows, job.total):
            raise ValueError("checkpoint state integrity failed")
        return fingerprints, row_fingerprints

    def _request_spec(self, job):
        url = API_ROOT + ROUTES[job.spec.endpoint]
        if job.phase == "METADATA":
            return url, {}
        if job.phase == "FACET":
            return url + f"facet/{job.spec.state_facet}/", {"length": 5000}
        return url + "data/", self._params(job)

    def get(self, identifier):
        if not self.path.exists() and not self.path.is_symlink():
            raise KeyError(identifier)
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            job, history, _ = self._read(db, identifier)
        if job is None:
            raise KeyError(identifier)
        self._verify(job)
        return {**self._public(job), "history": history}

    def list(self, *, offset=0, limit=50):
        if not self.path.exists() and not self.path.is_symlink():
            return {"jobs": [], "total": 0, "next_offset": None}
        with closing(self._connect()) as db:
            total = db.execute("SELECT COUNT(DISTINCT job_id) FROM jobs").fetchone()[0]
            identifiers = [r[0] for r in db.execute("SELECT job_id FROM jobs GROUP BY job_id ORDER BY MIN(rowid) LIMIT ? OFFSET ?", (limit, offset))]
        return {"jobs": [self.get(identifier) for identifier in identifiers], "total": total,
                "next_offset": offset + len(identifiers) if offset + len(identifiers) < total else None}

    def cancel(self, identifier, version):
        self._change(identifier, version, cancel=True)
        return self.get(identifier)

    def _change(self, identifier, version, *, cancel=False):
        # Acquire a fenced five-minute lease without holding a database lock
        # across network I/O. Cancellation revokes it immediately.
        with closing(self._connect(True)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            job, _, previous = self._read(db, identifier)
            if job is None:
                raise KeyError(identifier)
            self._verify(job)
            if job.version != version or job.status in {"COMPLETE", "CANCELLED"}:
                raise JobConflict("EIA_JOB_VERSION_OR_STATE_CONFLICT")
            now = self.clock()
            if not cancel and job.status == "RUNNING" and job.lease_until > now:
                raise JobConflict("EIA_JOB_ALREADY_RUNNING")
            changes = {"version": job.version + 1, "updated_at": datetime.fromtimestamp(now, timezone.utc),
                       "status": "CANCELLED" if cancel else "RUNNING", "error": None,
                       "lease_token": None if cancel else uuid4().hex, "lease_until": 0 if cancel else now + 300}
            new = AcquisitionJob.model_validate(job.model_dump() | changes)
            self._append(db, new, previous)
            return new

    def step(self, identifier, version, *, client: EIAClient | None = None):
        job = self._change(identifier, version)
        api = client or EIAClient(self.store)
        try:
            fingerprints, row_fingerprints = self._verify(job)
            if job.phase == "PAGES" and len(job.receipt_sha256) - 2 >= job.spec.max_pages:
                raise AcquisitionError("EIA_PAGE_LIMIT")
            url, params = self._request_spec(job)
            response, digest = api._json(url, params)
            changes = self._validate(job, response)
            if job.phase == "PAGES" and _hash(response["data"]) in fingerprints:
                raise AcquisitionError("EIA_PAGE_REPEATED")
            if job.phase == "PAGES":
                current_rows = [_hash(row) for row in response["data"]]
                if len(set(current_rows)) != len(current_rows) or row_fingerprints.intersection(current_rows):
                    raise AcquisitionError("EIA_ROW_REPEATED")
            changes = {"status": "QUEUED", **changes, "receipt_sha256": [*job.receipt_sha256, digest]}
        except AcquisitionError as error:
            code = str(error)
            # Do not trust arbitrary exception text as an audit status.
            changes = {"status": "FAILED", "error": code if re.fullmatch(r"EIA_[A-Z0-9_]{1,80}", code) else "EIA_ACQUISITION_FAILED"}
        finally:
            if client is None:
                api.close()
        with closing(self._connect(True)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current, _, previous = self._read(db, identifier)
            if current.lease_token != job.lease_token or current.version != job.version or self.clock() > job.lease_until:
                raise JobConflict("EIA_JOB_LEASE_FENCED")
            result = AcquisitionJob.model_validate(job.model_dump() | changes | {
                "version": job.version + 1, "updated_at": datetime.fromtimestamp(self.clock(), timezone.utc),
                "lease_token": None, "lease_until": 0})
            self._append(db, result, previous)
        return self.get(identifier)
