"""NEON -> AguaYLuz vocabulary mapping for the Puerto Rico (D04) sites.

Three tables live here so the ingest scripts and the alert promoter agree:

1. :data:`PR_SITES` — the four NEON Puerto Rico sites. NEON Domain D04 "Atlantic
   Neotropical" is the only domain with PR sites; every other NEON domain is
   out of jurisdiction for this producer.
2. :data:`PRODUCT_METRICS` — NEON data-product code -> this repo's
   ``monitoring_reading.metric``. Deliberately partial: the ``metric`` enum in
   ``schemas/monitoring_reading.schema.json`` is closed, so only products that
   map onto an existing value are promoted to readings. See
   :data:`DEFERRED_PRODUCTS` for the ones awaiting a schema edit.
3. :data:`PRODUCT_ALERT_MODULES` — NEON product -> alert module, used to route a
   publication change onto one of the ten modules the ``alert_event`` schema
   allows.
"""

from __future__ import annotations

from typing import Any

#: NEON domain covering Puerto Rico. Sites in any other domain are ignored.
PR_DOMAIN_CODE = "D04"

#: The four NEON Puerto Rico sites, as published by ``/api/v0/sites``.
#:
#: ``habitat`` distinguishes the two aquatic sites (streams — the hydrologically
#: interesting ones for this producer) from the two terrestrial sites (a dry
#: forest and an agricultural station, which carry precipitation and soil
#: products). It is NOT a NEON field: NEON's own ``siteType`` is CORE/GRADIENT,
#: which describes sampling design, not medium.
PR_SITES: list[dict[str, Any]] = [
    {
        "code": "CUPE",
        "name": "Río Cupeyes NEON",
        "site_type": "CORE",
        "habitat": "aquatic",
        "lat": 18.11352,
        "lon": -66.98676,
    },
    {
        "code": "GUAN",
        "name": "Guánica Forest NEON",
        "site_type": "CORE",
        "habitat": "terrestrial",
        "lat": 17.96955,
        "lon": -66.86870,
    },
    {
        "code": "GUIL",
        "name": "Río Yahuecas NEON",
        "site_type": "GRADIENT",
        "habitat": "aquatic",
        "lat": 18.17406,
        "lon": -66.79868,
    },
    {
        "code": "LAJA",
        "name": "Lajas Experimental Station NEON",
        "site_type": "GRADIENT",
        "habitat": "terrestrial",
        "lat": 18.021261,
        "lon": -67.076889,
    },
]

#: Site codes, for cheap membership tests.
PR_SITE_CODES: frozenset[str] = frozenset(s["code"] for s in PR_SITES)


def site_by_code(code: str) -> dict[str, Any] | None:
    return next((s for s in PR_SITES if s["code"] == code), None)


# ── product -> reading metric ─────────────────────────────────────────────────
#: NEON product code -> (metric, human title).
#:
#: Only products whose measurement maps onto the CLOSED ``metric`` enum in
#: ``schemas/monitoring_reading.schema.json`` appear here. Adding a NEON product
#: that measures something else requires extending that enum first — mapping it
#: to ``other`` instead would make ``metric`` useless for downstream filtering,
#: and inventing a value fails schema validation at ingest.
#:
#: **Units deliberately live elsewhere** — on the individual CSV column, in
#: ``scripts/ingest_neon_products.py::CSV_COLUMNS``. A product can be read from one
#: of several column names, and pinning the unit to the product let a fallback
#: column inherit the wrong one. One unit per product here would reintroduce that.
PRODUCT_METRICS: dict[str, dict[str, str]] = {
    "DP4.00130.001": {
        "metric": "streamflow",
        "title": "Continuous discharge",
    },
    "DP1.20193.001": {
        "metric": "streamflow",
        "title": "Salt-based stream discharge",
    },
    "DP1.20048.001": {
        "metric": "streamflow",
        "title": "Discharge field collection",
    },
    "DP1.20016.001": {
        "metric": "gage_height",
        "title": "Elevation of surface water",
    },
    "DP1.20093.001": {
        "metric": "water_quality",
        "title": "Chemical properties of surface water",
    },
    "DP1.20033.001": {
        "metric": "water_quality",
        "title": "Nitrate in surface water",
    },
    "DP1.20097.001": {
        "metric": "water_quality",
        "title": "Dissolved gases in surface water",
    },
}

#: Products sampled by field campaign rather than by a continuous sensor. Their
#: publication cadence is genuinely irregular — ``DP1.20193.001`` has 48 months of
#: data across an 8-year record, i.e. roughly every other month — so a
#: "no new month in N months" check fires on a perfectly healthy feed. Excluded
#: from the publication-gap detector rather than tuned around.
IRREGULAR_CADENCE_PRODUCTS: frozenset[str] = frozenset({
    "DP1.20193.001",  # Salt-based stream discharge — manual salt-injection campaigns
    "DP1.20048.001",  # Discharge field collection — manual gauging visits
})

#: Products whose absence for several months is a real signal (continuous AIS
#: sensors and regular monthly sampling). The publication-gap detector uses only
#: these.
MONTHLY_CADENCE_PRODUCTS: frozenset[str] = frozenset(
    set(PRODUCT_METRICS) - IRREGULAR_CADENCE_PRODUCTS
)

#: Products this producer wants but cannot store yet, and the ``metric`` enum
#: value each one needs. Tracked for availability (so their releases still
#: alert) but not promoted to readings. Extending the enum and moving an entry
#: up into PRODUCT_METRICS is the whole follow-up.
DEFERRED_PRODUCTS: dict[str, dict[str, str]] = {
    "DP1.00045.001": {"needs_metric": "precipitation", "title": "Precipitation - tipping bucket"},
    "DP1.00006.001": {"needs_metric": "precipitation", "title": "Precipitation"},
    "DP1.00094.001": {"needs_metric": "soil_moisture", "title": "Soil water content and salinity"},
    "DP1.00041.001": {"needs_metric": "soil_temperature", "title": "Soil temperature"},
    "DP4.00200.001": {"needs_metric": "evapotranspiration", "title": "Bundled eddy covariance"},
    "DP1.00013.001": {"needs_metric": "precipitation", "title": "Wet deposition chemical analysis"},
}


# ── product -> alert module ───────────────────────────────────────────────────
#: ``schemas/alert_event.schema.json`` pins ``module_id`` to a closed ten-value
#: enum, so a NEON publication event must land on an existing module rather than
#: a new "data publication" one. Water-chemistry products route to CONTAMINATION,
#: flow/stage to HYDRO_OPS, precipitation/met to WEATHER_HAZARD.
PRODUCT_ALERT_MODULES: dict[str, str] = {
    "DP1.20093.001": "CONTAMINATION",
    "DP1.20033.001": "CONTAMINATION",
    "DP1.20097.001": "CONTAMINATION",
    "DP1.20163.001": "CONTAMINATION",
    "DP1.20194.001": "CONTAMINATION",
    "DP4.00130.001": "HYDRO_OPS",
    "DP4.00133.001": "HYDRO_OPS",
    "DP1.20016.001": "HYDRO_OPS",
    "DP1.20048.001": "HYDRO_OPS",
    "DP1.20193.001": "HYDRO_OPS",
    "DP1.00045.001": "WEATHER_HAZARD",
    "DP1.00006.001": "WEATHER_HAZARD",
    "DP1.00013.001": "WEATHER_HAZARD",
    "DP1.00038.001": "WEATHER_HAZARD",
}

#: Module for a product with no explicit routing. HYDRO_OPS at an aquatic site,
#: WEATHER_HAZARD at a terrestrial one — the closest honest default in each case.
DEFAULT_ALERT_MODULE_BY_HABITAT: dict[str, str] = {
    "aquatic": "HYDRO_OPS",
    "terrestrial": "WEATHER_HAZARD",
}

#: Feed-health events (missing publication, sensor gap, checksum mismatch, API
#: failure) route here. TELECOM_SCADA's charter is "telemetry and control loss at
#: remote infrastructure", which is exactly a NEON sensor that stopped publishing.
FEED_HEALTH_MODULE = "TELECOM_SCADA"


def alert_module_for(product_code: str, habitat: str = "aquatic") -> str:
    """Alert module for a NEON product publication event."""
    explicit = PRODUCT_ALERT_MODULES.get(product_code)
    if explicit:
        return explicit
    return DEFAULT_ALERT_MODULE_BY_HABITAT.get(habitat, "HYDRO_OPS")


def sanitize_code(value: str) -> str:
    """Make a NEON identifier safe for an ``alert_id``.

    ``alert_id`` matches ``^AYL_ALR_[0-9]{8}_[A-Za-z0-9_-]+$`` — **dots are not
    allowed**, and every NEON product code contains two (``DP4.00130.001``).
    Silently omitting this produces rows that fail schema validation downstream
    in ``scripts/build_alert_system.py`` rather than at the promoter.
    """
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(value))


#: Evidence tier for every NEON row. NEON is an NSF-funded federal observatory
#: publishing calibrated, QA-flagged data — the same tier as USGS NWIS and NOAA.
NEON_EVIDENCE_TIER = "T1"

#: Recorded on every provenance row. NEON's data policy places its data under
#: CC BY 4.0; see https://www.neonscience.org/data-samples/data-policies-citation-guidelines
NEON_LICENSE = "CC BY 4.0 (NEON data policy)"

NEON_OPERATOR = "NSF NEON"
