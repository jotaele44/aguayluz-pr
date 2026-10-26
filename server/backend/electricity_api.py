"""Native electricity evidence workspace; fail-closed writes, read-only projection."""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import ParseError

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from aguayluz.electricity.eia import AcquisitionError, EIAClient, validate_workbook_url
from aguayluz.electricity.evidence import SourceReceipt
from aguayluz.electricity.projection import electricity_projection
from aguayluz.electricity.store import EvidenceStore
from aguayluz.electricity.workbook import parse_860m
from server.backend import main as legacy

router = APIRouter(tags=["electricity"])
_acquisition_lock = threading.Lock()


def _store() -> EvidenceStore:
    return EvidenceStore(Path(legacy.DATA) / "electricity")


def _require_operator(request: Request) -> None:
    key = os.environ.get("API_SECRET_KEY", "")
    if not key:
        raise HTTPException(503, detail="ELECTRICITY_WRITES_DISABLED")
    if not secrets.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {key}".encode()):
        raise HTTPException(401, detail="OPERATOR_AUTH_REQUIRED")


class AcquisitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=1000)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sheet_path: str = Field(pattern=r"^xl/worksheets/sheet[1-9][0-9]*\.xml$")
    effective_at: AwareDatetime


@router.get("/electricity/v1/projection")
def projection() -> dict:
    try:
        return electricity_projection(_store())
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        raise HTTPException(503, detail="ELECTRICITY_EVIDENCE_INTEGRITY_FAILED") from exc


@router.post("/electricity/v1/acquire", dependencies=[Depends(_require_operator)])
def acquire(body: AcquisitionRequest) -> dict:
    if not _acquisition_lock.acquire(blocking=False):
        raise HTTPException(409, detail="ACQUISITION_ALREADY_RUNNING")
    client = EIAClient(_store())
    try:
        digest = client.acquire_workbook(body.url)
        _store().record_attempt("EIA_ACQUIRED_AUDIT_ONLY")
        return {"sha256": digest, "review_state": "AUDIT_ONLY"}
    except AcquisitionError as exc:
        _store().record_attempt(str(exc))
        raise HTTPException(502, detail=str(exc)) from None
    finally:
        client.close()
        _acquisition_lock.release()


@router.post("/electricity/v1/import/860m", dependencies=[Depends(_require_operator)])
def import_860m(body: ImportRequest) -> dict:
    try:
        store = _store()
        raw = store.read_raw(body.sha256)
        result = parse_860m(raw, sheet_path=body.sheet_path, receipt_sha256=body.sha256,
                           effective_at=body.effective_at)
        store.add_claims(result["claims"])
        return {"arithmetic": result["arithmetic"], "unresolved": result["unresolved"],
                "canonical_promotion": "BLOCKED", "effective_at": datetime.isoformat(body.effective_at)}
    except (OSError, ValueError, KeyError, IndexError, ParseError, zipfile.BadZipFile, sqlite3.DatabaseError) as exc:
        raise HTTPException(422, detail="EIA_860M_IMPORT_REQUIRES_SOURCE_SCHEMA_REVIEW") from exc


@router.post("/electricity/v1/import/workbook", dependencies=[Depends(_require_operator)])
async def import_workbook(request: Request, source_url: str = Header(alias="X-EIA-Source-URL", max_length=1000)) -> dict:
    try:
        validate_workbook_url(source_url)
    except AcquisitionError:
        raise HTTPException(422, detail="EIA_OFFICIAL_URL_REQUIRED") from None
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 50_000_000:
            raise HTTPException(413, detail="EIA_RESPONSE_TOO_LARGE")
    raw = bytes(chunks)
    if not raw.startswith(b"PK\x03\x04"):
        raise HTTPException(422, detail="EIA_WORKBOOK_FORMAT_INVALID")
    key = os.environ.get("EIA_API_KEY", "")
    if key and key.encode() in raw:
        raise HTTPException(422, detail="EIA_RESPONSE_CONTAINS_CREDENTIAL")
    receipt = SourceReceipt(sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw),
                            source_url=source_url, authority="EIA origin asserted by operator; not independently acquired",
                            retrieved_at=datetime.now(timezone.utc), schema_signature="OFFLINE_ORIGIN_UNVERIFIED/AUDIT_ONLY")
    _store().capture(raw, receipt)
    _store().record_attempt("EIA_OFFLINE_CAPTURED_AUDIT_ONLY")
    return {"sha256": receipt.sha256, "review_state": "AUDIT_ONLY", "origin_verification": "UNVERIFIED"}
