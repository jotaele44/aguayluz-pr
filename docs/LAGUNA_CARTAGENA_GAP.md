# Laguna Cartagena basin — what USGS actually publishes

A data-availability investigation of the three USGS monitoring sites in the Laguna
Cartagena basin (Lajas / Boquerón, southwestern Puerto Rico), prompted by a data-request
letter to the USGS Waterdata support team.

Every claim below was verified against the live APIs on **2026-08-02**; the endpoint that
produced each one is cited.

## The headline

The request letter asked whether records exist that are *not published* — aquifer
assignment, lab chemistry, method metadata, instrumentation logs. The answer the data
gives is different, and more useful: **the records that exist are published. The
monitoring itself lapsed decades ago.**

This is not an access problem to escalate. It is a coverage gap to document.

## Site by site

| Site | Type | Published record | In this corpus |
|---|---|---|---|
| `50129899` Laguna Cartagena | lake | 33 discrete water-quality series. One sampling campaign, 2011-11 → 2012-08. **No daily values.** | `USGS_50129899` (reservoir) |
| `50129900` Outflow | stream | Discharge daily values **1984-06-05 → 1985-11-12, 518 points**, then nothing for 40 years. Plus 36 discrete WQ series from the same 2011-12 campaign. | `USGS_50129900` (stream_gage) |
| `180046067053700` Laguna Cartagena Well | well | 4 series, all one-off: water level (`62610`, `72019`) 1985-08-19; specific conductance (`00095`) 1986-03-25. **Zero daily values.** | `USGSWQ_180046067053700` (chemistry, `needs_review`) and `USGSFM_180046067053700` (water levels) |

Sources: `waterservices.usgs.gov/nwis/site/?seriesCatalogOutput=true` for the series
inventory; `waterservices.usgs.gov/nwis/dv/` for the discharge record;
`api.waterdata.usgs.gov/samples-data/results/narrow` for the sample results;
`api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements` for the water levels.

The well was measured twice, forty years ago. That is consistent with the letter's own
closing hypothesis — that it may never have been fully activated beyond construction.

## Why the well was invisible to this producer

Not an oversight, and worth stating plainly because it looks like one.

`scripts/ingest_usgs_groundwater.py` deliberately keeps only wells that carry a time
series:

```python
# Keep only wells that actually carry a time series — an aquifer monitor cares about
# the monitored subset, not every historical one-off measurement site.
monitored = {r["site_no"] for r in readings}
```

That rule takes **5,437** Puerto Rico groundwater sites down to **36** assets, and it is
correct: an aquifer monitor should not carry thousands of sites that publish nothing.
The well *is* returned by the NWIS query that script makes — it is filtered out
afterwards, because it has no daily values.

So the fix was not to special-case the well past the rule. It was to give it real
readings, via the discrete-sample API the rule never looked at. The well now satisfies
the existing invariant without weakening it.

### …and why it needed its own id prefix

`ingest_usgs_groundwater.merge_assets` replaces **every** `USGSGW_*` row on each run and
regenerates only wells with a daily-values series. Parking a discrete-sample well under
that prefix meant the next daily refresh silently deleted it — that ingest runs daily,
this one did not. Caught in review before it shipped.

The repo had already solved this exact class of bug once, with a prefix. From
`ingest_usgs_groundwater.py`'s own docstring:

> Groundwater `asset_id` uses the `USGSGW_` prefix (NOT `USGS_`) so the surface-water
> `ingest_usgs_water` merge — which replaces every `USGS_*` row — never wipes these wells.

Same fix, one layer out: sample-derived assets use **`USGSWQ_`**, so the namespaces are
disjoint and no ordering between cadences can clobber either. A regression test asserts
the well survives a groundwater run.

## The retrieval path moved

`waterservices.usgs.gov/nwis/gwlevels/` now returns **HTTP 301** to a decommissioning
notice. The warning already carried in `ingest_usgs_groundwater.py`'s docstring — "the
legacy `/nwis/gwlevels/` service is being decommissioned" — is now current fact rather
than a caution.

The replacement is **`api.waterdata.usgs.gov/samples-data`**, keyless, HTTP 200. That is
what `scripts/ingest_usgs_samples.py` reads.

samples-data serves the *chemistry*, not the water levels. It returns exactly **one row**
for the well — the 1986 specific conductance, 2350 µS/cm.

### Correction, 2026-08-02: the water levels are retrievable after all

An earlier version of this document said the 1985 water-level measurements "appear only in
the site series catalogue and are not retrievable through the new API." **That was wrong,
and it was wrong in a specific way worth naming:** samples-data is one of ~36 collections
on `api.waterdata.usgs.gov`, and it is not the one that replaced `gwlevels`. Discrete
field measurements moved to the OGC API's `field-measurements` collection. Checking a
single successor service and generalising from it is what produced the error.

```
GET api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items
    ?monitoring_location_id=USGS-180046067053700&f=json
```

returns both records, keyless:

| pcode | value | datum | date | approval | qualifier |
|---|---|---|---|---|---|
| `62610` groundwater level above NGVD29 | 31.50 ft | NGVD29 | 1985-08-19 | Approved | `Above`, `Pumping` |
| `72019` depth to water below land surface | 11.20 ft | Local Assumed Datum | 1985-08-19 | Approved | `Above`, `Pumping` |

Both are now ingested by `scripts/ingest_usgs_field_measurements.py` as
`groundwater_level` readings against `USGSFM_180046067053700`. Both carry
`review_status: needs_review` — the `Pumping` qualifier means the level was measured while
the well was drawing, which is drawdown at the pump, not a static water table.

The correction is larger than one well. That collection holds **4,392 measurements across
82 PR wells** in the last ten years, against the 36 wells
`scripts/ingest_usgs_groundwater.py` can see — it reads the Daily Values service, so a
well without a continuous series is invisible to it no matter how recently it was
measured. 48 of those 82 wells were absent from this corpus entirely.

## What the ingest actually recovered

`scripts/ingest_usgs_samples.py`, run live against all three sites: **187 sample results
parsed, 120 stored.**

- 59 for the lake, 60 for the outflow, 1 for the well.
- Characteristics include nutrients (nitrate, nitrite, ammonia, phosphorus), faecal
  indicator bacteria (*Enterococcus*, faecal coliform), metals (arsenic, lead, mercury,
  zinc), and field parameters (conductance, dissolved oxygen, pH, turbidity, salinity).
- Units come from the API's own `Result_MeasureUnit` per row, so nothing is inferred.

**67 results were deliberately not stored**, and the run reports the count rather than
swallowing it:

- **41 non-detects.** `Not Detected` means below the detection limit, which is not zero.
  Storing it as zero would fabricate a measurement.
- Results with a **blank unit**. `monitoring_reading.unit` requires a non-empty string,
  and inventing one would mislabel the value.

The remainder are rows without a usable date.

## Where these readings surface

They reach the PRII hub through the canonical federation export —
`scripts/federation_export.py` globs `data/*_readings.jsonl`, so no exporter change was
needed, and `monitoring_readings` went from 0 to 120. Per ADR 0001 that export is this
producer's supported product surface; the dashboard in this repo is diagnostic-only.

They are **not** selectable on that diagnostic dashboard. `server/backend/app.py`'s
`READING_VECTOR_REGISTRY` has no `usgs_samples` vector and `monitoring_quality.py`'s
`SERIES_METADATA_REGISTRY` has no `water_quality` entry, so `GET /readings?kind=usgs_samples`
would be rejected. Wiring that up means touching the vector registry, the series-metadata
registry and `dashboard/src/lib/monitoring.js`, which is frontend work deliberately out of
scope here — tracked as a follow-up rather than claimed as done.

## What this does not tell you

- Whether unpublished records exist in USGS internal systems. The APIs can only show
  what is published; the letter's questions about lithological logs, instrumentation
  records and site schematics are not answerable from here.
- Anything about *why* monitoring stopped. The record shows when, not why.

## The aquifer assignment: answered, and the answer is "none"

The letter asked specifically for the well's aquifer assignment. An earlier version of
this document recorded it as "absent from both the site service and samples-data," which
left open whether USGS holds one and does not expose it.

The OGC `monitoring-locations` collection settles it. USGS **publishes** the field and
leaves it empty:

```
GET api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items
    ?id=USGS-180046067053700&f=json
→ aquifer_code: null, national_aquifer_code: null, aquifer_type_code: null,
  well_constructed_depth: null, hole_constructed_depth: null, construction_date: null
→ altitude: 42.7 ft (NGVD29), hydrologic_unit_code: 21010003, county: Lajas
```

So the site is georeferenced and assigned to a hydrologic unit, but has **no aquifer
assignment, no constructed depth and no construction date** in the published record. That
is consistent with the letter's own closing hypothesis that the well was never fully
activated beyond construction — and it means the question is answered rather than blocked:
there is nothing to release.

For contrast, this is not a gap in USGS's schema. Wells that *are* assigned come back
populated — `175711066143600` (Piezómetro JBNERR East 1, Salinas) carries
`aquifer_code: 110SCPL` and `well_constructed_depth: 74.0`. `ingest_usgs_field_measurements.py`
records either outcome verbatim in the asset's `source_ref`, so an empty assignment reads
as a finding rather than as missing data.

## Related

- `docs/NEON_INTEGRATION.md` — NEON's `LAJA` and `GUAN` sites sit in the same corner of
  the island and do carry current data, including groundwater chemistry at `GUIL`.
- `scripts/ingest_usgs_groundwater.py` — the daily-values groundwater ingest whose
  scoping rule is discussed above.
- `scripts/ingest_usgs_field_measurements.py` — the discrete-measurement ingest added by
  the correction above; it recovers the well's water levels and 82 PR wells besides.
- `scripts/ingest_usgs_samples.py` — the discrete-chemistry ingest that recovered the
  basin's 2011-12 sampling campaign.
