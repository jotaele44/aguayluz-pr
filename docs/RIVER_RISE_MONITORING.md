# River rise monitoring (USGS rate of rise)

AguaYLuz grades how fast every Puerto Rico stream gauge is rising, every refresh, from
USGS instantaneous values. A sudden rise is the first sign of a flash flood that a gauge
can show, and it shows at gauges NWS has never given flood thresholds.

This is detection of an **observed** rise. It is not a forecast and not an NWS warning.

## Why

Before this, AguaYLuz raised a river alert only when NWPS reported a flood *category*
(`_nwpsflood_`, [`NWS_HYDROMET_INTEGRATION.md`](NWS_HYDROMET_INTEGRATION.md)). That has two
gaps:

- **Rate isn't measured.** A river can climb from base flow to action stage within an hour,
  and the category changes only when the threshold is crossed.
- **Many gauges have no thresholds.** 34 of the 118 NWPS gauges report `not_defined`, so they
  can never raise a flood alert.

No sub-daily stage history survived between the 15-minute refresh runs:
`data/nwps_gauge_state.jsonl` keeps one value per gauge, and the USGS readings files are
gitignored. Each run therefore reads its own 6-hour window.

## Source

| Item | Value |
|---|---|
| Endpoint | `GET https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items` |
| Query | PR bounding box, `parameter_code` 00065 (gage height, ft) then 00060 (discharge, ft³/s), `datetime` = last 6 h, `skipGeometry=true`, a `properties` list, `limit=10000`; a `next` link is followed |
| Registry | `config/hydromet_sources.v1.json` → `usgs_river_rise` |
| Ingest | `scripts/ingest_usgs_river_rise.py` (`--src`, `--data-dir`, `--now`, `--assets`, `--thresholds`, `--history-hours`, `--dry-run`) |
| Detector | `src/aguayluz/hazard_adapters/river_rise.py` (pure, stdlib + hazard plane) |
| Thresholds | `config/river_rise_thresholds.v1.json` |
| Schedule | every `scripts/refresh.py` cadence, optional, right after the NWPS gauges |
| Key | none; `USGS_API_KEY` (sent as `X-Api-Key`, never stored) raises the rate limit |

**Latency.** PR gauges relay over GOES satellite about once an hour, so readings arrive in
bursts of four 15-minute values. In a live probe on 2026-11-26, readings were 44 minutes
old at the median and 74 minutes at the 90th percentile. Add up to 15 minutes for the
cron and 5 minutes of dashboard polling. Every state row carries its own
`latency_minutes`.

**Rate limit.** Anonymous requests share a limit of 1,000 per hour per IP address. This
ingest makes 2 requests per run, about 192 a day.

## Method

Every feature is classified before anything is computed, and
`retained + excluded + unresolved` must equal the feature count or the run fails closed:

| Outcome | When |
|---|---|
| retained | instantaneous (`statistic_id` 00011) stage or discharge at a stream gauge |
| excluded | reservoir, lake or canal site (`utility_assets.asset_subtype` ≠ `stream_gage`); other parameter or statistic; a value USGS withholds and qualifies (e.g. `RATINGDEV`); an excluded qualifier (equipment, maintenance, backwater, ice, discontinued, seasonal); duplicate timestamp; a second time series for the same site and parameter; an interior spike |
| unresolved | no site, no time, no value, or a value that is not a number |

Per stream site, over the 6-hour window:

- **Lookup by time.** Gauges report every 5, 10 or 15 minutes. A value "1 hour ago" is the
  last reading in the 10 minutes up to that time, never "four readings back".
- **Rises.** Δ15 min, Δ1 h and Δ3 h, plus the least-squares rate over the last hour (at
  least 3 readings).
- **Spikes.** An interior reading more than 1 ft away from two neighbours that agree with
  each other is dropped. A newest reading that jumps more than 1 ft with less than 0.25 ft
  of rise in the half hour before it is `PENDING_CONFIRMATION`: the class is capped at
  ELEVATED for that run.
- **Discharge ratio.** Q now / Q minimum over 6 h, used only when the minimum is at least
  5 ft³/s and the rise at least 100 ft³/s. Discharge is computed from the same stage sensor
  through a rating curve, so it is never independent evidence. At FLASH it also needs an
  elevated stage rise.
- **NWPS datum check.** A site bound to an NWPS gauge (by `usgsId`) uses that gauge's
  thresholds only when the NWPS stage equals the USGS reading, within 0.1 ft, at a common
  timestamp. Otherwise the result is `FAIL` or `NO_COMMON_TIME`, and no NWPS threshold is
  used.
- **Headroom.** A big river whose action stage sits 15 ft above base flow can rise 2 ft in an
  hour without flooding. With a passing datum check, each class's stage thresholds are scaled
  by `fraction × (action stage − 6-hour minimum) / base 1-hour threshold`, clamped to
  `[1, 3]`. A site just below action stage never gets a hair trigger; the projection covers
  it instead.
- **Projection.** Minutes to NWPS action and minor stage at the current rate, only with a
  passing datum check, out to 180 minutes; 0 once the stage is already above.

**Classes** (defaults, pending calibration; any one criterion is enough):

| Class | Δ15 min | Δ1 h | Δ3 h | Q ratio |
|---|---|---|---|---|
| ELEVATED_RISE | — | ≥ 1 ft | ≥ 2 ft | ≥ 3 |
| RAPID_RISE | ≥ 0.75 ft | ≥ 2 ft | ≥ 4 ft | — |
| FLASH_RISE | ≥ 1.5 ft | ≥ 4 ft | — | ≥ 5 with Δ1 h ≥ 1 ft |

**Data states.** Only `OK` and `PENDING_CONFIRMATION` can open an episode.

| State | Meaning |
|---|---|
| `OK` | fresh, enough readings |
| `PENDING_CONFIRMATION` | newest reading jumped without a prior rise |
| `STALE` | newest reading older than 150 minutes |
| `INSUFFICIENT` | fewer than 3 readings in the last hour, or no reading 1 h back |
| `NO_STAGE` | no stage series |
| `SUPPRESSED` | the site is suppressed in the thresholds config |

Per-site overrides in `config/river_rise_thresholds.v1.json` take a `scale`, a `suppress`
flag and a `note`. 50059050, below the Carraizo dam, carries a note because gate and
spillway releases raise its stage without rain.

## Episodes

A RAPID or FLASH rise opens one canonical event, `USGS_RISE:<site>:<onset>`. The onset is
the last base-level reading before the climb.

- A revision is written only when the peak class escalates, the minor-stage projection first
  fires (within 60 minutes, sticky), or the episode closes. The current class moves every
  run (RAPID ↔ FLASH during a storm) and stays in the state file.
- An episode closes once 90 minutes of observation time pass with no class and less than
  0.1 ft of rise in the last hour. A new rise resets that clock. A site with no fresh data
  holds its episode open, then closes it after 24 hours with `closed_reason=stale`.
- A new rise after a closed episode gets an onset after that episode's end.
- Closed episodes are pruned 35 days after they end, longer than the 30 days for which alerts
  report closed episodes.

## Files

| File | Committed | Content |
|---|---|---|
| `data/river_rise_state.jsonl` | yes | one row per stream site, rewritten every run: binding, NWPS link, latest reading, latency, data state, metrics, projection, class, thresholds applied, the open episode and its quiet clock, and a 25-point 15-minute grid of stage and discharge |
| `data/hydromet_records.jsonl` | yes | `USGS_RISE:` episode revisions (`RIVER_STAGE_RATE_OF_RISE`, provisional); opening and closing revisions embed the series |
| `data/hydromet_relationships.jsonl` | yes | `SAME_LOCATION → USGS_<site>` (STABLE_ID) and `SPATIALLY_INTERSECTS → <GEOID>` per revision |
| `data/hydromet_manifestations.jsonl`, `data/hydromet_receipts.json` | yes | byte SHA-256 of each response; the run receipt (arithmetic, latency p50/p90, classes, episode actions) |
| `data/hydromet_snapshots/usgs_river_rise/` | no | raw response bytes, pruned each run to the responses still referenced |

Municipio binding uses point-in-polygon on the asset coordinates, corroborated by the
asset's NWIS municipality. A disagreement stays `UNRESOLVED`.

## Calibration

`scripts/calibrate_river_rise.py` replays the live detector over historical USGS readings
as if it ran every 15 minutes, each run seeing only readings at least 45 minutes old. It
scores three kinds of window:

| Window | What is measured |
|---|---|
| Storms (Fiona 2022, María 2017) | NWPS action-stage crossings at same-datum gauges, classed by what was observable before the crossing reading: `rising_limb` (the hour before already rose ≥ 1 ft), `step` (the crossing reading is the first anomaly, so nothing on the same feed can precede NWPS), `gradual`, `no_data`. A hit is an episode open by the first 15-minute run that could see the crossing, which is when the NWPS category changes. |
| NWS Flash Flood Warnings (from `data/service_events.jsonl`) | whether a stream gauge in a warned municipio opened an episode during the warning |
| Dry-season fortnights (February and March 2026) | rapid/flash episodes per gauge per 30 days, each labelled by the NWS flood products around it (`--nws-products`): one for the gauge's own municipio (`local`), only elsewhere on the island within ±6 h (`island`, a rain day), or none (`none`) |

"Dry season" is not "no rain": NWS San Juan issued 21 flood products between 1 and 19
February 2026, including Flash Flood Warnings on 2 and 15 February. The labels come from the
Iowa Environmental Mesonet archive of NWS VTEC events
(`https://mesonet.agron.iastate.edu/json/vtec_events.py?wfo=TJSJ&year=2026`, T4 aggregation of
T1 NWS products), used only to label the backtest.

Promotion is enabled only when:

- at least 5 rising-limb storm crossings are labelled;
- at least 80% of them are hits;
- at most 0.5 dry-season episodes per gauge per 30 days carry no NWS flood product anywhere
  (`none`).

Until the full run is recorded in `config/river_rise_thresholds.v1.json`, promotion stays off
(`promotion.enabled: false`). The state file and the dashboard show every class regardless.

## Limits and blind spots

- **About an hour behind.** Readings are 40–75 minutes old when they arrive, so the river may
  already have crested.
- **Provisional data.** USGS revises it later. A sensor fault that passes the spike guard can
  grade as a rise.
- **Dam releases** raise stage without rain (e.g. 50059050 below Carraizo).
- **Projection needs NWPS thresholds.** About 80 stream sites are read, and only those bound to
  an NWPS gauge with thresholds and a passing datum check get a projection.
- **No routing.** No upstream/downstream or watershed linkage is used, and nothing claims a
  rise reached an intake.
- **Burst arrival.** A rise that starts in the last reading of a burst may wait for the next
  burst to be confirmed.
