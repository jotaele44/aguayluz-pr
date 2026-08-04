# Laguna Cartagena one-day field and operator packet v0.4

## Control objective

Collect one authorized, provenance-complete observation window for Laguna Cartagena and the southwest irrigation system. Records remain in shadow mode and cannot trigger public notification, production promotion, control action, or an automatic leakage finding.

## Personnel and access boundary

This packet is for an authorized, qualified adult field crew operating under the land manager's approval and its site-specific safety plan. It does not authorize entry to the refuge, entry into water, boating, confined-space work, electrical work, gate manipulation, or access to operator facilities. No sampling begins until the USFWS authorization file is present, signed, and hashed in `file_manifest.csv`.

## Fixed monitoring locations

| ID | Location | Coordinates | Required measurements |
|---|---|---|---|
| `50129899` | Laguna Cartagena near Boquerón | 18.0124634301021, -67.1087894817786 WGS84 | Lagoon stage; conductivity; temperature; DO; pH; turbidity; nitrate; ammonia; phosphorus; fecal indicator |
| `50129900` | Laguna Cartagena outflow | 18.01246343, -67.1090673 NAD83 | Outflow discharge |
| `180046067053700` | Laguna Cartagena well | 18.01079699, -67.0932338 NAD83 | Local groundwater level |
| `50128905` | Lajas irrigation canal below Lago Loco | Authoritative operator/USGS location | Release, treatment withdrawal, agricultural turnout, gate position, known leak |
| `50128940` | Downstream canal operational gage | Authoritative operator/USGS location | Terminal flow |

Field coordinates must be recorded from the field device and fall within 0.5 km of the bound direct location. A site ID alone does not replace the field GPS fix.

## One-day synchronization contract

1. The packet declares one `window_start_utc` and `window_end_utc`.
2. The window cannot exceed 24 hours.
3. Every observation includes an ISO-8601 timestamp with an explicit offset and is normalized to UTC.
4. Direct field measurements and operator records must fall inside the same declared window.
5. Water balance is computed only when `canal_release`, `treatment_withdrawal`, `agricultural_turnout`, and `terminal_flow` are present in `ft3/s`.
6. Gate position and known-leak flow are retained as supporting operational evidence but do not substitute for a required balance term.

## Required evidence files

Each observation row references:

- the raw instrument export or authoritative operator record;
- a contemporaneous location photograph for field records;
- field notes for field records;
- instrument and calibration identifiers for in-situ measurements;
- a sample identifier and complete chain-of-custody entry for laboratory analytes.

Every referenced file must appear in `file_manifest.csv` with its exact SHA-256 digest. A renamed, edited, absent, or hash-mismatched file is rejected.

## Calibration record

`instrument_calibrations.csv` binds:

- instrument ID;
- calibration record ID;
- calibration and expiry timestamps in UTC;
- standard or lot identifier;
- calibration certificate file and SHA-256;
- responsible qualified person and signature.

The calibration window must contain the observation time.

## Chain of custody

For nitrate, ammonia, phosphorus, and fecal-indicator results, `chain_of_custody.csv` must bind:

- sample ID and collection UTC;
- collector;
- tamper-evident seal ID;
- each custody transfer;
- sample condition;
- laboratory receipt UTC;
- laboratory report file and SHA-256;
- responsible signature.

A laboratory result without complete custody and a hashed report remains a gap and is not ingested.

## Operator request scope

AAA and the southwest irrigation-system operator are requested to provide existing records for the declared field window:

- canal release;
- treatment withdrawal;
- agricultural turnout;
- gate position/state;
- known leak flow or an explicit `none recorded` statement;
- terminal flow.

Records should preserve original timestamps, timezone, units, source-system record IDs, revision status, and the original CSV/PDF/export when available. The request is direct-provider outreach, not a FOIA request.

## Execution

```bash
python operators/laguna_cartagena_field_packet.py \
  field_packets/laguna_cartagena/v0.4/<packet-id> \
  --output-dir artifacts/laguna_cartagena_field_packet
```

A blank or incomplete packet produces `explicit_gap_receipt`, keeps `current_condition.status = unknown`, and writes no eligible observations.

## Promotion rule

`current_condition.status` may leave `unknown` only through the existing control plane after all twelve direct metrics pass location, freshness, validity, QA, directness, representativeness, calibration/custody, evidence-file, and schema controls. The validator never sets eligibility fields itself and never makes a leakage claim.
