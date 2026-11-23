"""Read-only API for the USGS Puerto Rico water-use estimates (2010 / 2015 / 2020).

Serves the committed rows written by ``scripts/ingest_usgs_water_use.py``: public-supply
withdrawals by source (surface water, groundwater), island-wide and by municipality, with
the other freshwater categories for context. Shares are computed at request time from the
stored values (``aguayluz.water_use.island_summary``); nothing is persisted.

Stdlib + FastAPI only -- the gui-parity CI job boots this backend without the geospatial
stack. There is no write path: the sources are static publications re-read on demand by a
person, so a button that re-downloaded them would add failure modes without adding evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aguayluz import CONFIG_DIR as _DEFAULT_CONFIG_DIR
from aguayluz import DATA_DIR as _DEFAULT_DATA_DIR
from aguayluz import water_use as wu

router = APIRouter(tags=["water-use"])

#: Resolved per request so tests (and AGUAYLUZ_DATA_HOME) can redirect them.
DATA_DIR: Path = _DEFAULT_DATA_DIR
CONFIG_DIR: Path = _DEFAULT_CONFIG_DIR

SCOPE_STATEMENT = (
    "U.S. Geological Survey estimates of freshwater withdrawals in Puerto Rico for 2010, 2015 and "
    "2020, in million gallons per day. Public supply covers PRASA and non-PRASA community systems. "
    "These are five-yearly compilations, not measurements of current production: nothing here is "
    "newer than 2020. Withdrawals are counted in the municipality where the intake is, not where "
    "the water is used. The 2010 figures are a manual transcription from a PDF report (tier T2); "
    "2015 and 2020 are read from USGS data-release tables (tier T1)."
)
ALERTING_REASON = "Historical estimates published every five years; there is nothing to alert on."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_list() -> list[dict[str, object]]:
    try:
        config = wu.load_sources(CONFIG_DIR)
    except (OSError, ValueError):
        return []
    entries = [*config["sources"], config["transcription_2010"]]
    return [
        {
            "source_key": entry["source_key"],
            "year": entry["year"],
            "title": entry["title"],
            "doi": entry["doi"],
            "url": entry["source_url"],
            "evidence_tier": entry["evidence_tier"],
            "sha256": entry["pinned_sha256"],
            "retrieved_utc": entry["retrieved_utc"],
            "extraction_method": "manual_transcription" if "values" in entry else "xlsx_cell",
        }
        for entry in entries
    ]


@router.get("/water-use/estimates")
def water_use_estimates() -> JSONResponse:
    rows = wu.load_estimates(DATA_DIR)
    receipt = wu.load_receipt(DATA_DIR)
    years = wu.island_summary(rows)
    return JSONResponse({
        "scope": {
            "statement": SCOPE_STATEMENT,
            "completeness_claimed": False,
            "unit": wu.UNIT,
            "evidence_tiers": sorted({str(row["evidence_tier"]) for row in rows}),
            "latest_year": max((year["year"] for year in years), default=None),
            "alerting": "not_applicable",
            "alerting_reason": ALERTING_REASON,
        },
        "generated_at": _iso(_now()),
        "source": {
            "source_id": wu.SOURCE_ID,
            "last_status": (receipt or {}).get("last_status"),
            "last_success_utc": (receipt or {}).get("last_success_utc"),
            "last_error": (receipt or {}).get("last_error"),
            "sources": _source_list(),
        },
        "categories": [{"id": c, "label": wu.CATEGORY_LABELS[c]} for c in wu.CATEGORIES],
        "counts": {"records": len(rows), "years": len(years)},
        "years": years,
        "municipios": {
            "public_supply": wu.municipio_table(rows, "public_supply"),
            "irrigation": wu.municipio_table(rows, "irrigation"),
        },
        "restatements": wu.restatements(years),
        "related": {"aquifer_bands": "/aquifer-bands"},
    })
