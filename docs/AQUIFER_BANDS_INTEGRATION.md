# PRDNER aquifer condition bands (south-coast observation wells)

AguaYLuz ingests the condition bands that a USGS page publishes for five continuously
recorded observation wells on the south-coast aquifer of Puerto Rico, so a depth-to-water
reading can be read as **Optimum / Observation / Operational Adjustment / Critical** rather
than only as a number or a percentile.

## Why

The only groundwater alert logic in the repo is a statistical proxy
(`src/aguayluz/water_alerts.py::aquifer_alerts`: a reading in the site's own deepest 10%),
plus a generic 50 ft operator default in `server/backend/monitoring_quality.py`. Neither
knows what PRDNER treats as a problem for a given well:

| Well | Hole depth | Critical onset | Where the generic 50 ft default would trip |
|---|---|---|---|
| Constancia 3 (Ponce) | 150 ft | 13.65 ft | 36.35 ft past Critical |
| Piezometer Jac-6 (Juana Díaz) | 49 ft | 26.9 ft | never: the hole is shallower than 50 ft |
| Alomar Oeste (Santa Isabel) | 70 ft | 17.4 ft | 32.6 ft past Critical |
| Piezometer Aguirre HW 5B (Salinas) | 52 ft | 23.43 ft | effectively never: only with the water at the bottom of the hole |
| Piezometer Rasa D (Salinas) | 87 ft | 51.55 ft | 1.55 ft before Critical |

The default is not calibrated to any of the five. Hole depths are those printed on the
source page (Alomar Oeste's well depth is "N/A" there).

On 2026-11-08 Aguirre HW 5B read 29.76 ft (provisional), 6.33 ft past its Critical onset,
and had been in the Critical band on 467 of the 676 days since 2025-01-01. Nothing in the
repo could say so before this source.

## The source

| | |
|---|---|
| Page | `https://pr.water.usgs.gov/drought/hydro_conditions_selected_wells.html` (USGS Caribbean-Florida Water Science Center) |
| Authority | Attributed on the page to the Puerto Rico Department of Natural and Environmental Resources (PRDNER). Not independently verified. |
| Evidence tier | **T2**: operational documentation published by USGS. No primary PRDNER record has been seen. |
| Published as | Hard-coded `ranges` and label ladders in the page's inline JavaScript, per well. No API, file or feed carries them. |
| Effective date | **Not published.** Stored as `null` with `effective_date_status = not_published_by_source`; never inferred from the capture date. |
| Depth convention | Feet below land surface, positive down (USGS parameter 72019). The page plots the same numbers negated. |

The extensionless URL (`…/hydro_conditions_selected_wells`) 301s to a generic Water Science
Center landing page. The producer requests the `.html` form with redirects **off**, so a
redirect is a failure rather than a different document that gets frozen.

### Bands as published (2026-11-08)

Depth below land surface in feet, `shallow <= depth < deep`.

| Well (site no.) | Above Optimum | Optimum | Observation | Operational Adjustment | Critical |
|---|---|---|---|---|---|
| Constancia 3, Ponce (175934066364800) | < 8.6 | 8.6 – 10.49 | 10.49 – 12.0 | 12.0 – 13.65 | ≥ 13.65 |
| Piezometer Jac-6, Juana Díaz (180057066311300) | < 18.9 | 18.9 – 22.02 | 22.02 – 25.38 | 25.38 – 26.9 | ≥ 26.9 |
| Alomar Oeste, Santa Isabel (175734066233300) | < 13.2 | 13.2 – 15.79 | 15.79 – 16.45 | 16.45 – 17.4 | ≥ 17.4 |
| Piezometer Aguirre HW 5B, Salinas (175947066130601) | < 12.25 | 12.25 – 16.54 | 16.54 – 21.42 | 21.42 – 23.43 | ≥ 23.43 |
| Piezometer Rasa D, Salinas (175910066155500) | < 31.6 | 31.6 – 38.2 | 38.2 – 45.6 | 45.6 – 51.55 | ≥ 51.55 |

The page's legend names four conditions (blue Optimum, yellow Observation, orange
Operational Adjustment, red Critical). The green band shallower than Optimum has **no legend
entry**, so it is stored as `above_optimum` and never given a PRDNER name.

How much of the island's public supply these aquifers and the others provide (10.8% from
groundwater in 2020) is covered separately in [`WATER_USE_INTEGRATION.md`](WATER_USE_INTEGRATION.md);
the Aquifer Bands page links to it.

## What was wired

| Piece | Path |
|---|---|
| Parser, classifier, registry and reading helpers (stdlib only) | `src/aguayluz/aquifer_bands.py` |
| Producer | `scripts/ingest_prdner_well_bands.py` |
| Registry: append-only revisions, one per material change | `data/aquifer_band_registry.jsonl` |
| Receipt: latest attempt and latest success | `data/aquifer_band_receipt.json` |
| Contracts | `schemas/aquifer-bands/v1/aquifer_band_registry.schema.json`, `aquifer_band_receipt.schema.json` |
| Schedule | `scripts/refresh.py::STEP_AQUIFER_BANDS` (weekly and `--all`, optional) |
| Read-only API | `server/backend/aquifer_api.py`: `GET /aquifer/bands` |
| Dashboard | **Aquifer Bands** page (`/aquifer-bands`, under Water & Weather; links to **Water Use**): `dashboard/src/pages/AquiferBandsPage.jsx`, `dashboard/src/lib/aquifer-api.js`, `dashboard/src/lib/aquifer-hooks.js` |
| GUI-parity capability | `aquifer-threshold-bands` in `.federation/gui-capabilities.json` |
| Tests | `tests/test_aquifer_bands.py`, `tests/test_ingest_prdner_well_bands.py`, `tests/test_aquifer_api.py`, `dashboard/src/pages/AquiferBandsPage.test.jsx`, `dashboard/src/lib/aquifer-api.test.js`, `dashboard/tests/aquifer-bands.spec.mjs` |

The two JSON(L) files are committed on purpose (see `.gitignore`): the registry is the
revision base each run diffs against, and the receipt is the only durable evidence the page
was read and parsed. The raw page bytes are kept under `data/aquifer_band_snapshots/`
(gitignored).

Readings are **not** re-ingested. The latest depth for each well comes from the existing
`data/usgs_continuous_readings.jsonl` (OGC `latest-continuous`, parameter 72019), falling
back to `data/groundwater_levels.jsonl` (daily values). Wells bind by stable id to their
`USGSGW_<site>` asset; the page's title only corroborates.

## The panel

`GET /aquifer/bands` derives everything per request from the committed registry and the latest
local reading, so there is no state file to go stale and no write path: the page has no
refresh button, because a control that scraped a third-party page on demand would add load and
failure modes without adding evidence. The only control is **Retry** after a failed load.

For each well the page shows the depth, the class **written out as text** (colour only
reinforces it), the margin to the Critical onset ("6.33 ft past Critical onset" / "4.57 ft before
Critical"), the reading's date with a **Provisional** or **Approved** badge, and the bands as a
bar whose text alternative lists every edge. A depth beyond the chart axis is still Critical and
its marker is clamped to the end of the bar. The source panel shows freshness
(FRESH / STALE / FAILED / NEVER, with the hydromet plane's meaning), the last read and attempt,
the fetched-bytes SHA-256, wells accounted, the in-source inconsistencies above, and the page's
own "Map and Info" links, labelled as recorded but not fetched.

States that are rendered rather than left blank: loading; request failure with a retry (never
shown as "no wells"); no bands registered yet (with the source panel still shown if a receipt
exists, so a page that never parsed says why); a well with **no local reading**, which keeps its
bands and claims no class; a stale reading (older than two days, at the day resolution readings
carry), which is flagged but still classified; and a STALE or FAILED source, which keeps showing
the last verified bands. A fresh checkout has the registry but no readings files (they are
gitignored and rebuilt by the refresh), so it shows the bands with no class until a refresh has
run.

## Rules that are easy to get wrong

* **Fail closed.** The thresholds are scraped from one page's JavaScript. The parser asserts
  exactly five charts of five contiguous, shallow-to-deep bands; the legend; the PRDNER
  attribution; that the page reads parameter 72019; that its request, label ladders and
  reference links name the same five wells; and that the two copies of each threshold agree
  to within rounding (0.011 ft). Anything else stops the run, writes a FAIL receipt, and
  leaves the registry untouched. The bytes of a page that failed to parse are still kept.
* **Two known source inconsistencies are recorded, not fatal.** Aguirre HW 5B's chart range
  ends Observation at 21.42 ft while its label ladder says 21.43 ft; Rasa D's label ladder has
  no rung for the shallow green band. The chart ranges are treated as authoritative.
* **Classification is total.** The page's own label ladders fall through for a depth beyond
  their last rung. Here a depth at or beyond the deepest edge is `critical`, a negative depth
  (flowing artesian well) is `above_optimum`, and NaN is rejected, never coerced.
* **72019 only.** A level *above* datum (62610) runs in the opposite direction and would
  invert every class, so a reading is accepted only when its parameter code is exactly
  `72019` and its unit is feet.
* **The raw byte hash is not a content identity.** The CDN injects a per-request script
  (`__CF$cv$params`, a ray id and a timestamp) into the page, so `source_byte_sha256`
  differs on every fetch of identical content. It records which bytes were seen. Whether
  the thresholds changed is decided by `material_digest`, a hash of the parsed classes and
  edges, and a registry revision is appended only when that changes.

## What this does not do

* **No alerts and no incidents.** Every current reading of these wells is provisional
  (the latest approved day per well is between 2026-03-31 and 2026-08-13), and the monitoring
  lifecycle ignores provisional rows by policy
  (`config/monitoring_site_thresholds.json`: `provisional_observations_can_change_lifecycle`
  is `false`). Band state is shown, not alerted on.
* **No entry in `config/monitoring_site_thresholds.json`.** That registry takes one scalar
  per metric and site and requires an `effective_date`, which this source does not publish.
  Revisit when PRDNER supplies a dated document.
* **No hub export.** Band state does not reach the PRII hub; that would extend the
  federation contract and needs its own proposal.
* **No scraping of the `AWLSites.asp` pages.** The page's "Map and Info" links
  (`groundwaterwatch.usgs.gov`) are recorded as `reference_url` and never fetched. They are
  views of the same wells and could not be read from the environment this was built in, so
  their content is unverified.

## Blind spots

* **No effective date, version or method.** Whether Aguirre HW 5B's persistent Critical state
  is chronic drawdown or thresholds set for different conditions cannot be told from the
  page. Its readings sat at 23.83 ft or deeper through the same window of 2025.
* **Provisional data.** USGS marks all of it subject to revision.
* **Weekly cadence.** A threshold edit can be seen up to a week late; the registry goes
  STALE after 14 days without a successful read.
* **Dependence on the asset set.** Each page well must exist as a `USGSGW_` asset, which
  `ingest_usgs_groundwater.py` keeps only while the well has a daily-value series. A well
  that lost its series fails the run (visible in the receipt) rather than being dropped
  silently.

## Lead

A public-records request to DRNA (PRDNER) for the threshold document, with its adoption date,
method and revision history, would convert this from T2 to a primary record and supply the
`effective_date` the monitoring registry requires. The chance it returns a dated document is
an analyst estimate of roughly 55–65%, not a measured base rate.

## Verifying a change

```bash
python -m pytest -q tests/test_aquifer_bands.py tests/test_ingest_prdner_well_bands.py tests/test_aquifer_api.py
python scripts/ingest_prdner_well_bands.py --dry-run    # live fetch, writes nothing
python scripts/check_gui_parity.py                      # the ratchet must report new=0
cd dashboard && npx vitest run src/pages/AquiferBandsPage.test.jsx src/lib/aquifer-api.test.js
```
