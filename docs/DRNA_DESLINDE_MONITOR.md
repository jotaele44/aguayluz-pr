# DRNA ZMT Deslinde Monitor

Status: **PROVISIONAL / bounded authoritative-source monitor**

## Goal

Detect newly published DRNA-approved/certified Zona Marítimo-Terrestre (ZMT) deslindes without promoting social-media claims, names, proximity, or keyword matches into legal-status findings.

## Authoritative denominator

Current bounded source:

- `https://www.drna.pr.gov/deslindes-zmt-aprobados/`
- Detail notices must resolve under `/deslindes-zmt/deslindes-zmt-aprobados/` on `drna.pr.gov`.

The approved-listing source publishes a stable `Número de Permiso`, a certified date, and commonly the promovente, propietario, address, purpose, and notice-publication date. The monitor uses the permit number as the administrative identity key.

This denominator is **bounded, not universal**. Older/deleted notices, non-web records, appeals, amendments, and geometry exhibits remain separate coverage questions.

### 2026-09-14 pagination observation

The live first listing page exposed 12 visible approved-notice entries and numbered pagination candidates through page 16. Direct checks of at least `/page/2/` and `/page/16/` redirected outside the approved-listing family to an older `Aviso Deslindes ZMT` item (`Page Dorado Beach Resort, Dorado`, 2009). That is a source-manifestation contradiction, not evidence that pages 2-16 are empty.

The runtime therefore treats any numbered pagination candidate that resolves outside the approved-listing family as a blocking acquisition error. It must not silently truncate to page 1 and call the corpus exhaustive. Until the archive/pagination route is independently recovered or an authoritative alternative denominator is found, **historical approved-list exhaustion is BLOCKED**.

## Approval gate

A record may emit `DESLINDE_APPROVED` only when all of the following hold:

1. source host is `drna.pr.gov` or `www.drna.pr.gov`;
2. source path is under the DRNA approved-deslinde detail path;
3. a stable DRNA permit number matching the accepted permit format is present;
4. an explicit valid certified date is present;
5. the permit number did not exist in the previous frozen logical snapshot.

Keyword presence such as `aprobado`, `certificación`, or `deslinde` is insufficient.

## Preservation and identity

Each acquired listing/detail manifestation is eligible for content-addressed raw-byte preservation. Each parsed record preserves:

- authoritative source URL;
- retrieval UTC;
- source byte count;
- SHA-256 of the retrieved detail-page bytes;
- raw published strings for promovente, owner, address, and purpose.

The CLI defaults raw-byte preservation to `data/drna_deslindes/raw_cas/<sha256-prefix>/<sha256>`.

RAW strings are not canonicalized into identity claims. Permit identity, person/company identity, parcel identity, and geometry identity remain separate.

Duplicate stable permit IDs found at distinct authoritative detail URLs fail closed for adjudication; they are never collapsed by name, proximity, or ordering.

## State transitions

`diff_records` emits only:

- `DESLINDE_APPROVED` — a new stable permit appeared in the authoritative approved corpus with an explicit certified date;
- `SOURCE_MANIFESTATION_CHANGED` — the same stable permit remains but one or more published fields changed;
- `SOURCE_ABSENCE` — a previously observed permit is absent from the newly discovered corpus.

`SOURCE_ABSENCE` must never be interpreted automatically as revocation, denial, withdrawal, supersession, or invalidation.

### Baseline rule

The first successful acquisition is a **BASELINE**, not a transition interval. The CLI suppresses `DESLINDE_APPROVED` events on bootstrap by default. Historical approvals are emitted on bootstrap only with the explicit diagnostic flag `--emit-bootstrap-approvals`.

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

Baseline:

```bash
python scripts/ingest_drna_deslindes.py \
  --output data/drna_deslindes/current.json \
  --events data/drna_deslindes/events.json
```

Subsequent diff:

```bash
python scripts/ingest_drna_deslindes.py \
  --previous data/drna_deslindes/previous.json \
  --output data/drna_deslindes/current.json \
  --events data/drna_deslindes/events.json
```

## Certification gates

### PASS in implementation scope

- authoritative-host/detail-path gate;
- stable permit identity gate;
- explicit valid certification-date gate, including Spanish month names;
- social/news/non-approved-path rejection;
- keyword-only rejection;
- duplicate-detail discovery deduplication;
- duplicate stable permit across distinct detail URLs fails closed;
- source disappearance remains `SOURCE_ABSENCE`;
- bootstrap does not manufacture historical transition events;
- raw listing/detail bytes can be preserved in content-addressed storage;
- listing pagination redirects outside the denominator fail closed.

### OPEN/BLOCKED before certification

- **BLOCKED:** recover/exhaust approved-list pagination/archive because observed numbered routes can redirect outside the approved-listing family;
- determine whether older approved notices are discoverable through an alternate authoritative archive/query;
- execute live acquisition and freeze a complete baseline only after denominator closure;
- add appeal/reconsideration/supersession authoritative sources;
- add authoritative geometry-document acquisition and parcel/ZMT/servidumbre binding;
- test broader live HTML drift and malformed-notice variants;
- execute CI/runtime/lint/coverage evidence on the PR head;
- add scheduler/alert delivery only after acquisition denominator and cadence semantics close.

Certification state remains **PROVISIONAL / BLOCKED ON HISTORICAL DENOMINATOR**.
