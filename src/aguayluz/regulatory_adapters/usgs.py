"""Live, keyless USGS adapter for the regulatory ingestion framework.

USGS is the first live provider (of the six named in
``research/regulatory/contracts.py``'s ``Provider`` enum) because
``scripts/ingest_usgs_field_measurements.py`` and siblings already prove the OGC API
(``api.waterdata.usgs.gov``) is keyless and reachable from this environment, and
``contracts.py``'s ``PROVIDER_BASELINE_CAPABILITIES`` already scopes USGS to
``RecordFamily.ENTITY`` only — monitoring-location site metadata, never a permit or
enforcement authority. This module implements exactly that scope: nothing beyond
site metadata is claimed for USGS here.

Reuses the same ``monitoring-locations`` collection, bbox/pagination pattern, and
GeoJSON shape already live-verified by ``scripts/ingest_usgs_field_measurements.py``.

Stages, mirroring the design doc's discover/fetch/normalize/checkpoint split:

* :func:`discover` builds **page locators only** — no network call. A page (not an
  individual site) is the fetch unit: the paginated listing already carries full site
  properties per feature, so treating each site as its own fetch would mean a second,
  redundant per-site request for data already in hand. One receipt legitimately backs
  many observations (the existing regulatory framework fixture already establishes
  this: ``AYL_REGOBS_FDA_001`` and ``AYL_REGOBS_FDA_DUPLICATE`` share one receipt).
* :func:`fetch` performs the one HTTP GET a page locator names, and builds its
  :mod:`aguayluz.regulatory_db`-shaped source receipt. No auth header is ever sent —
  this endpoint is keyless — so none can leak into the receipt.
* :func:`normalize` expands one page's raw bytes into zero or more
  ``RegulatoryObservation`` dicts, each schema-valid and traceable to the page's
  receipt via a deterministic ``observation_id`` (stable hash of provider + site +
  a hash of that *feature's own properties* + normalization version — deliberately
  not the page's own bytes, since the OGC API stamps every page envelope with a
  per-request ``timeStamp`` that would otherwise mint a new id on every rerun even
  when a site's actual data hasn't changed). Replaying an unchanged site reproduces
  the same id, so the merge in ``regulatory_db`` replaces rather than duplicates it.

Pure functions, no module-level state — the CLI (``scripts/ingest_regulatory_usgs.py``)
owns checkpoint load/save and persistence, the same split ``scripts/build_alerts.py``
keeps between promoters and I/O.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

PROVIDER = "USGS"
OGC_ROOT = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
MONITORING_LOCATIONS_URL = f"{OGC_ROOT}/monitoring-locations/items"
NORMALIZATION_VERSION = "usgs/v1"
DEFAULT_LIMIT = 1000
#: Bound on page locators discover() emits per call — a resumable ceiling, not a
#: claim that PR's whole monitoring-locations catalogue fits in one run.
MAX_PAGES = 20


def capabilities() -> dict[str, Any]:
    """Mirrors ``contracts.PROVIDER_BASELINE_CAPABILITIES[Provider.USGS]``."""
    return {
        "provider": PROVIDER,
        "record_families": ["entity"],
        "pagination": "offset",
        "authentication_class": "public_or_key",
        "rate_limit_policy": "bounded",
        "public_export_constraints": [],
    }


def _site_no(raw: str) -> str:
    """Strip the USGS- provider prefix, e.g. ``'USGS-50038100'`` -> ``'50038100'``."""
    return raw.removeprefix("USGS-").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def discover(
    *,
    bbox: str,
    checkpoint: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build page locators for the ``monitoring-locations`` bbox query.

    Resumes from ``checkpoint["cursor"]`` (a page count, not a raw record offset) so
    a later run continues past what an earlier run already fetched rather than
    re-covering the same pages. No network call happens here.
    """
    start_page = int((checkpoint or {}).get("cursor") or 0)
    locators = []
    for page in range(start_page, start_page + MAX_PAGES):
        offset = page * limit
        locators.append({
            "provider": PROVIDER,
            "provider_record_id": f"page:{offset}",
            "locator": (
                f"{MONITORING_LOCATIONS_URL}?f=json&bbox={bbox}"
                f"&limit={limit}&offset={offset}"
            ),
            "record_family": "entity",
        })
    next_checkpoint = {"provider": PROVIDER, "cursor": str(start_page + MAX_PAGES), "bbox": bbox}
    return locators, next_checkpoint


def fetch(locator: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Retrieve one page's raw bytes and build its source receipt."""
    import httpx

    with httpx.Client(timeout=180, follow_redirects=True) as client:
        r = client.get(locator["locator"])
        r.raise_for_status()
        content = r.content
        status = r.status_code
        media_type = r.headers.get("content-type", "application/json").split(";")[0].strip()

    digest = hashlib.sha256(content).hexdigest()
    receipt = {
        "receipt_id": f"AYL_REGRCPT_USGS_{digest[:24]}",
        "provider": PROVIDER,
        "retrieved_at": _now_iso(),
        "request_locator": locator["locator"],
        "http_status": status,
        "sha256": digest,
        "byte_count": len(content),
        "media_type": media_type or "application/json",
        "retrieval_status": "success",
        "redactions": [],
    }
    return content, receipt


def normalize(raw: bytes, receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand one page's raw GeoJSON bytes into RegulatoryObservation dicts.

    ``observed_at`` is stamped equal to ``retrieved_at``: monitoring-locations is site
    *metadata*, not a dated reading, so there is no more honest "observed" timestamp
    than the moment this snapshot of it was retrieved.

    ``observation_id`` is hashed from each feature's own ``properties`` — never from
    ``receipt["sha256"]``. The OGC API wraps every page in an envelope carrying a
    per-request ``timeStamp``, so two live fetches of an unchanged site never produce
    byte-identical *pages* even though the site's own content is unchanged; hashing
    off the page-level receipt would mint a new observation_id on every single run,
    breaking replay idempotency. Hashing off the feature's own properties instead
    means the id changes only when USGS's actual data for that site changes.
    """
    doc = json.loads(raw)
    features = doc.get("features") or []
    observations: list[dict[str, Any]] = []
    for feat in features:
        props = feat.get("properties") or {}
        site = _site_no(str(props.get("monitoring_location_number") or props.get("id") or ""))
        if not site:
            continue
        content_hash = hashlib.sha256(
            json.dumps(props, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        material = f"USGS\0{site}\0{content_hash}\0{NORMALIZATION_VERSION}".encode()
        observation_id = f"AYL_REGOBS_USGS_{hashlib.sha256(material).hexdigest()[:24]}"
        observations.append({
            "observation_id": observation_id,
            "record_family": "entity",
            "provider": PROVIDER,
            "provider_record_id": site,
            "observed_at": receipt["retrieved_at"],
            "retrieved_at": receipt["retrieved_at"],
            "source_receipt_id": receipt["receipt_id"],
            "normalization_version": NORMALIZATION_VERSION,
            "evidence_tier": "T1",
            "freshness_state": "current",
            "identifiers": [{"scheme": "usgs_site_no", "value": site}],
            "payload": {
                "name": (props.get("monitoring_location_name") or "").strip(),
                "site_type_code": (props.get("site_type_code") or "").strip(),
                "county_name": (props.get("county_name") or "").strip(),
                "altitude": props.get("altitude"),
                "hydrologic_unit_code": props.get("hydrologic_unit_code"),
            },
        })
    return observations
