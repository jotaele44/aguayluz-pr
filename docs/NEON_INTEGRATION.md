# NEON integration (Domain D04 — Puerto Rico)

How AguaYLuz consumes the NSF National Ecological Observatory Network API, why it is
split into a keyless half and a token-gated half, and what is deliberately deferred.

## Why NEON

The producer's hydrology backbone is regulatory and operational — USGS NWIS gauges,
NOAA CO-OPS tide stations, EPA SDWIS/ECHO enforcement. None of it carries
research-grade stream chemistry, and none of it covers the southwest dry-forest /
Lajas valley corridor at sensor density. NEON does, at four sites:

| Code | Name | NEON type | Habitat | Lat / Lon | Municipality | Products |
|---|---|---|---|---|---|---|
| `CUPE` | Río Cupeyes NEON | CORE | aquatic | 18.11352 / -66.98676 | San Germán | 79 |
| `GUAN` | Guánica Forest NEON | CORE | terrestrial | 17.96955 / -66.86870 | Guánica | 87 |
| `GUIL` | Río Yahuecas NEON | GRADIENT | aquatic | 18.17406 / -66.79868 | Adjuntas | 85 |
| `LAJA` | Lajas Experimental Station NEON | GRADIENT | terrestrial | 18.021261 / -67.076889 | Lajas | 77 |

D04 "Atlantic Neotropical" is the only NEON domain with Puerto Rico sites.
Municipalities are resolved by point-in-polygon against `data/geo/pr_municipios.geojson`,
reusing `municipality_for()` from `scripts/ingest_usgs_water.py`.

## Endpoint map — the split that shapes everything

Verified against the live API. `data.neonscience.org/api/v0`:

| Endpoint | Anonymous | Notes |
|---|---|---|
| `/sites`, `/sites/{code}` | **200** | `/sites` returns every NEON site worldwide (~26 MB); we fetch the four PR sites individually instead |
| `/products`, `/products/{code}` | **200** | |
| `/locations/{code}` | **200** | |
| `/releases`, `/releases/{name}` | **200** | |
| `/data/{product}/{site}/{month}` | **403** | `{"error":{"status":403,"detail":"Access Denied"},"data":null}` — NEON's own gateway, not a local proxy |

Two consequences:

1. **The entire publication-change signal is keyless.** `/sites/{code}` returns
   `availableMonths[]` for every product at that site. Diffing it run over run yields
   new releases, new products and corrected historical months with nothing downloaded.
2. **Bulk file access needs a token**, so `scripts/ingest_neon_products.py` is gated.

### Authentication

- Header is **`X-API-Token`**, not `Authorization: Bearer`. A bearer token is silently
  ignored, leaving you anonymous at the lower rate limit.
- Resolution order: explicit arg → `$NEON_API_TOKEN` → `$NEON_API_KEY` → `None`.
  `None` is a supported mode, unlike `WatersClient` which raises.
- **An invalid token is worse than no token**: it turns an otherwise-200 anonymous
  request into a 403. `NeonClient` therefore raises `NeonAuthError` for a 403 *with* a
  token (fix the credential) and `NeonAccessDenied` for a 403 *without* one (the
  endpoint is gated), and never silently retries anonymously.
- Rate limit: 200 requests/hour anonymously, higher with a token. Every response
  carries `X-RateLimit-Remaining`, which the client logs and the health check reports.

## Pipeline

```
NEON /sites/{code}  (keyless, 4 requests)
      │
      ▼
scripts/ingest_neon.py
      ├─► data/utility_assets.jsonl          NEON_<site> rows        (committed)
      ├─► data/neon_availability.jsonl       site × product state    (committed)
      ├─► data/neon_publication_events.jsonl deduped event log       (committed)
      ├─► outputs/neon_changes.jsonl         this run's delta
      └─► outputs/neon_health.json           provider health record
                    │
      ┌─────────────┴──────────────┐
      ▼                            ▼
scripts/ingest_neon_products.py   scripts/build_alerts.py
  (needs NEON_API_TOKEN)            └─► data/alert_events.jsonl
      └─► data/neon_readings.jsonl        (gitignored, auto-globbed by the exporter)
```

### Why two of these files are committed

`.gitignore` blocks `data/*` and re-includes specific files. The time-series reading
files (`reservoir_levels`, `groundwater_levels`, `coastal_levels`, and now
`neon_readings`) stay ignored — they are regenerable output.

`neon_availability.jsonl` and `neon_publication_events.jsonl` are **not** regenerable:
the availability snapshot *is* the previous state the delta is computed against. If it
were gitignored, every CI runner would start from empty and report all 328 site/product
pairs as new on every run.

For the same reason, a **bootstrap run with no previous state emits no changes at all**.
There is no delta against nothing, and treating NEON's decade-old catalogue as 328
`new_product` events would flood the alert layer on first adoption. The registry is
populated on that run; the first real delta lands on the next one.

### Compact month storage

`availableMonths` holds ~100 entries per product; 328 pairs of those would bloat a
committed file. Each row stores `month_count`, `first_month`, `latest_month` and a
**`months_sha256`** over the sorted month list. The hash detects a back-filled
historical month — the "corrected product" case — that a `latest_month` comparison
alone would miss.

## Change types

Emitted by `diff_availability()` in `scripts/ingest_neon.py` (pure; `today` injected):

| Type | Meaning |
|---|---|
| `new_month` | A newer month was published — the routine monthly release |
| `backfilled_month` | The month hash moved but `latest_month` did not: a historical month was corrected or re-released |
| `new_product` | A product appeared at a site for the first time |
| `new_release` | The site's newest NEON RELEASE tag changed |
| `publication_gap` | A monthly-cadence product has not published in `--stale-months` months |

`publication_gap` is checked **only** for `MONTHLY_CADENCE_PRODUCTS` (continuous AIS
sensors and regular monthly sampling). Campaign-sampled products —
`DP1.20193.001` salt-based discharge, `DP1.20048.001` field gauging — are irregular by
design (48 months across an 8-year record) and would otherwise fire constantly on a
perfectly healthy feed.

## Product → metric

`schemas/monitoring_reading.schema.json` has a **closed `metric` enum**, so only
products that map onto an existing value are promoted to readings:

| NEON product | Title | `metric` | CSV column(s) read | Unit stored |
|---|---|---|---|---|
| `DP4.00130.001` | Continuous discharge | `streamflow` | `maxpostDischarge`, `continuousDischarge` | m3/s (NEON publishes L/s) |
| `DP1.20193.001` | Salt-based stream discharge | `streamflow` | `finalDischarge`, `streamDischarge` | m3/s |
| `DP1.20048.001` | Discharge field collection | `streamflow` | `finalDischarge`, `totalDischarge` | m3/s |
| `DP1.20016.001` | Elevation of surface water | `gage_height` | `surfacewaterElevMean`, `surfacewaterElev` | m |
| `DP1.20093.001` | Chemical properties of surface water | `water_quality` | `specificConductance` | uS/cm |
| `DP1.20033.001` | Nitrate in surface water | `water_quality` | `surfWaterNitrateMean`, `surfWaterNitrate` | uM |
| `DP1.20097.001` | Dissolved gases in surface water | `water_quality` | `dissolvedCO2` | mol/mol |

### Units bind to the column, not the product

Where a product lists several CSV columns they are **naming variants of one
measurement**, and each candidate in `CSV_COLUMNS` carries its own `unit` and
`scale`. That is deliberate. An earlier version put a single unit on the product,
so a fallback to the second column inherited the first column's unit — with
`["specificConductance", "waterTemp"]` under one `uS/cm`, a file carrying only
`waterTemp` would have stored a temperature labelled as conductance. A
plausible-looking wrong number is worse than no number, and the parser's
"skip the file" fail-safe did not catch it, because a column *was* matched.

Two rules follow, both enforced by `tests/test_ingest_neon_products.py`:

1. Every candidate for a product measures the same physical quantity. A different
   analyte (CH4 vs CO2) or quantity (temperature vs conductance) gets its own
   product entry or none — never a fallback, since `metric` + `parameter_code`
   would otherwise stop identifying what was measured.
2. Therefore every candidate for a product shares one unit.

`waterTemp` and `dissolvedCH4` were removed as fallbacks under this rule. A file
without the documented column is skipped with a warning.

Sub-daily sensor records are reduced to a **daily mean per site/metric**, matching the
schema's `AYL_RDG_<YYYYMMDD>_<site>_<metric>` "stable per asset/metric/day" contract.
Rows whose NEON QA flag (`finalQF` and friends) is `1` are dropped before aggregation.

### Deferred products

Tracked for availability — so their releases still alert — but **not** promoted to
readings, because each needs a new `metric` enum value:

| NEON product | Needs `metric` |
|---|---|
| `DP1.00045.001` Precipitation - tipping bucket | `precipitation` |
| `DP1.00006.001` Precipitation | `precipitation` |
| `DP1.00013.001` Wet deposition chemical analysis | `precipitation` |
| `DP1.00094.001` Soil water content and salinity | `soil_moisture` |
| `DP1.00041.001` Soil temperature | `soil_temperature` |
| `DP4.00200.001` Bundled eddy covariance | `evapotranspiration` |

The follow-up is to extend the enum in `schemas/monitoring_reading.schema.json` and
move the entry from `DEFERRED_PRODUCTS` up into `PRODUCT_METRICS` — the schema edit
should land with the code that consumes it, not ahead of it.

## Alerts

`schemas/alert_event.schema.json` pins `module_id` to a closed ten-value enum, so there
is no "data publication" module to add. `src/aguayluz/alert_promotion/neon.py` routes
onto existing modules by what the product measures:

| Signal | Module | `event_type` | Severity |
|---|---|---|---|
| Chemistry / nitrate / dissolved gases release | `CONTAMINATION` | `quality` | 2 |
| Discharge / surface-water elevation release | `HYDRO_OPS` | `quality` | 2 |
| Precipitation / meteorology release | `WEATHER_HAZARD` | `quality` | 2 |
| New product / new release tag | routed as above | `quality` | 1 |
| Publication gap | `TELECOM_SCADA` | `failure` | 2 |

`TELECOM_SCADA` was seeded dormant with the charter "telemetry and control loss at
remote infrastructure". A monitoring station that stops publishing for months is
exactly that, so this feed activates it — the same mechanism by which the USGS
earthquake ingest activated `SEISMIC_GEO`.

No NEON alert reaches `CRITICAL_SEVERITY` (4). A publication event is an operator
signal, not a life-safety one, and must not trigger push/SMS fan-out.

Two details that fail schema validation if missed:

- `alert_id` matches `^AYL_ALR_[0-9]{8}_[A-Za-z0-9_-]+$` — **dots are forbidden**, and
  every NEON product code has two. `sanitize_code()` maps `DP4.00130.001` →
  `DP4_00130_001`.
- The date component is anchored on the **published month**, not the detection time, so
  re-detecting a publication keeps a stable `alert_id` and the idempotent merge in
  `scripts/build_alerts.py` replaces the row instead of accumulating one per run.

## Running it

```bash
python scripts/ingest_neon.py                       # keyless; no credential needed
python scripts/ingest_neon.py --src tests/fixtures/neon_site_cupe_sample.json   # offline

export NEON_API_TOKEN=...                           # https://data.neonscience.org/myaccount
python scripts/ingest_neon_products.py              # exits 0 with a notice if unset
```

Cadence in `scripts/refresh.py`: `ingest_neon.py` runs `daily`/`weekly`/`all` (NEON
publishes monthly, so a daily poll is ample at 4 requests against a 200/hour quota);
`ingest_neon_products.py` runs `weekly`/`all`. Both are `optional=True`.

## Known limitations

- **The live download path is unverified.** `/api/v0/data/` is credential-gated and no
  NEON token was available when this was built, so `scripts/ingest_neon_products.py`
  has not been exercised end-to-end against a real response. Its fixtures
  (`tests/fixtures/neon_data_manifest_sample.json`,
  `neon_continuous_discharge_sample.csv`) are **SYNTHETIC** — hand-authored from NEON's
  published response and file formats and labelled as such in the files themselves.
  They exercise this repo's parsing, unit-conversion, QA-flag and md5-integrity logic
  correctly; they do **not** prove the CSV column names match a real NEON download.
  The parser fails safe — a file with no documented column is skipped with a warning
  rather than read from a guessed column. First run with a real token should be
  reviewed against `docs/NEON_INTEGRATION.md`'s product table before the output is
  trusted. This gating is recorded in `federation.json#waf_blocked_sources`.
- `asset_type` is `water` for all four sites. GUAN and LAJA are a dry forest and an
  agricultural station rather than water infrastructure, but the enum offers only
  water/wastewater/power/telecom/fuel/unknown and their hydrologic products are why
  this producer wants them. The distinction is carried in `asset_subtype`
  (`research_station_aquatic` / `research_station_terrestrial`), never flattened.
- Retired site/product pairs are dropped from the registry rather than tombstoned. NEON
  removing a product from a site is rare, and a stale row would keep re-firing
  `publication_gap`.
