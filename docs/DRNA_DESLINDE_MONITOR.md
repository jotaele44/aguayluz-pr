# DRNA ZMT Deslinde Monitor

Status: **PROVISIONAL / bounded authoritative-source monitor**

## Goal

Detect newly published DRNA-approved/certified Zona Marítimo-Terrestre (ZMT) deslindes without promoting social-media claims, names, proximity, or keyword matches into legal-status findings.

## Authoritative denominator

Current bounded source:

- `https://www.drna.pr.gov/deslindes-zmt-aprobados/`
- Detail notices must resolve under `/deslindes-zmt/deslindes-zmt-aprobados/` on `drna.pr.gov`.

The approved-listing source publishes a stable `Número de Permiso`, a certified date, and commonly the promovente, propietario, address, purpose, and notice-publication date. The monitor uses the permit number as the administrative identity key.

This denominator is **bounded**, not universal. Pagination/archive completeness, older notices, deleted pages, non-web records, appeals, amendments, and geometry exhibits remain separate coverage questions.

## Approval gate

A record may emit `DESLINDE_APPROVED` only when all of the following hold:

1. source host is `drna.pr.gov` or `www.drna.pr.gov`;
2. source path is under the DRNA approved-deslinde detail path;
3. a stable DRNA permit number matching the accepted permit format is present;
4. an explicit parseable certified date is present;
5. the permit number did not exist in the previous frozen logical snapshot.

Keyword presence such as `aprobado`, `certificación`, or `deslinde` is insufficient.

## Preservation and identity

Each parsed record preserves:

- authoritative source URL;
- retrieval UTC;
- source byte count;
- SHA-256 of the retrieved detail-page bytes;
- raw published strings for promovente, owner, address, and purpose.

RAW strings are not canonicalized into identity claims. Permit identity, person/company identity, parcel identity, and geometry identity remain separate.

## State transitions

`diff_records` emits only:

- `DESLINDE_APPROVED` — a new stable permit appeared in the authoritative approved corpus with an explicit certified date;
- `SOURCE_MANIFESTATION_CHANGED` — the same stable permit remains but one or more published fields changed;
- `SOURCE_ABSENCE` — a previously observed permit is absent from the newly discovered corpus.

`SOURCE_ABSENCE` must never be interpreted automatically as revocation, denial, withdrawal, supersession, or invalidation.

## Geometry boundary

Administrative approval and geometry identity are different claims.

This monitor does **not** establish:

- the exact approved boundary geometry;
- parcel identity;
- ZMT geometry;
- servidumbre de salvamento geometry;
- whether a technical recommendation was followed;
- whether an approval is currently final after appeal/reconsideration.

Those require separate authoritative documents/geometries and contradiction adjudication.

## Punta Bandera calibration case

The DRNA approved-deslinde notice for permit `O-AG-CER02-SJ-00887-16062025` publishes:

- owner: `PUNTA BANDERA ASSOCIATES, INC.`;
- location text: Luquillo Beach Boulevard/Ocean Drive, Bo. Mata de Plátano, Luquillo;
- purpose: delimit area and residential project;
- certified date: `2026-07-29`;
- notice publication date: `2026-08-24`.

The repository regression fixture uses those published fields strictly as an authoritative administrative-status calibration case. It does not certify parcel/ZMT/servidumbre geometry or adjudicate the separate allegation that technical reports or a servidumbre were disregarded.

## Run

```bash
python scripts/ingest_drna_deslindes.py \
  --previous data/drna_deslindes/previous.json \
  --output data/drna_deslindes/current.json \
  --events data/drna_deslindes/events.json
```

For the first run, omit `--previous`. Every current record will then appear as newly observed; that bootstrap run must be classified as baseline acquisition, not as proof that all approvals occurred during the monitoring interval.

## Open gates before certification

- exhaust listing pagination/archive behavior;
- determine whether older approved notices are discoverable outside the current listing;
- freeze listing-page bytes in addition to detail-page hashes;
- preserve raw detail-page bytes in a CAS or immutable acquisition store rather than hashes alone;
- add scheduler/alert delivery only after cadence and failure semantics are defined;
- add appeal/reconsideration/supersession sources;
- add authoritative geometry-document acquisition and parcel/ZMT/servidumbre binding;
- test live HTML drift and malformed-notice handling;
- verify no duplicate permit IDs are published across distinct detail URLs without adjudication.

Certification state remains **PROVISIONAL** until those bounded-source and persistence gates close.
