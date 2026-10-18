# Outdoor conditions layer

AguaYLuz composes one **current-conditions row per municipio** (78) for time spent
outside: beach and surf, sea state, sun and heat, air, rivers and rain, and the official
alerts that apply. The rows are written to `data/outdoor_conditions.jsonl` and exported
to the PRII hub as `outdoor_condition` entities; the hub's AguaYLuz page renders them
(**Outdoor Conditions** tab). This repository's dashboard is diagnostic only (ADR 0001):
it shows the underlying sources' freshness on the **NWS Hydromet** page.

The layer is **conditions context from public sources, not safety advice**. It does not
track activities, and it is not exhaustive.

## Sources

Six sources were added for this layer. They join the NWS hydromet plane
([`NWS_HYDROMET_INTEGRATION.md`](NWS_HYDROMET_INTEGRATION.md)): responses are frozen by
byte SHA-256 before parsing, each run closes source arithmetic or fails closed with a
FAIL receipt, and each source is a registry entry in `config/hydromet_sources.v1.json`.

| Source (`source_id`) | Ingest | What it carries | Cadence |
|---|---|---|---|
| NWS San Juan Surf Zone Forecast (`nws_surf_zone`) | `scripts/ingest_nws_surf_zone.py` | Rip current risk (Low / Moderate / High) for today and tomorrow, surf height for five days, per beach zone | 15 min (WFO issues ~2 a day) |
| NWS marine-zone alerts (`nws_marine_alerts`) | `scripts/ingest_nws_marine_alerts.py` | Small Craft Advisory, Gale Warning and other alerts for the San Juan marine zones (AMZ7xx) | 15 min |
| NDBC/CARICOOS buoys (`ndbc_buoys`) | `scripts/ingest_ndbc_buoys.py` | Wave height and period, wind, water temperature at buoys 41053, 41056, 41115, 41121, 42085 | 15 min |
| EPA UV index (`epa_uv`) | `scripts/ingest_epa_uv.py` | Daily maximum UV index, one ZIP per municipio | daily |
| NWS gridded heat index (`nws_gridpoint_heat`) | `scripts/ingest_nws_gridpoint_heat.py` | Maximum heat index, wet-bulb globe temperature and air temperature over the next 24 and 48 h at each municipio's internal point | daily |
| AirNow (`airnow`) | `scripts/ingest_airnow.py` | Current AQI by reporting area and pollutant (Saharan dust shows as PM10/PM2.5) | 15 min; **needs `AIRNOW_API_KEY`** |

All six are keyless except AirNow. Without the `AIRNOW_API_KEY` repository secret the
AirNow ingest prints why and exits 0 **without writing a receipt**, so the source reads
`NEVER` and the air-quality component reads `NOT_CONFIGURED`. Its tests run on a fixture
constructed from AirNow's documented format (`tests/fixtures/outdoor/airnow/README.md`);
the live path has not run here.

The composer also folds in conditions the corpus already held:

| Component | Existing input |
|---|---|
| `river_flood` | NWPS gauge state (`data/nwps_gauge_state.jsonl`) |
| `rainfall_24h` | Stage IV 1-day rainfall records (hydromet plane) |
| `nws_alerts` | NWS land-zone alerts (`scripts/ingest_nws_alerts.py` → `data/service_events.jsonl`) — Heat Advisory, Rip Current Statement, Flood Advisory and the rest |
| `tropical_cyclone` | NHC advisories in the PR approach corridor (`scripts/ingest_nhc_storms.py`) |
| `earthquakes` | USGS quakes M3.5+ within 100 km in the last 24 h (`scripts/ingest_usgs_quakes.py`) |
| `beach_water_quality` | DRNA beach monitoring advisories (`data/hazard_records.jsonl`, weekly) |
| `access_closures` | USDA Forest Service El Yunque access orders (`data/access_conditions.jsonl`) |

## Reference bindings

`scripts/freeze_outdoor_reference.py` writes `data/reference/outdoor_reference.v1.json`
from public sources, with the SHA-256 of each response it used. Rerun it only when a
binding needs revisiting (NWS re-zones, Census publishes a new relationship file).

| Section | Built from | Binding |
|---|---|---|
| `marine_zones` | `api.weather.gov/zones?type=marine&area=AM` (`cwa == SJU`) | municipio polygon within 2 km of the zone polygon |
| `gridpoints` | `api.weather.gov/points/{lat},{lon}` | NWS grid cell holding the Census internal point |
| `forecast_zones` | `api.weather.gov/zones/forecast/{zone}` | zone names, because NWS land alerts name zones, not municipios |
| `uv_zips` | Census 2020 ZCTA–county relationship file | largest-land-area ZCTA in the municipio that EPA's UV service answers for |
| `access_assets` | `data/reference/el_yunque_access_assets.json` (USDA FS geometry) | certified asset geometry intersects the municipio |

An El Yunque asset whose stored geometry does not hash to its own `geometry_wkb_sha256`
(Baño de Oro Trail, when this was written) is skipped and listed under
`unresolved_material`; a closure on it stays unbound.

## How each component is bound

Every component records its `evidence_class` and `binding_method`:

| Component | Evidence | How |
|---|---|---|
| `rip_current` | `AUTHORITATIVE_BINDING` | the product names the beaches' municipios ("Including the beaches of …"); Culebra and Vieques bind by zone name |
| `marine_alerts` | `PROXIMITY` | the alert's marine zones, and the municipios within 2 km of them |
| `sea_state` | `PROXIMITY` | nearest buoy within 40 km of a coastal municipio's internal point, distance recorded |
| `uv` | `AUTHORITATIVE_BINDING` | EPA's own CITY for the ZIP names the municipio; otherwise `UNRESOLVED` |
| `heat` | `POINT_IN_POLYGON` | the grid cell at the Census internal point (`REPRESENTATIVE_POINT`) |
| `air_quality` | `PROXIMITY` | nearest AirNow reporting area within 40 km |
| `beach_water_quality` | `AUTHORITATIVE_BINDING` | DRNA's municipio text for the beach |
| `nws_alerts` | `AUTHORITATIVE_BINDING` | `areaDesc` names the municipio, or the forecast zone holding its internal point |
| `access_closures` | `CERTIFIED_GEOMETRY` | certified USDA FS asset geometry |

A coastal municipio that the Surf Zone Forecast never names (Loíza, Cataño, Mayagüez and
others, when this was written) is `NOT_COVERED` for rip current risk; it is never given
a neighbour's forecast.

## States, never "safe"

Each component has a `state`:

| State | Meaning |
|---|---|
| `REPORTED` | the source has a current value for this municipio |
| `NONE_ACTIVE` | an alert-type source is current and lists nothing here — not a finding that conditions are benign |
| `STALE` | the newest value is too old for the component; it is still shown |
| `NOT_COVERED` | the source does not cover this municipio (inland, no beaches named, no gauge, nothing within range) |
| `NOT_INGESTED` | the input is absent from this checkout and nothing could be carried |
| `NOT_CONFIGURED` | the source needs a credential that is not configured |
| `SOURCE_FAILED` | the source has failed and never succeeded |

When an input file is absent from a run (the DRNA and El Yunque inputs come from other
jobs), the previous composition's component is carried forward, marked
`carried_forward` with `carried_from`. A UV or heat request that fails for one municipio
likewise keeps its previous value, marked at the source.

The row's `summary.level` is `ELEVATED`, `CAUTION`, `NO_DRIVER_REPORTED` or
`INSUFFICIENT_DATA`, from published categories only, and only from `REPORTED`
components:

| Component | `ELEVATED` | `CAUTION` |
|---|---|---|
| rip current (today) | High | Moderate |
| marine alerts | any active | — |
| beach water quality | any DRNA advisory | — |
| heat (24 h, NWS heat-index chart) | Danger, Extreme Danger | Extreme Caution |
| UV (EPA scale) | Extreme | High, Very High |
| air quality (EPA AQI) | Unhealthy or worse | Unhealthy for Sensitive Groups |
| river flood (NWS category) | minor, moderate, major | action |
| rainfall (Stage IV) | any cell ≥ 6 in | municipio mean ≥ 3 in |
| NWS land alerts | a Warning | an Advisory, Watch or Statement |
| tropical cyclone | within 500 km | in the approach corridor |
| earthquakes | — | M4.5+ within 50 km |
| El Yunque access | — | any order in force |

Buoy readings drive nothing: no official threshold exists for them.

## Alerts

Only official NWS products promote, in `src/aguayluz/alert_promotion/outdoor.py`
(`WEATHER_HAZARD`, see [`ALERT_SYSTEM.md`](ALERT_SYSTEM.md)): rip current risk **High**
(severity 3) and marine-zone alerts for Puerto Rico waters (2 for advisories and
watches, 3 for warnings). Both stay below the push/SMS floor (4). UV, gridded heat,
buoys and AQI raise no alert; an NWS Heat Advisory already arrives through
`scripts/ingest_nws_alerts.py`.

## Files

| Artifact | Where |
|---|---|
| Composer | `src/aguayluz/outdoor/compose.py` |
| Ingest harness | `src/aguayluz/outdoor/runner.py` |
| CLI | `scripts/build_outdoor_conditions.py` (run by `scripts/refresh.py` in every cadence, before the derived alert layers) |
| Row schema | `schemas/outdoor_condition.v1.schema.json` |
| Per-source state | `data/outdoor_{surf,buoy,uv,heat,aqi}_state.jsonl` |
| Composed layer | `data/outdoor_conditions.jsonl` (a row keeps its `composed_at` until its content changes) |
| Federation export | `outdoor_condition` entities, `located_in` their municipio, components in `attributes` (`scripts/federation_export.py`) |
| Tests | `tests/test_ingest_outdoor_sources.py`, `tests/test_hazard_adapters_outdoor.py`, `tests/test_outdoor_compose.py`, `tests/test_alert_promotion_outdoor.py` |

## Known limits

- UV is one ZIP's daily maximum standing for the municipio; heat is one 2.5 km grid cell.
- Five buoys; two of them (41115, 41121) are wave-only, and the others often report wind
  without waves. A missing reading (`MM`) is `null`, never calm.
- The Surf Zone Forecast covers the beaches it names, not every coastal municipio.
- The heat-index bands are the national chart, not WFO San Juan's advisory criteria.
- AirNow data are preliminary and unvalidated, and the ingest is untested against a live
  response until the key exists.
