"""Bounded EIA v2 acquisition. Metadata, facets and bytes precede interpretation."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx

from aguayluz.electricity.evidence import SourceReceipt
from aguayluz.electricity.store import EvidenceStore

API_ROOT = "https://api.eia.gov/v2/"
ROUTES = {"facility-fuel": "electricity/facility-fuel/", "retail-sales": "electricity/retail-sales/"}


class AcquisitionError(RuntimeError):
    """Redacted failure suitable for receipts and user interfaces."""


def validate_workbook_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme == "https" and parsed.hostname == "www.eia.gov" and parsed.port in (None, 443) and not (parsed.username or parsed.password or parsed.query or parsed.fragment) and re.fullmatch(r"/electricity/data/(eia860m|eia923)/(?:archive/)?(xls|xlsx)/[A-Za-z0-9_.-]+\.(xlsx|zip)", parsed.path)
    except ValueError:
        valid = False
    if not valid:
        raise AcquisitionError("EIA_OFFICIAL_URL_REQUIRED")


class _RedactEIA(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = re.sub(r"(?i)(api_key(?:=|%3D|\x22\s*:\s*\x22))[^&\s\x22\x27]+", r"\1[REDACTED]", message)
        record.args = ()
        return True


# httpx logs complete request URLs at INFO; never let its query credential escape.
for _logger in ("httpx", "httpcore", "httpcore.http11", "httpcore.http2", "httpcore.connection"):
    logging.getLogger(_logger).addFilter(_RedactEIA())


class EIAClient:
    def __init__(self, store: EvidenceStore, *, client: httpx.Client | None = None, sleep=time.sleep):
        self.store = store
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self._owns_client = client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _request(self, url: str, params: dict, *, authenticated: bool) -> bytes:
        key = os.environ.get("EIA_API_KEY", "") if authenticated else ""
        if authenticated and not key:
            raise AcquisitionError("EIA_CREDENTIAL_MISSING")
        parameters = {**params, **({"api_key": key} if key else {})}
        for attempt in range(4):
            retry = False
            try:
                with self.client.stream("GET", url, params=parameters) as response:
                    status = response.status_code
                    retry = status in {429, 500, 502, 503, 504}
                    if 200 <= status < 300:
                        chunks = bytearray()
                        for chunk in response.iter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > 50_000_000:
                                raise AcquisitionError("EIA_RESPONSE_TOO_LARGE")
                        raw = bytes(chunks)
                        if key and any(token in raw for token in (key.encode(), quote(key, safe="").encode())):
                            raise AcquisitionError("EIA_RESPONSE_CONTAINS_CREDENTIAL")
                        return raw
                    if not retry:
                        raise AcquisitionError(f"EIA_HTTP_{status}")
                    # Respect Retry-After seconds, bounded to keep runs cancellable.
                    delay = response.headers.get("retry-after", "")
                    wait = min(30.0, float(delay)) if delay.isdigit() else min(8, 2 ** attempt)
            except httpx.HTTPError:
                retry, wait = True, min(8, 2 ** attempt)
            if retry and attempt < 3:
                self._sleep(wait)
        raise AcquisitionError("EIA_RETRY_EXHAUSTED")

    def _capture(self, url: str, raw: bytes, signature: str, params: dict | None = None) -> str:
        receipt = SourceReceipt(sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw),
                                source_url=url, authority="U.S. Energy Information Administration",
                                retrieved_at=datetime.now(timezone.utc), schema_signature=signature,
                                license="U.S. Government work; third-party exceptions unresolved",
                                request_parameters=tuple(sorted((k, str(v)) for k, v in (params or {}).items())))
        self.store.capture(raw, receipt)
        return receipt.sha256

    def _json(self, url: str, params: dict) -> tuple[dict, str]:
        raw = self._request(url, params, authenticated=True)
        digest = self._capture(url, raw, "EIA-v2-response/AUDIT_ONLY", params)
        try:
            envelope = json.loads(raw)
            response = envelope["response"]
            if not isinstance(response, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise AcquisitionError("EIA_SCHEMA_INVALID") from None
        return response, digest

    def discover(self, endpoint: str) -> dict:
        if endpoint not in ROUTES:
            raise AcquisitionError("EIA_ENDPOINT_UNSUPPORTED")
        response, digest = self._json(API_ROOT + ROUTES[endpoint], {})
        return {"metadata": response, "receipt_sha256": digest}

    def monthly_pr(self, endpoint: str, *, data_column: str, state_facet: str,
                   start: str, end: str, page_size: int = 5000, max_pages: int = 1000) -> dict:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", start) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", end) or start > end:
            raise AcquisitionError("EIA_PERIOD_INVALID")
        if not 1 <= page_size <= 5000 or not 1 <= max_pages <= 1000:
            raise AcquisitionError("EIA_PAGE_BOUND_INVALID")
        discovery = self.discover(endpoint)
        metadata = discovery["metadata"]
        if not isinstance(metadata.get("facets"), list) or not all(isinstance(f, dict) for f in metadata["facets"]) or not isinstance(metadata.get("frequency"), list) or not all(isinstance(f, dict) for f in metadata["frequency"]) or not isinstance(metadata.get("data"), dict):
            raise AcquisitionError("EIA_ENDPOINT_SCHEMA_UNSUPPORTED")
        facets = {f.get("id") for f in metadata.get("facets", [])}
        frequencies = {f.get("id") for f in metadata.get("frequency", [])}
        # Do not assume the continental API route includes PR or guess a geographic field.
        if state_facet not in {"state", "stateid", "plantState"} or state_facet not in facets or data_column not in metadata.get("data", {}) or "monthly" not in frequencies:
            raise AcquisitionError("EIA_ENDPOINT_SCHEMA_UNSUPPORTED")
        url = API_ROOT + ROUTES[endpoint]
        facet, facet_digest = self._json(url + f"facet/{state_facet}/", {"length": 5000})
        if not isinstance(facet.get("facets"), list) or not all(isinstance(f, dict) for f in facet["facets"]):
            raise AcquisitionError("EIA_FACET_COVERAGE_UNVERIFIED")
        if str(facet.get("totalFacets")) != str(len(facet.get("facets", []))):
            raise AcquisitionError("EIA_FACET_COVERAGE_UNVERIFIED")
        if not any(f.get("id") == "PR" for f in facet.get("facets", [])):
            raise AcquisitionError("EIA_PR_NOT_SUPPORTED")
        rows, digests, total = [], [discovery["receipt_sha256"], facet_digest], None
        seen_pages = set()
        for _ in range(max_pages):
            params = {"frequency": "monthly", "data[0]": data_column,
                      f"facets[{state_facet}][]": "PR", "start": start, "end": end,
                      "sort[0][column]": "period", "sort[0][direction]": "asc",
                      "offset": len(rows), "length": page_size}
            response, digest = self._json(url + "data/", params)
            page = response.get("data")
            try:
                count = int(response["total"])
            except (KeyError, ValueError, TypeError):
                raise AcquisitionError("EIA_TOTAL_INVALID") from None
            if count < 0 or (total is not None and count != total) or not isinstance(page, list):
                raise AcquisitionError("EIA_PAGINATION_DRIFT")
            total = count
            if len(page) > page_size or (not page and len(rows) != total):
                raise AcquisitionError("EIA_PAGE_INCOMPLETE")
            if page and digest in seen_pages:
                raise AcquisitionError("EIA_PAGE_REPEATED")
            seen_pages.add(digest)
            for row in page:
                if not isinstance(row, dict) or row.get(state_facet) != "PR" or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(row.get("period", ""))) or not start <= str(row.get("period", "")) <= end or data_column not in row:
                    raise AcquisitionError("EIA_ROW_SCOPE_INVALID")
            rows.extend(page)
            digests.append(digest)
            if len(rows) == total:
                return {"rows": rows, "receipt_sha256": digests, "review_state": "AUDIT_ONLY",
                        "source": total, "retained": len(rows), "excluded": 0}
            if len(rows) > total:
                raise AcquisitionError("EIA_TOTAL_MISMATCH")
        raise AcquisitionError("EIA_PAGE_LIMIT")

    def acquire_workbook(self, url: str) -> str:
        validate_workbook_url(url)
        raw = self._request(url, {}, authenticated=False)
        if not raw.startswith(b"PK\x03\x04"):
            raise AcquisitionError("EIA_WORKBOOK_FORMAT_INVALID")
        return self._capture(url, raw, "EIA-original-workbook/AUDIT_ONLY")
