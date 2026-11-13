"""Read-only API for the PRDNER aquifer condition bands (south-coast observation wells).

Serves the committed registry written by ``scripts/ingest_prdner_well_bands.py`` together
with the latest local depth-to-water reading for each well, classified at request time by
``aguayluz.aquifer_bands``. Nothing is persisted: the class is a pure function of the
registry and a reading, so there is no state file to go stale.

Stdlib + FastAPI only -- the gui-parity CI job boots this backend without the geospatial
stack. There is deliberately no write path: the producer is scheduled, and a panel that
could trigger a scrape of a third-party page on demand would add load and failure modes
without adding evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aguayluz import DATA_DIR as _DEFAULT_DATA_DIR
from aguayluz import aquifer_bands as ab

router = APIRouter(tags=["aquifer"])

#: Resolved per request so tests (and AGUAYLUZ_DATA_HOME) can redirect it.
DATA_DIR: Path = _DEFAULT_DATA_DIR

SCOPE_STATEMENT = (
    "Condition bands (Optimum, Observation, Operational Adjustment, Critical) that a USGS page "
    "attributes to the Puerto Rico Department of Natural and Environmental Resources, applied "
    "to the latest depth-to-water reading of five south-coast observation wells. This is "
    "operational documentation (tier T2) with no published effective date, applied to "
    "provisional USGS data that is subject to revision. A class is an observed condition, "
    "not an alert, a confirmed shortage or a service impact."
)
ALERTING_REASON = (
    "Display only: the monitoring lifecycle ignores provisional readings by policy, and these "
    "wells' current readings are provisional."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/aquifer/bands")
def aquifer_bands() -> JSONResponse:
    now = _now()
    registry = ab.current_registry(ab.read_jsonl(DATA_DIR / ab.REGISTRY_FILE))
    receipt = ab.load_receipt(DATA_DIR)
    readings = ab.latest_readings(list(registry), DATA_DIR)
    items: list[dict[str, Any]] = [
        ab.well_view(row, readings.get(site), now.date()) for site, row in registry.items()
    ]
    with_reading = [item for item in items if item["reading"] is not None]
    return JSONResponse({
        "scope": {
            "statement": SCOPE_STATEMENT,
            "completeness_claimed": False,
            "evidence_tier": ab.EVIDENCE_TIER,
            "authority_claim": ab.AUTHORITY_CLAIM,
            "effective_date": None,
            "effective_date_status": ab.EFFECTIVE_DATE_STATUS,
            "parameter_code": ab.PARAMETER_CODE,
            "depth_convention": ab.DEPTH_CONVENTION,
            "alerting": "display_only",
            "alerting_reason": ALERTING_REASON,
        },
        "generated_at": _iso(now),
        "source": {
            "source_id": ab.SOURCE_ID,
            "url": ab.PAGE_URL,
            "freshness": ab.freshness(receipt, now),
            "receipt": receipt,
        },
        "classes": [{"id": cls, "label": ab.CLASS_LABELS[cls]} for cls in ab.CLASSES],
        "counts": {
            "wells": len(items),
            "with_reading": len(with_reading),
            "provisional_readings": sum(1 for item in with_reading if item["reading"]["provisional"]),
            "stale_readings": sum(1 for item in with_reading if item["reading"]["stale"]),
            "critical": sum(1 for item in items if item["class"] == "critical"),
        },
        "items": items,
    })
