# USGS water-use estimates: public supply by source (2010 / 2015 / 2020)

## Why

The repository already tracked the south-coast aquifer in detail: five observation wells
against their PRDNER condition bands ([`AQUIFER_BANDS_INTEGRATION.md`](AQUIFER_BANDS_INTEGRATION.md)),
USGS groundwater levels, and drought. It held nothing on the question those wells are usually
raised to answer: **how much of Puerto Rico's public water supply comes from groundwater at
all?**

A research report supplied to the project put that share at about 11% and total public-supply
withdrawals at 500–600 million gallons per day (Mgal/d). Its headline was right, but it
contradicted itself on 2010 (677 and 724 Mgal/d; groundwater 71 and 118) and named a well that
does not exist under that name. This change ingests the U.S. Geological Survey figures the
report was drawing on, from the publications themselves, so the numbers can be read off a
pinned source instead of a secondary summary.

## The sources

All three are U.S. Geological Survey, Caribbean-Florida Water Science Center, and are listed
with their hashes in `config/usgs_water_use_sources.v1.json`.

| Data year | Publication | What is read | Format | Evidence tier |
|---|---|---|---|---|
| 2020 | Data release [10.5066/P9HWON2W](https://doi.org/10.5066/P9HWON2W), "Estimated public-supply water withdrawals and domestic water use in Puerto Rico" (ver. 2.0, March 2023) | Table 1: public supply by source and municipality | xlsx | **T1** |
| 2015 | Data release [10.5066/P9POVNC6](https://doi.org/10.5066/P9POVNC6), "Spatial and tabular datasets of water withdrawals and use in Puerto Rico, 2015" | Table 4 (by category), Table 6 (public supply by municipality), Table 9 (irrigation by municipality), Table 14 (trends 1990–2015) | xlsx | **T1** |
| 2010 | Molina-Rivera, 2014, Open-File Report 2014-1117, [10.3133/ofr20141117](https://doi.org/10.3133/ofr20141117) | Table 8 and the body text | **PDF only** | **T2**: manual transcription |

The xlsx files are committed byte-identical under `tests/fixtures/usgs_water_use/`; each one's
SHA-256 is pinned, and a live run also checks ScienceBase's own MD5. The 2010 report has no
data release, so its island totals were transcribed by hand, with the page and table recorded
for each value, and bound to the PDF's SHA-256
(`39f78c12387c71bfcf800d120c38856f84d7604f8723b1f737a6c3b475f77b8c`). The PDF (12 MB) is not
committed and is never parsed by code. A transcription is one step further from the source
than a cell read by a parser, which is why it is T2 rather than T1.

## Figures as published

Public-supply withdrawals, PRASA and non-PRASA community systems together, in Mgal/d. Shares
are of surface water plus groundwater.

| Year | Surface water | Groundwater | Total | Surface | Groundwater | Tier |
|---|---|---|---|---|---|---|
| 2010 | 590 | 87 | 677.21 | 87.1% | 12.9% | T2 |
| 2015 | 509.78 | 66.62 | 576.40 | 88.4% | 11.6% | T1 |
| 2020 | 536.64 | 65.10 | 601.74 | 89.2% | 10.8% | T1 |

In 2020 PRASA withdrew 592.41 of the 601.74 Mgal/d (532.72 surface, 59.70 groundwater);
non-PRASA community systems withdrew 9.32.

For 2010 the report gives the total to two decimals in Table 8 and the split only in its text,
rounded to whole numbers ("677 Mgal/d (590 Mgal/d from surface-water and 87 Mgal/d from
groundwater facilities)"), which is why the two do not sum exactly.

## Report claim vs primary source

| Claim in the supplied report | Primary source | Verdict |
|---|---|---|
| 2010 public supply is "677" in one place and "724" in another | Public supply is 677.21 (OFR 2014-1117, Table 8). 723.75 is *total offstream freshwater withdrawals*, every category together | 724 is a different category |
| 2010 public supply is 606 surface + 118 groundwater | 606.14 and 117.61 are the split of total offstream freshwater. Public supply was 590 + 87 | Misattributed |
| 2010 groundwater is 71 Mgal/d (the report's Table 1) | Not found in the 2010 report | **Unresolved**; not ingested |
| 2015: 576 total, 88% surface / 12% groundwater | 576.40 = 509.78 + 66.62 | Correct |
| 2020: 602 total, 537 surface (89%), 65 groundwater (11%) | 601.74 = 536.64 + 65.10 | Correct |
| Groundwater levels fell 40 ft in Salinas and 11 ft in Guayama (Torres-González and Rodríguez), described as a 2010–2015 result | OFR 2015-1215 ([10.3133/ofr20151215](https://doi.org/10.3133/ofr20151215)) covers 2010–15, but states those declines occurred "during 2012–14" | Magnitudes correct; the window is 2012–14 |
| Irrigation groundwater withdrawals rose from 6.0 to 10.5 Mgal/d, 2010 to 2012 | Same report, same figures | Correct (south-coast aquifer only; not ingested) |
| Four sentinel wells, one named "Rosas" | The USGS page lists five wells; the Salinas piezometer is **Rasa D**, site `175910066155500` | Corrected; see the aquifer bands doc |
| PRASA produced 513 Mgal/d in fiscal year 2024, about 88% from filtration plants | Not checked against a PRASA document | **Unverified**; cited as context only, not ingested |

One thing the report did not mention: the 2015 release's trends table restates 2010 public
supply as **670** Mgal/d, against 677.21 in the 2010 report, and 2010 total freshwater as
728.23 against 723.75. The pages read give no reason. Both values are stored, as separate
rows, and the dashboard shows both without offering an explanation.

## What was wired

| Piece | Path |
|---|---|
| Source registry: DOIs, file names, MD5 and SHA-256 pins, the 2010 transcription | `config/usgs_water_use_sources.v1.json` |
| xlsx reader, table parsers, read-side summaries (stdlib only) | `src/aguayluz/water_use.py` |
| Producer | `scripts/ingest_usgs_water_use.py` |
| Estimates: 207 rows, rewritten deterministically on each run | `data/water_use_estimates.jsonl` |
| Receipt: latest attempt and latest success | `data/water_use_receipt.json` |
| Contracts | `schemas/water-use/v1/water_use_estimate.schema.json`, `water_use_receipt.schema.json` |
| Source files, byte-identical | `tests/fixtures/usgs_water_use/` |
| Read-only API | `server/backend/water_use_api.py`: `GET /water-use/estimates` |
| Dashboard | **Water Use** page (`/water-use`, under Water & Weather): `dashboard/src/pages/WaterUsePage.jsx`, `dashboard/src/lib/water-use-api.js`, `dashboard/src/lib/water-use-hooks.js` |
| GUI-parity capability | `usgs-water-use-estimates` in `.federation/gui-capabilities.json` |
| Tests | `tests/test_water_use.py`, `tests/test_ingest_usgs_water_use.py`, `tests/test_water_use_api.py`, `dashboard/src/pages/WaterUsePage.test.jsx`, `dashboard/src/lib/water-use-api.test.js`, `dashboard/tests/water-use.spec.mjs` |

The 207 rows are: public supply island-wide for each year, with the PRASA and non-PRASA split
for 2015 and 2020; public supply for all 78 municipalities in 2015 and 2020; the eight
freshwater categories for 2015; irrigation for the 32 municipalities that had any in 2015; the
2010 values of three categories as restated in 2015; and three transcribed 2010 values.

The two `data/` files are committed on purpose (see `.gitignore`). The releases are static, so
the producer runs **on demand** and is not part of `scripts/refresh.py`; and the GUI-parity job
boots the backend with no network, so the page needs the rows in the tree. Raw bytes are also
kept under `data/water_use_snapshots/` (gitignored) on each run.

## The page

`GET /water-use/estimates` serves the committed rows and computes shares per request. There is
no write path and no refresh button: re-downloading a five-yearly publication on demand would
add failure modes without adding evidence. The controls are **Retry** after a failed load and a
year toggle on the municipality table.

The page shows public supply by source for each year, with the share as a bar whose text
alternative carries the same numbers; each year's evidence tier and whether it was read from a
table or transcribed; the 2010 restatement; all freshwater categories for 2015, with a note
that the total row's split is not the public-supply split; public supply by municipality of
intake, largest groundwater withdrawal first; and every source with its DOI and pinned hash. It
links to **Aquifer Bands**, which links back.

States that are rendered rather than left blank: loading; request failure with a retry; no
estimates loaded; a year whose split by source was not published (text, no bar); and a failed
latest run, which keeps showing the last verified figures.

## Rules that are easy to get wrong

* **Public supply is one category; total freshwater is all of them.** In 2010 the two are
  677.21 and 723.75 Mgal/d and their groundwater shares are 12.9% and 16.3%. Quoting the second
  as the first is the error the supplied report made. Both are stored and labelled.
* **Bind columns by header text.** The 2015 tables list groundwater before surface water; the
  2020 table lists surface water first. A positional reader swaps the sources for one year.
* **Withdrawals are counted where the intake is.** San Juan withdrew 0.00 Mgal/d in 2010. The
  municipality table is a map of intakes, not of consumption.
* **Irrigation totals include reclaimed water.** The 2015 municipality table's total is surface
  + groundwater + reuse (79.11 island-wide); the category table's irrigation withdrawal is
  77.58. Reuse is kept in its own field and the municipality table's total row is used only to
  check the rows above it.
* **A changed file stops the run.** A file whose SHA-256 differs from the pin fails, writes a
  FAIL receipt and leaves the estimates untouched, because a release that changed needs a
  person to look at it. `--accept-new-bytes` lets the run proceed and records the new hash; the
  pin is still edited by hand.
* **A figure two tables both publish must agree.** 2015 public supply is in Tables 4 and 6;
  the run fails if they differ and records the agreement if they do not.
* **Never infer.** 2010 irrigation is a total only; its split is `null`. Shares are computed at
  read time and never stored.

## What this does not do

* **No current figures.** Nothing here is newer than 2020. This is not PRASA's production
  today, and the page says so.
* **No PRASA ingest.** PRASA's own reports were not acquired. The 513 Mgal/d figure is
  unverified context.
* **No alerts.** These are historical estimates.
* **No 2010 by-municipality rows.** They exist in the 2010 report (its Table 1) but would be
  78 hand-transcribed rows.
* **No 2020 irrigation or other categories.** The 2020 release covers public supply and
  domestic use only.
* **No hub export.** The estimates do not reach the PRII hub; that would extend the federation
  contract.
* **Not on a schedule.** Run it when USGS publishes the 2025 compilation.

## Blind spots

* **Why USGS restated 2010** (677.21 to 670) is not explained in the pages read.
* **The report's "71 Mgal/d" for 2010 groundwater** was not located in any source.
* **Estimates, not meter readings.** USGS compiles them from data PRASA and the Department of
  Health supply; the 2020 table notes the raw data "are not available online". The method's
  uncertainty is not published as a number.
* **The 2010 values depend on one person's reading of a PDF.** They are bound to the file's
  hash, so anyone can re-read pages 14 and 39, but no parser checks them.
* **A five-year step hides droughts.** 2015 was a drought year and 2020 was not; a change
  between them is not a trend.

## Lead

A public-records request to PRASA (AAA) for monthly production by source and by facility would
give current, sub-annual figures and a primary record for the 513 Mgal/d claim. The chance it
returns per-facility monthly data is an analyst estimate of roughly 40–55%, not a measured base
rate: PRASA supplied such data to USGS for the 2020 compilation, but it is not published.

## Verifying a change

```bash
python -m pytest -q tests/test_water_use.py tests/test_ingest_usgs_water_use.py tests/test_water_use_api.py
python scripts/ingest_usgs_water_use.py --dry-run           # offline, from the fixtures; writes nothing
python scripts/ingest_usgs_water_use.py --fetch --dry-run   # live: MD5 and SHA-256 against ScienceBase
python scripts/check_gui_parity.py                          # the ratchet must report new=0
cd dashboard && npx vitest run src/pages/WaterUsePage.test.jsx src/lib/water-use-api.test.js
```
