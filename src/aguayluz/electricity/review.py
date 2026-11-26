"""Reversible candidate recommendations; scientific evidence is never mutated."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from aguayluz.electricity.evidence import GeneratorClaim, StrictModel

EMPTY_REVISION = "0" * 64
ReviewAction = Literal["RECOMMEND_RETAIN", "RECOMMEND_EXCLUDE", "DEFER", "REVERSE"]
ReviewReason = Literal[
    "ORIGINAL_REQUIRED", "CAPACITY_CONFLICT", "STATUS_CONFLICT", "TEMPORAL_CONFLICT",
    "SOURCE_DISAGREEMENT", "REVIEW_CORRECTION",
]


class ReviewError(ValueError):
    """A bounded rejection that is safe for the API and audit interface."""


class ReviewRequest(StrictModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_review_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: ReviewAction
    reason_code: ReviewReason
    reverses: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def reversal_target(self) -> ReviewRequest:
        if (self.action == "REVERSE") != (self.reverses is not None):
            raise ValueError("only reversal requests must specify a target")
        return self


class ReviewEvent(ReviewRequest):
    schema_version: Literal["aguayluz.electricity-review-event/v1"] = "aguayluz.electricity-review-event/v1"
    sequence: int = Field(ge=1, strict=True)
    actor: Literal["SHARED_OPERATOR_KEY"] = "SHARED_OPERATOR_KEY"
    recorded_at: AwareDatetime
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_identity: str
    review_state: Literal["AUDIT_ONLY"] = "AUDIT_ONLY"
    canonical_promotion: Literal["BLOCKED"] = "BLOCKED"


class StoredReviewEvent(ReviewEvent):
    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewedClaim(StrictModel):
    claim_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_identity: str
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_recommendation: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    active_action: Literal["RECOMMEND_RETAIN", "RECOMMEND_EXCLUDE", "DEFER"] | None


class ReviewProjection(StrictModel):
    schema_version: Literal["aguayluz.electricity-reviews/v1"] = "aguayluz.electricity-reviews/v1"
    producer: Literal["aguayluz-pr"] = "aguayluz-pr"
    jurisdiction: Literal["PR"] = "PR"
    source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    certification: Literal["NOT_CERTIFIED"] = "NOT_CERTIFIED"
    canonical_promotion: Literal["BLOCKED"] = "BLOCKED"
    actor_scope: Literal["SHARED_OPERATOR_KEY_NOT_INDIVIDUAL_IDENTITY"] = "SHARED_OPERATOR_KEY_NOT_INDIVIDUAL_IDENTITY"
    claims: list[ReviewedClaim]
    events: list[StoredReviewEvent]


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def claim_identifier(claim: dict) -> str:
    """Hash the complete validated claim; a source digest alone is not a row ID."""
    return _digest(GeneratorClaim.model_validate(claim).model_dump(mode="json"))


class ReviewLedger:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "reviews.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("review database symlinks refused")
        db = sqlite3.connect(self.path, timeout=10)
        os.chmod(self.path, 0o600)
        db.executescript("""
          CREATE TABLE IF NOT EXISTS review_events (
            sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL,
            request_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS review_no_update BEFORE UPDATE ON review_events
            BEGIN SELECT RAISE(ABORT, 'immutable review event'); END;
          CREATE TRIGGER IF NOT EXISTS review_no_delete BEFORE DELETE ON review_events
            BEGIN SELECT RAISE(ABORT, 'immutable review event'); END;
        """)
        return db

    def _read(self, db: sqlite3.Connection, projection: dict) -> tuple[list[dict], dict]:
        known = {claim_identifier(c): c for c in projection["generator_claims"]}
        events, stacks, requests = [], {}, set()
        previous = EMPTY_REVISION
        for sequence, identifier, request_id, payload in db.execute(
            "SELECT sequence,event_id,request_id,payload FROM review_events ORDER BY sequence"
        ):
            event = ReviewEvent.model_validate_json(payload).model_dump(mode="json")
            claim = known.get(event["claim_id"])
            if (sequence != len(events) + 1 or event["sequence"] != sequence
                    or _digest(event) != identifier or event["request_id"] != request_id
                    or request_id in requests or event["expected_review_revision"] != previous
                    or claim is None or claim["receipt_sha256"] != event["receipt_sha256"]
                    or GeneratorClaim.model_validate(claim).source_identity != event["source_identity"]):
                raise ValueError("review integrity failed")
            stack = stacks.setdefault(event["claim_id"], [])
            if event["action"] == "REVERSE":
                if not stack or stack[-1]["event_id"] != event["reverses"]:
                    raise ValueError("review reversal integrity failed")
                stack.pop()
            else:
                stack.append({**event, "event_id": identifier})
            events.append({**event, "event_id": identifier})
            requests.add(request_id)
            previous = identifier
        return events, stacks

    def snapshot(self, projection: dict) -> dict:
        if self.path.is_symlink():
            raise ValueError("review database symlinks refused")
        if self.path.exists():
            with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
                db.execute("BEGIN")
                events, stacks = self._read(db, projection)
        else:
            events, stacks = [], {}
        claims = []
        for claim in projection["generator_claims"]:
            identifier = claim_identifier(claim)
            stack = stacks.get(identifier, [])
            claims.append({"claim_id": identifier,
                           "source_identity": GeneratorClaim.model_validate(claim).source_identity,
                           "receipt_sha256": claim["receipt_sha256"],
                           "active_recommendation": stack[-1]["event_id"] if stack else None,
                           "active_action": stack[-1]["action"] if stack else None})
        return ReviewProjection(source_revision=projection["revision"],
                                revision=events[-1]["event_id"] if events else EMPTY_REVISION,
                                claims=sorted(claims, key=lambda c: c["claim_id"]),
                                events=events).model_dump(mode="json")

    def append(self, projection: dict, request: ReviewRequest) -> dict:
        # A separate ledger leaves every original scientific projection byte and
        # contract intact. Expected revisions serialize concurrent operator edits.
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            events, stacks = self._read(db, projection)
            body = request.model_dump(mode="json")
            for event in events:
                if event["request_id"] == request.request_id:
                    if any(event[key] != value for key, value in body.items()):
                        raise ReviewError("REVIEW_REQUEST_ID_CONFLICT")
                    return {"event": event, "replayed": True}
            if request.source_revision != projection["revision"]:
                raise ReviewError("REVIEW_SOURCE_REVISION_STALE")
            previous = events[-1]["event_id"] if events else EMPTY_REVISION
            if request.expected_review_revision != previous:
                raise ReviewError("REVIEW_REVISION_STALE")
            claim = next((c for c in projection["generator_claims"]
                          if claim_identifier(c) == request.claim_id), None)
            if claim is None:
                raise ReviewError("REVIEW_CLAIM_UNKNOWN")
            if request.action == "REVERSE":
                stack = stacks.get(request.claim_id, [])
                if not stack or stack[-1]["event_id"] != request.reverses:
                    raise ReviewError("REVIEW_REVERSAL_NOT_ACTIVE")
            event = ReviewEvent(**body, sequence=len(events) + 1,
                                recorded_at=datetime.now(timezone.utc),
                                receipt_sha256=claim["receipt_sha256"],
                                source_identity=GeneratorClaim.model_validate(claim).source_identity)
            payload = event.model_dump(mode="json")
            identifier = _digest(payload)
            db.execute("INSERT INTO review_events VALUES (?,?,?,?)",
                       (event.sequence, identifier, request.request_id, json.dumps(payload)))
            return {"event": {**payload, "event_id": identifier}, "replayed": False}
