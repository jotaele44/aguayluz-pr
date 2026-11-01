# ADR: Native electricity evidence workspace v1

Status: accepted for isolated development; NOT CERTIFIED for release.

## Ownership and compatibility

AguaYLuz retains producer ownership. THEHUB remains the supported Federation
product surface under its existing ADR. The additive `/electricity` route is a
native research workspace, not a replacement hub or an assertion that the full
Electricity Intelligence product is complete. Existing water, outage, hydro,
environmental and GIS paths and exports are unchanged. No production configuration
or existing readiness declaration is changed.

The scientific path is source bytes → immutable receipt → validated source claim
or measurement → read-only projection → GUI. Local presentation preferences
cannot modify scientific state. This plane never consumes legacy nearest-feed
or similarly named asset edges as verified electrical/hydraulic connectivity.

## Evidence and identity

Raw content is SHA-256 addressed and rehashed before every projection. SQLite
receipts, measurements, generator claims and attempt logs are append-only through
application APIs and protected by refusal triggers. Duplicate input is idempotent;
an integrity error blocks the whole projection rather than showing a false empty
system. Receipts preserve retrieval UTC, unresolved publication/license fields,
authority, safe source URL, query parameters without credentials and parser signature.

OBSERVED, RECONSTRUCTED, FORECAST and SOURCE_CANDIDATE are distinct measurement
classes. Derived measurements require versioned methods and uncertainty;
forecasts additionally require issue times before target intervals. Every result
remains AUDIT_ONLY. There is deliberately no promotion endpoint in v1.

Generator identity is source-system + literal EIA plant ID + literal generator ID.
`01` differs from `1`. Names and coordinates never produce crosswalks. Snapshot
effective dates describe the source claim's validity, not commissioning history.
Overlapping incompatible claims are retained in the contradiction ledger.
Cross-system equivalence and historical aliases still require independent review.

## Acquisition boundaries

EIA API credentials come only from server-side `EIA_API_KEY`. The client discovers
endpoint metadata and geographic facets before requesting PR monthly data. Routes
without demonstrable PR coverage fail closed. Page totals, scope, repeated pages,
page limits and missing data are checked; partial rows are never returned as a
complete acquisition. This is not a transactional EIA server snapshot or a
resumable production scheduler. Pagination API support is fixture-tested until
actual official metadata is acquired.

Official workbook URLs are HTTPS/host/path allowlisted; redirects are refused.
Requests have bounded retries, delays, timeouts and response sizes. HTTP client
logging filters redact EIA query credentials; error messages never include raw
request/response text. Credential-echoing responses are refused before storage.
No EIA key is sent when downloading public workbooks.

Offline uploads require operator authentication and carry explicitly UNVERIFIED
origin. They cannot substitute for independent original-source acquisition.
OOXML parsing uses an explicit worksheet and known required headers; unknown
headers, formulas, unsafe members, excessive expansion and ambiguous IDs stay
quarantined. ZIP acquisition is preserved but nested EIA-923 archive interpretation
and full EIA-923 schema adaptation are not implemented.

Electricity writes require a configured operator key; absence disables writes.
They do not inherit the older backend's optional-auth behavior. Keys never enter
frontend build variables, browser preferences, receipts or query artifacts.
Acquisition is synchronous and allows only one network acquisition per process.
Distributed rate limiting, cancellation, scheduler checkpoints and full RBAC
remain open requirements.

## Interfaces

- `GET /electricity/v1/projection`: deterministic content revision, separate state
  collections, source receipts, source claims, contradictions, attempts and gaps.
  Contract: `schemas/electricity_projection.v1.schema.json`. Integrity failure is
  HTTP 503, not zero records. Wall-clock generation time is outside the revision.
- `POST /electricity/v1/acquire`: JSON `{url}`; returns captured SHA-256 only.
- `POST /electricity/v1/import/workbook`: bounded binary body and
  `X-EIA-Source-URL` header; preserves offline-origin uncertainty.
- `POST /electricity/v1/import/860m`: JSON `{sha256, sheet_path, effective_at}`;
  imports source-candidate claims and returns source/retained/excluded/unresolved
  accounting. Source hashes must already be captured and verified.

The new projection does not add fields to legacy Federation streams. THEHUB and
Spiderweb acceptance of this new contract is OPEN; local JSON Schema validation
alone does not establish consumer integration.

## Native presentation

The discoverable bilingual workspace includes evidence status, grid-class/series/
date controls, source-bound charts and tables when records exist, plant/generator
claims, contradictions, original/offline acquisition, import accounting, JSON
export and locally saved language/class preferences. Related existing native
workspaces are linked. Explicit coverage disclosures track the remaining product
modules; they are not implemented forecasts, tariffs, dashboards or alerts.

Browser reload/polling reads the same projection; stale transport failures disable
export and show retry. No unavailable or delayed data are labeled live telemetry.
Mobile Chromium and automated accessibility checks are bounded checks, not native
iPhone installation or assistive-technology certification.
