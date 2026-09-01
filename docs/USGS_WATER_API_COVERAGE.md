# USGS Water Data API Category Coverage

Status: **implemented on the current-main-derived branch; live operator verification pending
for the newly added modern API paths.**

This matrix distinguishes a provider being known to AguaYLuz from actual observation
ingestion. A category cannot be marked monitored merely because USGS is present in a
provider registry.

## Security and rate limits

`USGS_API_KEY` is read only at request time and sent as the `X-Api-Key` header. It is
never written to receipts, JSONL outputs, logs, fixtures, source files, workflow YAML,
or pull-request text. The ingesters also work keylessly at the lower public rate limit.

## Ten-category implementation

| Category | Producer | Cadence | Boundary |
|---|---|---|---|
| Continuous Values | `ingest_usgs_continuous.py` | fast/daily/weekly/all | Uses `latest-continuous` by default; bounded historical mode uses `continuous`. Parameter, site, unit, approval status, timestamp identity, and freshness remain isolated. |
| Daily Values | existing `ingest_usgs_levels.py`, `ingest_usgs_groundwater.py` | daily/weekly/all | Existing operational path remains unchanged in this vector. |
| Monitoring Locations | `ingest_usgs_time_series_metadata.py` | weekly/all | Creates a source-native location registry; does not overwrite utility assets. |
| Time Series Metadata | `ingest_usgs_time_series_metadata.py` | daily/weekly/all | Preserves units, begin/end, last-modified, thresholds, data-gap interval, and calculated freshness state. |
| OGC APIs | `ingest_usgs_field_measurements.py`, `ingest_usgs_peaks.py` | daily/weekly/all | Re-adjudicates only the USGS vectors from PR #109 on current main. Parameter `72019` is default; opposite-direction `62610` remains opt-in. Peak qualifier sets participate in identifiers. |
| Water Quality Portal | `ingest_usgs_water_quality.py` | weekly/all | Puerto Rico discovery is state-scoped and year-bounded. |
| USGS Samples API | existing basin ingest plus `ingest_usgs_water_quality.py` | daily/weekly/all | Numeric results remain readings. Non-detects are stored in a censored ledger and never converted to zero. |
| Statistics | `ingest_usgs_statistics.py` | weekly/all | Reads beta `observationNormals` and `observationIntervals`. Baselines are marked `cross_validation_status=pending` and cannot silently replace local alert percentiles. |
| RTFI | `ingest_usgs_rtfi.py` | fast/daily/weekly/all | Only source-declared NWIS associations become gage-impact edges. Provisional status is explicit. |
| NIMS | `ingest_usgs_nims.py` | daily/weekly/all | Stores camera metadata and recent image listings only. It downloads no image and performs no computer-vision inference. |

## Fail-closed gate

`config/usgs_water_api_coverage.json` is the canonical category matrix.
`scripts/validate_usgs_api_coverage.py` rejects:

- a missing or duplicate category;
- a monitored category without an existing producer;
- a monitored category without output artifacts;
- a monitored category whose producer is absent from every declared cadence;
- provider registration presented as implementation.

`--strict-live` additionally rejects every category lacking a reviewed live receipt.
That strict mode is intentionally an operator promotion gate, not a CI requirement in
the DNS-constrained implementation environment.

## Evidence boundary

Implementation and fixture conformance do not establish that every endpoint currently
returns Puerto Rico records. The first network-enabled run must preserve response
headers, row counts, pagination links, skipped-row accounting, receipt hashes, and
zero-secret scans before any newly added category is promoted from
`implemented_unverified_live` to `live_verified=true`.
