"""Shared contracts for bounded USGS Water Data API ingestion.

The functions in this module are deliberately source-shape tolerant but fail closed:
unparseable values, dates, identifiers, units, or unsupported parameters are skipped
and accounted for by the caller rather than coerced.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable, Iterator, Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

OGC_COLLECTIONS = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
STATISTICS_ROOT = "https://api.waterdata.usgs.gov/statistics/v0"
RTFI_ROOT = "https://api.waterdata.usgs.gov/rtfi-api"
NIMS_ROOT = "https://api.waterdata.usgs.gov/nims/v0"
SAMPLES_RESULTS = "https://api.waterdata.usgs.gov/samples-data/results/narrow"
WQP_STATIONS = "https://www.waterqualitydata.us/data/Station/search"
WQP_RESULTS = "https://www.waterqualitydata.us/data/Result/search"

PR_BBOX = (-67.95, 17.70, -65.20, 18.70)
PR_STATE_FIPS = "72"
DEFAULT_PAGE_SIZE = 500
DEFAULT_MAX_PAGES = 200

PARAMETER_METRICS: dict[str, tuple[str, str]] = {
    "00054": ("reservoir_storage_pct", "%"),
    "00060": ("streamflow", "ft3/s"),
    "00065": ("gage_height", "ft"),
    "62610": ("groundwater_level", "ft"),
    "62614": ("reservoir_elevation", "ft"),
    "62615": ("reservoir_elevation", "ft"),
    "72019": ("groundwater_level", "ft"),
    "72375": ("reservoir_elevation", "ft"),
    "72379": ("reservoir_elevation", "ft"),
}


class ContractError(ValueError):
    """Raised when a source response violates a required ingestion contract."""


def api_headers(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return secret-safe request headers.

    The key is read only at request time and never persisted in receipts or outputs.
    """
    source = os.environ if env is None else env
    key = str(source.get("USGS_API_KEY", "")).strip()
    return {"X-Api-Key": key} if key else {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bare_site(value: Any) -> str:
    raw = str(value or "").strip()
    return raw.split("-", 1)[-1] if raw else ""


def safe_float(value: Any) -> float | None:
    if value in (None, "", "-999999", "-999999.0"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def iso_day(value: Any) -> str | None:
    raw = str(value or "").strip()
    if len(raw) >= 10:
        candidate = raw[:10]
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            return None
    return None


def timestamp_token(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    return "".join(ch for ch in raw if ch.isdigit())[:14] or "unknown"


def stable_hash(*parts: Any) -> str:
    payload = "|".join(str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def flatten_features(documents: Any) -> list[dict[str, Any]]:
    if isinstance(documents, dict):
        documents = [documents]
    rows: list[dict[str, Any]] = []
    for doc in documents or []:
        if not isinstance(doc, dict):
            continue
        features = doc.get("features")
        if isinstance(features, list):
            rows.extend(feature for feature in features if isinstance(feature, dict))
    return rows


def next_link(document: Mapping[str, Any]) -> str | None:
    for link in document.get("links") or []:
        if isinstance(link, Mapping) and link.get("rel") == "next":
            href = str(link.get("href") or "").strip()
            if href:
                return href
    return None


def iter_ogc_pages(
    client: Any,
    url: str,
    params: Mapping[str, Any],
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> Iterator[dict[str, Any]]:
    """Yield bounded OGC FeatureCollection pages, following server next links."""
    request_params = dict(params)
    request_params.setdefault("f", "json")
    request_params.setdefault("limit", page_size)
    current_url: str | None = url
    current_params: Mapping[str, Any] | None = request_params
    for _ in range(max_pages):
        response = client.get(current_url, params=current_params, headers=api_headers())
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict):
            raise ContractError("USGS response is not a JSON object")
        yield document
        href = next_link(document)
        if href:
            current_url, current_params = href, None
            continue
        returned = document.get("numberReturned")
        features = document.get("features") or []
        if isinstance(returned, int) and returned >= page_size:
            offset = int(request_params.get("offset", 0)) + page_size
            request_params["offset"] = offset
            current_url, current_params = url, request_params
            continue
        if len(features) >= page_size:
            offset = int(request_params.get("offset", 0)) + page_size
            request_params["offset"] = offset
            current_url, current_params = url, request_params
            continue
        return
    raise ContractError(f"pagination exceeded max_pages={max_pages}")


def read_json_documents(paths: Iterable[Path]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            documents.append(value)
        elif isinstance(value, list):
            documents.extend(item for item in value if isinstance(item, dict))
        else:
            raise ContractError(f"{path}: expected JSON object or list")
    return documents


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def merge_by_key(
    existing: Iterable[dict[str, Any]],
    new: Iterable[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*existing, *new]:
        value = str(row.get(key) or "").strip()
        if not value:
            raise ContractError(f"row missing merge key {key}")
        merged[value] = row
    return [merged[item] for item in sorted(merged)]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in materialized),
        encoding="utf-8",
    )
    tmp.replace(path)


def metric_for_parameter(parameter_code: Any) -> tuple[str, str] | None:
    return PARAMETER_METRICS.get(str(parameter_code or "").strip())


def reading_row(
    *,
    site: str,
    parameter_code: str,
    value: float,
    unit: str,
    observed_at: str,
    source_ref: str,
    provisional: bool,
    id_namespace: str,
    asset_prefix: str = "USGS_",
    review_status: str = "accepted",
) -> dict[str, Any] | None:
    metric = metric_for_parameter(parameter_code)
    day = iso_day(observed_at)
    if metric is None or day is None or not site or not unit:
        return None
    metric_name, _default_unit = metric
    token = timestamp_token(observed_at)
    return {
        "reading_id": f"AYL_RDG_{day.replace('-', '')}_{id_namespace}_{site}_{parameter_code}_{token}",
        "asset_id": f"{asset_prefix}{site}",
        "site_no": site,
        "metric": metric_name,
        "parameter_code": parameter_code,
        "value": value,
        "unit": unit,
        "observed_date": day,
        "provisional": provisional,
        "source_ref": source_ref,
        "source_hash": stable_hash(site, parameter_code, observed_at, value, unit),
        "evidence_tier": "T1",
        "confidence": 75 if provisional else 80,
        "review_status": review_status,
    }


def source_receipt(
    *,
    category: str,
    source_url: str,
    rows_written: int,
    skipped: Mapping[str, int],
    live: bool,
) -> dict[str, Any]:
    return {
        "category": category,
        "source_url": source_url,
        "retrieved_at": utc_now(),
        "rows_written": rows_written,
        "skipped": dict(sorted(skipped.items())),
        "live": live,
        "api_key_present": bool(api_headers()),
        "credential_material_persisted": False,
    }
