#!/usr/bin/env python3
"""Operator-invoked, read-only Río Camuy USGS Water Data snapshot adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

ROOT = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
ALLOWED_COLLECTIONS = {"latest-continuous", "continuous", "monitoring-locations", "time-series-metadata"}
SITE_POLICY = {
    "50014800": {"monitoring_location": "USGS-50014800", "source_id": "SRC_KARST_USGS_50014800", "current": {"00060", "00065", "72365"}, "historical": {"00045"}, "evidence_tier": "T1", "privacy_class": "P0_PUBLIC"},
    "50014600": {"monitoring_location": "USGS-50014600", "source_id": "SRC_KARST_USGS_50014600", "current": set(), "historical": {"00060"}, "evidence_tier": "T1", "privacy_class": "P0_PUBLIC"},
}
PARAMETERS = {
    "00060": ("discharge", "ft3/s", None),
    "00065": ("gage_height", "ft", "time_series_metadata_required"),
    "72365": ("stream_level_elevation", "ft", "PRVD02"),
    "00045": ("precipitation", "in", None),
}
STALE_AFTER_MINUTES = 90


class SnapshotError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RequestReceipt:
    url: str
    status_code: int
    received_at: str
    response_sha256: str
    request_receipt_sha256: str


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str) -> datetime | None:
    text = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _receipt(response: httpx.Response, received_at: str) -> RequestReceipt:
    body_hash = sha256_hex(response.content)
    parsed = urlparse(str(response.request.url))
    sanitized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    material = {
        "method": response.request.method,
        "url": sanitized,
        "query": sorted((k, v) for k, v in response.request.url.params.multi_items() if k != "api_key"),
        "status_code": response.status_code,
        "response_sha256": body_hash,
        "received_at": received_at,
    }
    return RequestReceipt(sanitized, response.status_code, received_at, body_hash, sha256_hex(canonical_json(material)))


def _features(document: dict[str, Any]) -> list[dict[str, Any]]:
    features = document.get("features")
    if not isinstance(features, list):
        raise SnapshotError("schema_drift", "USGS response missing features array")
    return [item for item in features if isinstance(item, dict)]


def _next_link(document: dict[str, Any]) -> str | None:
    return next((str(link["href"]) for link in document.get("links") or [] if isinstance(link, dict) and link.get("rel") == "next" and link.get("href")), None)


def fetch_collection(client: httpx.Client, collection: str, *, site: str, parameter_code: str | None = None, datetime_range: str | None = None, page_limit: int = 500) -> tuple[list[tuple[dict[str, Any], RequestReceipt]], list[RequestReceipt]]:
    if collection not in ALLOWED_COLLECTIONS:
        raise SnapshotError("collection_not_allowed", collection)
    if site not in SITE_POLICY:
        raise SnapshotError("out_of_scope_site", site)
    params: dict[str, Any] = {"monitoring_location_id": SITE_POLICY[site]["monitoring_location"], "limit": page_limit, "f": "json"}
    if parameter_code:
        params["parameter_code"] = parameter_code
    if datetime_range and collection == "continuous":
        params["datetime"] = datetime_range
    next_url: str | None = f"{ROOT}/{collection}/items"
    next_params: dict[str, Any] | None = params
    items: list[tuple[dict[str, Any], RequestReceipt]] = []
    receipts: list[RequestReceipt] = []
    seen: set[str] = set()
    while next_url:
        if next_url in seen:
            raise SnapshotError("pagination_loop", next_url)
        seen.add(next_url)
        response = client.get(next_url, params=next_params)
        receipt = _receipt(response, _now())
        receipts.append(receipt)
        if response.status_code == 429:
            raise SnapshotError("rate_limited", "USGS returned HTTP 429")
        if response.status_code >= 500:
            raise SnapshotError("upstream_5xx", f"USGS returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise SnapshotError("upstream_http_error", f"USGS returned HTTP {response.status_code}")
        try:
            document = response.json()
        except ValueError as exc:
            raise SnapshotError("schema_drift", "USGS response is not JSON") from exc
        if not isinstance(document, dict):
            raise SnapshotError("schema_drift", "USGS response is not an object")
        items.extend((feature, receipt) for feature in _features(document))
        next_url, next_params = _next_link(document), None
    return items, receipts


def _quality_flag(approval: Any, qualifier: Any) -> str:
    approvals = [str(v).lower() for v in approval] if isinstance(approval, list) else [str(approval or "").lower()]
    qualifiers = [str(v).lower() for v in qualifier] if isinstance(qualifier, list) else [str(qualifier or "").lower()]
    if any("reject" in value for value in approvals + qualifiers):
        return "rejected"
    return "validated" if "approved" in approvals else "provisional"


def normalize_observation(feature: dict[str, Any], receipt: RequestReceipt, *, collection: str, now: datetime | None = None) -> dict[str, Any] | None:
    props = feature.get("properties")
    if not isinstance(props, dict):
        raise SnapshotError("schema_drift", "feature missing properties object")
    site = str(props.get("monitoring_location_id") or props.get("site_no") or "").strip().removeprefix("USGS-")
    if site not in SITE_POLICY:
        raise SnapshotError("out_of_scope_site", site or "missing")
    pcode = str(props.get("parameter_code") or "").strip()
    if pcode not in PARAMETERS:
        raise SnapshotError("unknown_parameter", pcode or "missing")
    current_allowed = pcode in SITE_POLICY[site]["current"]
    historical_allowed = pcode in SITE_POLICY[site]["historical"]
    if not current_allowed and not historical_allowed:
        raise SnapshotError("parameter_not_admitted_for_site", f"{site}:{pcode}")
    value = props.get("value")
    observed_at = str(props.get("time") or props.get("datetime") or props.get("observed_at") or "").strip()
    unit = str(props.get("unit_of_measure") or props.get("unit") or "").strip()
    if value is None or not observed_at or not unit:
        return None
    observed_property, expected_unit, datum = PARAMETERS[pcode]
    operational = collection == "latest-continuous" and current_allowed and site == "50014800" and pcode != "00045"
    observed_dt = _parse_dt(observed_at)
    reference = now or datetime.now(timezone.utc)
    age_minutes = None if observed_dt is None else max(0.0, (reference - observed_dt).total_seconds() / 60.0)
    freshness = "unknown" if age_minutes is None else ("stale" if age_minutes > STALE_AFTER_MINUTES else "current")
    approval = props.get("approval_status") or props.get("approvals_status") or []
    qualifier = props.get("qualifier") or props.get("qualifiers") or []
    return {
        "source_id": SITE_POLICY[site]["source_id"], "monitoring_location": SITE_POLICY[site]["monitoring_location"],
        "parameter_code": pcode, "observed_property": observed_property, "value": value, "unit": unit,
        "expected_unit": expected_unit, "datum": datum, "observed_at": observed_at, "qualifier": qualifier,
        "approval_status": approval, "received_at": receipt.received_at, "request_receipt_sha256": receipt.request_receipt_sha256,
        "evidence_tier": SITE_POLICY[site]["evidence_tier"], "quality_flag": _quality_flag(approval, qualifier),
        "privacy_class": SITE_POLICY[site]["privacy_class"], "operational_admission": operational,
        "freshness": freshness, "age_minutes": age_minutes,
    }


def materialize_snapshot(client: httpx.Client, *, history_datetime: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    plans: Iterable[tuple[str, str, str | None]] = (
        ("latest-continuous", "50014800", "00060"), ("latest-continuous", "50014800", "00065"),
        ("latest-continuous", "50014800", "72365"), ("continuous", "50014800", "00045"),
        ("continuous", "50014600", "00060"), ("monitoring-locations", "50014800", None),
        ("monitoring-locations", "50014600", None), ("time-series-metadata", "50014800", None),
        ("time-series-metadata", "50014600", None),
    )
    reference = now or datetime.now(timezone.utc)
    observations: list[dict[str, Any]] = []
    receipts: list[RequestReceipt] = []
    diagnostics: list[dict[str, str]] = []
    for collection, site, parameter in plans:
        try:
            rows, page_receipts = fetch_collection(client, collection, site=site, parameter_code=parameter, datetime_range=history_datetime)
            receipts.extend(page_receipts)
            if collection in {"latest-continuous", "continuous"}:
                for feature, receipt in rows:
                    row = normalize_observation(feature, receipt, collection=collection, now=reference)
                    if row is None:
                        diagnostics.append({"collection": collection, "site": site, "code": "partial_record"})
                    else:
                        observations.append(row)
                        if row["operational_admission"] and row["freshness"] != "current":
                            diagnostics.append({"collection": collection, "site": site, "code": "stale_current_observation"})
        except SnapshotError as exc:
            diagnostics.append({"collection": collection, "site": site, "code": exc.code})
    current = [row for row in observations if row["operational_admission"] and row["freshness"] == "current"]
    return {
        "schema_version": "aguayluz.rio-camuy-usgs-snapshot/v0.2", "generated_at": reference.isoformat().replace("+00:00", "Z"),
        "operational_state": "observed" if current and not diagnostics else "unknown", "safe_open_reopen_inference": False,
        "public_notifications_enabled": False, "automatic_public_reopening_enabled": False, "local_sensor_commissioned_count": 0,
        "stage_rain_thresholds_authority": "pilot_provisional",
        "observations": sorted(observations, key=lambda row: (row["monitoring_location"], row["parameter_code"], row["observed_at"])),
        "request_receipts": [asdict(receipt) for receipt in receipts], "diagnostics": diagnostics,
    }


def internal_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": snapshot["schema_version"], "generated_at": snapshot["generated_at"],
        "operational_state": snapshot["operational_state"], "safe_open_reopen_inference": False,
        "public_notifications_enabled": False, "automatic_public_reopening_enabled": False,
        "local_sensor_commissioned_count": 0, "stage_rain_thresholds_authority": "pilot_provisional",
        "observations": [row for row in snapshot.get("observations", []) if row.get("privacy_class") == "P0_PUBLIC"],
        "diagnostics": list(snapshot.get("diagnostics", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--history-datetime")
    args = parser.parse_args()
    api_key = os.environ.get("USGS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("USGS_API_KEY is required")
    with httpx.Client(headers={"X-Api-Key": api_key, "Accept": "application/geo+json, application/json"}, timeout=60, follow_redirects=True) as client:
        snapshot = materialize_snapshot(client, history_datetime=args.history_datetime)
    projection = internal_projection(snapshot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": snapshot["schema_version"], "generated_at": snapshot["generated_at"],
        "snapshot_sha256": sha256_hex(canonical_json(projection)), "request_receipts": snapshot["request_receipts"],
        "diagnostics": snapshot["diagnostics"], "credential_persisted": False, "safe_open_reopen_inference": False,
    }
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
