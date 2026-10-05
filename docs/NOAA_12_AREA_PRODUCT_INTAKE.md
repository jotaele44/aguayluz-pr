# NOAA twelve-area product intake and build gates

Status: planning inventory, not runtime configuration. Live-source certification: OPEN.
Recorded 2026-10-05. Scope remains exactly the twelve approved weather.gov menu areas.
This inventory enumerates candidate product families, not every NOAA dataset.
No source has been enabled by this document.

## Binding architecture

Reuse existing acquisition, scheduling, monitoring, provenance and GUI paths.
Aviation routes to PITIRRE/SkyWatcher; Marine to PITIRRE/MarineWatcher;
Space Weather to PITIRRE/SpaceWatcher. Spiderweb retains geometry authority.
AguaYLuz retains its existing water infrastructure measurements and consumes
relevant shared hazards. A watcher route is not an instruction to duplicate a
producer. Other destinations below are planning recommendations from the audit.

Each new product must add distinct user value, demonstrate coverage for the
intended Puerto Rico area or stations, and avoid duplicating an existing source.
Global space-weather applicability must be explicit; global indices alone do
not establish a local outage or impact.

## Repository evidence boundary

Audit baseline: AguaYLuz a22970f44a4e066d8eff0e17c1edef4c79d63ec3;
PITIRRE/skywatcher-pr 2100e6527d49abc302b804d3175feea9ce614eb4.
Prerequisite AguaYLuz PR325 head a7df1b91e7fe32642d1ea2ef19e10e99661a2a55
builds on 55619dc91a814efdfab8e2436865da3c164857f6.
PITIRRE PR342 head b93517d4145452c88fb24ec15f715219fd7f24a4
builds on the audited PITIRRE baseline.
Both PRs remained draft/open when checked. No merge or deployment is claimed.

The commit workflow query returned 14 successful PR workflows for AguaYLuz
and 9 for PITIRRE, including GUI parity:
- https://github.com/jotaele44/aguayluz-pr/actions/runs/37246919546
- https://github.com/jotaele44/skywatcher-pr/actions/runs/37246854223

This is evidence for the queried heads and returned workflow page, not every
possible check or production state. AguaYLuz's PR metadata reports mergeable=false;
that condition remains unresolved. Passing workflows do not settle mergeability.
The NWS full identity, complete-snapshot retirement, expiry and raw-warning
semantics repairs are proposed in PR325. PITIRRE's GUI test parse repair is
proposed in PR342. NHC raw event semantics and full CAP relationships remain open.

## Twelve-area intake matrix

PARTIAL means an existing category-relevant path; FOUNDATION means reusable
storage/contracts/context without dedicated acquisition; NOT_FOUND means the
bounded audit did not establish a dedicated implementation. These are development
states, not live certification or percentages of all provider products.

| Area | Development state | Reuse / evidence | Candidate next products and class | Destination / gate |
|---|---|---|---|---|
| Local | PARTIAL | scripts/ingest_nws_alerts.py; alert promotion, API and GUI | NWS point/zone forecasts (forecast); station conditions (observation) | AguaYLuz; resolve actual PR points and returned forecast URLs before selecting an adapter |
| Graphical | NOT_FOUND | Existing MapLibre and drought presentation | NDFD fields (forecast); radar reflectivity (observation); QPE (analysis) | Underlying domain owner; rendering is a manifestation, not another producer |
| Aviation | FOUNDATION | PITIRRE airport_states weather_json; console explicitly lacks official METAR/TAF adapter | AWC METAR (observation), TAF (forecast), SIGMET (warning), station metadata (reference) | SkyWatcher; validate chosen ICAO stations, issue/valid times, missing data and API limits |
| Marine | PARTIAL | AguaYLuz ingest_noaa_tides.py and coastal monitoring; PITIRRE coastal/maritime registry | Coastal/offshore forecasts (forecast), wind/wave observations, marine advisories (warning) | MarineWatcher; reuse CO-OPS measurements through shared consumption; validate zone and station coverage |
| Rivers and Lakes | PARTIAL | Existing USGS producers, water_monitoring_layers and monitoring console | NWS gauge forecast stages (forecast), flood outlooks (guidance), gauge metadata (reference) | AguaYLuz; reconcile station IDs and units with USGS before adding acquisition |
| Hurricanes | PARTIAL | ingest_nhc_storms.py; NHC hazard promotion and alerts | Official track/cone/wind/probability products (forecast/guidance); advisories (warning) | AguaYLuz with watcher consumers; resolve NHC raw event semantics; Spiderweb owns geometry certification |
| Severe Weather | PARTIAL | Shared NWS warnings and repaired lifecycle proposed in PR325 | CAP relationships (warning); selected radar/QPE (observation/analysis), QPF (forecast) | AguaYLuz with watcher context; acquire warnings once and distinguish estimates from forecasts |
| Fire Weather | NOT_FOUND | Generic NWS warnings are reusable but do not establish dedicated coverage | Relevant fire warnings (warning); SPC outlooks (guidance); spot products only if applicable | Conditional AguaYLuz consumption; establish PR coverage and decision value first |
| Sunrise/Sunset | NOT_FOUND | Existing location/date consumers; no established ephemeris | Sunrise/sunset (derived astronomical calculation) | Shared utility; location from authorized geometry contract, timezone/date/polar edge cases, documented algorithm |
| Long Range Forecasts | NOT_FOUND | Historical monitoring context | CPC 6–10/8–14 day and hazards outlook families (probabilistic guidance) | AguaYLuz; verify PR coverage product by product; share CPC acquisition with Climate Prediction |
| Climate Prediction | FOUNDATION | ingest_drought_usdm.py; ingest_precip_ncei.py; drought GUI | CPC monthly/seasonal/drought outlooks (probabilistic forecast/guidance) | AguaYLuz; preserve USDM/NCEI as observational context, not forecasts; avoid duplicate CPC families |
| Space Weather | FOUNDATION | PITIRRE SPACE.SPACE_WEATHER and generic replay; orbital ingestion is distinct | SWPC indices (observation), outlooks (forecast), alerts (warning) | SpaceWatcher; verify actual service schemas and freshness; express global applicability without invented local geometry |

Computed: 5 PARTIAL + 3 FOUNDATION + 4 NOT_FOUND = 12 categories reviewed.
Product denominator, payload coverage and production completeness remain UNKNOWN.

## Official discovery sources

Reviewed official documentation on 2026-10-05:
- https://www.weather.gov/gis/IDP-GISRestMetadata
- https://www.weather.gov/documentation/services-web-api
- https://aviationweather.gov/data/api/
- https://www.weather.gov/marine/
- https://www.swpc.noaa.gov/products-and-data (redirect observed to spaceweather.gov)

The GIS page lists product families under reference, climate, forecast/guidance/
warning and observation groupings. Its twelve navigation labels are not twelve
datasets. Long Range Forecasts and Climate Prediction link to the same CPC site.

AWC documents METAR/TAF worldwide coverage and G-AIRMET coverage limited to the
contiguous 48 states. Worldwide family coverage does not prove a particular
station has current data. Its API documents no browser CORS, result/rate limits,
and 204 for valid no-data requests. Acquisition should therefore run through
the existing backend and monitor, with bounded requests and explicit no-data state.

The SWPC page retrieval exposed incomplete dynamic product content and a displayed
date inconsistent with the session date. It establishes a discovery lead only;
it is not a frozen operational payload or source-time proof. Do not infer
service absence from missing rendered fields.

These are documentation reviews. No live product payload census or source-byte
freeze was performed in this increment. Candidate endpoints must be discovered
from current official schemas, not invented from menu names.

## Required per-product acceptance record

Before enabling a product, record:
1. Stable family ID, official source, schema/version, selected manifestations,
   semantic class and owner/consumers. Distinct observations, forecasts, guidance,
   warnings, reference and history remain typed separately.
2. Geographic/station coverage with evidence, exclusions and unresolved residue.
   Unsupported coverage is explicit; acquisition failure is not empty coverage.
3. Exact acquired bytes, SHA256, retrieval UTC, source issue/valid times,
   pagination and accounting of retained/excluded records. Byte identity and
   logical record identity remain distinct.
4. Existing-producer overlap and reuse decision. JSON/GeoJSON/raster/XML views
   of the same issuance do not become independent hazard counts.
5. Polling cadence, caching, retry/backoff, provider limits, freshness threshold,
   successful empty response, malformed response and outage behavior.
6. Source geometry retained with source identity; Spiderweb geometry references
   remain separate from representative points and candidate exposure.
7. Backend → API → client → visible GUI, including freshness, provenance,
   no-data, stale and error states and applicable refresh controls.
8. Targeted fixtures/negative checks and repository GUI parity gates. Never
   regenerate a baseline merely to pass. Certify only the bounded proven scope.

## Optimal continuation

First resolve PR325 mergeability while preserving both prerequisite changes;
do not equate CI success with an applied repair. Next qualify a small reusable
product slice: NWS local forecast discovery in AguaYLuz, and AWC METAR/TAF station
coverage in SkyWatcher. Select implementation only after the coverage and overlap
records support it. MarineWatcher and SpaceWatcher retain their dedicated lanes.
Fire, astronomical calculations and CPC outlooks remain within scope without
requiring speculative adapters now.

This document changes no scheduler, API, GUI, geometry authority or certification
state. Documentation-only planning adds no shipped human-facing capability.
