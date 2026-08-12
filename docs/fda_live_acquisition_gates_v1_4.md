# FDA live source acquisition gates v1.4

Status: **design only; disabled**

This document defines the gates that must be satisfied before AguaLuz may implement or activate any live FDA acquisition path. It adds no HTTP client, credentials, scheduler, database writes, API route, GUI capability, or canonical facility promotion.

## Authority and source boundaries

| Record family | Preferred official source | Secondary official source | Authority boundary |
|---|---|---|---|
| Establishments, registrations, device listings | openFDA registration and listing API or original downloadable files | FDA AccessData Registration & Listing search | Registration or listing is a source assertion, not FDA approval and not an environmental permit. |
| Recalls and enforcement reports | openFDA device enforcement API | FDA Weekly Enforcement Report | Preserve published status and corrections. Do not use ingestion alone as a public alert or lifecycle tracker. |
| Inspection classifications | FDA Inspection Classification/Data Dashboard export when an official export is available | FDA public dashboard search | The public database is not comprehensive. Absence cannot establish that no inspection occurred. |
| Warning, response, and close-out letters | FDA Warning Letters search and official XLSX/document links | FDA Reading Room | A warning letter is not final adjudication; later responses, close-out letters, and other actions may change status. |

## Source-admission gate

Every source profile must be approved before any network implementation. Admission requires:

1. Official FDA or HHS ownership and an allow-listed HTTPS host.
2. Documented access mode: API, official bulk file, official tabular export, or bounded HTML/document retrieval.
3. A frozen terms and policy snapshot with retrieval time and SHA-256.
4. Explicit update cadence, coverage limits, known omissions, and maximum query/page constraints.
5. Public redistribution classification for each field and document.
6. A source-specific prohibition list preventing approval, compliance, environmental-permit, and complete-universe inference.

HTML acquisition is denied by default. It may be admitted only where no official API or bulk export provides the record family and after terms, robots, pagination, and document-link behavior are reviewed.

## Bounded HTTP client contract

A future implementation must satisfy all of the following:

- disabled by default and constructed only through dependency injection;
- HTTPS only; certificate verification mandatory;
- exact host allow-list with redirects rejected when the destination host is not allowed;
- connect and read timeouts; bounded response-body size; bounded decompression ratio;
- no cookies unless an approved source profile explicitly requires them;
- deterministic user agent identifying the project and contact channel;
- API key passed only in the documented request location and never persisted in a URL receipt;
- response media-type validation and schema/content sniffing before normalization;
- raw response bytes written only to an immutable staging receipt store after hash calculation;
- no automatic execution from imports, GUI startup, API startup, or scheduler discovery.

## Rate-limit and retry contract

The implementation must read documented openFDA limits at activation time and freeze them in an operator-approved source profile. Numeric limits must not be hard-coded from memory.

Required behavior:

- anonymous mode is permitted only for bounded smoke tests;
- routine acquisition requires an API key where openFDA supports one;
- token-bucket or equivalent client-side limiting below the documented ceiling;
- honor `Retry-After` and provider rate-limit headers when present;
- retry only transient network failures, HTTP 408, 429, and bounded 5xx responses;
- exponential backoff with jitter and a maximum attempt count;
- no retry for 400, 401, 403, 404, schema mismatch, terms failure, or hash mismatch;
- circuit-open state after repeated provider or contract failures;
- one run-level request budget and one source-level byte budget.

## Pagination and checkpoint contract

Each source adapter must define a versioned checkpoint containing:

- source profile version;
- request/query fingerprint;
- page, skip/limit cursor, opaque cursor, or file identity as applicable;
- high-water timestamp only when the source guarantees suitable ordering;
- ETag and Last-Modified values when provided;
- last accepted raw receipt ID and SHA-256;
- normalizer version;
- retrieval start and completion timestamps;
- terminal, partial, failed, superseded, or replay state.

Checkpoints are invalidated when source profile, query scope, file identity, or normalizer contract changes. A changed ETag or Last-Modified value triggers a new immutable observation set; it never overwrites prior raw bytes.

## Provenance and receipt contract

Every HTTP response or official download must produce a receipt before normalization. Required fields include:

- provider and source ID;
- requested URL with secrets removed;
- HTTP method and status;
- retrieval timestamp;
- response media type and byte count;
- SHA-256 of exact raw bytes;
- ETag, Last-Modified, Content-Disposition, and final allow-listed URL when present;
- retry count, pagination cursor, and request fingerprint;
- terms/profile version;
- redaction report;
- failure classification.

Normalization must bind observation identity to provider record identity, raw SHA-256, and normalizer version. Corrections, retractions, and later versions remain additive and linked by supersession fields.

## Secret and logging gate

- Keys are loaded only from an operator-controlled environment variable or private file outside the repository.
- Keys, authorization headers, cookies, query credentials, and session identifiers are denied from logs, exceptions, receipts, checkpoints, fixtures, telemetry, and exports.
- Redaction is allow-list based, tested with sentinel secrets, and applied before serialization.
- Debug mode cannot emit raw headers or complete request URLs.
- Secret scanning must pass on the exact final head.

## Export and entity-resolution gate

Public export is fail-closed. Only fields explicitly approved in the source profile may leave staging. Raw warning-letter documents and inspection records retain their original source links and authority notes.

No FDA record may automatically:

- create or merge a canonical facility;
- establish current compliance or noncompliance;
- establish FDA approval from registration/listing;
- establish an environmental permit, water withdrawal, discharge, well, or wastewater relationship;
- treat absence from a public FDA dataset as negative evidence.

Entity links remain proposed observations until contradiction review and human adjudication under the merged regulatory entity-link schema.

## Activation sequence

A future live implementation requires separate explicit authorization and all of these stages:

1. Legal/terms review receipt for every admitted source.
2. Offline contract tests and replay fixtures.
3. Disabled network client implementation with no scheduler or persistence activation.
4. Bounded operator-host smoke against one source and one page/file.
5. Raw receipt and secret-redaction inspection.
6. Freshness, correction, pagination, rate-limit, and failure-mode tests.
7. Separate approval for staging persistence.
8. Separate approval for scheduling.
9. Separate approval for any public export.

Failure at any stage leaves live acquisition disabled.

## Current decision

The approved design does not authorize implementation or execution of live requests. The merged offline FDA adapter remains the only executable FDA component and accepts injected fixture data only.
