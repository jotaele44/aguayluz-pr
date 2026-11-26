# NOAA twelve-area build resumption

Scope is the twelve weather.gov menu areas already approved. Aviation routes
to PITIRRE/SkyWatcher, Marine to PITIRRE/MarineWatcher, and Space Weather to
PITIRRE/SpaceWatcher. Spiderweb retains geometry authority. AguaYLuz reuses its
existing hydrological ingestion and consumes relevant shared hazards.

## Increment 1: NWS source identity and lifecycle

The old ingest used numeric source-ID suffixes, which could collapse distinct
CAP identities. The new ID includes the full SHA256 of the exact source ID.
The weather alert projection retains that complete generated identity.

A validated complete active-alert snapshot retires absent producer-owned rows
as closed history. It does not delete them or treat arbitrary URNs as NWS
ownership. Duplicate identities and malformed or paginated snapshots fail
before rewriting the ledger. Reconciliation is deterministic at a fixed
observation time, idempotent, and preserves non-NWS rows.

Raw NWS rows now use the existing `unknown` event enum; weather promotion still
produces `hazard` alerts. A flood warning cannot establish contamination, and
a weather warning cannot establish a utility interruption. The shared enum
remains unchanged; a dedicated hazard enum requires consumer adjudication.
The separate NHC producer's legacy service-event workaround remains OPEN.

Expired/withdrawn/cancelled weather alerts are closed. The API projects expired
historical records as closed with `source_status` retained, without changing
source data. Critical filtering and federation export also check expiration.
The GUI keeps historical evidence inspectable without an actionable critical
badge.

## Evidence and limitations

The ingest stores exact acquisition bytes and the pre-reconciliation ledger
under `data/nws_snapshots` (or the custom output directory). Raw payload archive
hashes establish BYTE identity. Per-event hashes establish LOGICAL canonical
feature-JSON identity using UTF-8, sorted keys and compact JSON separators;
these are deliberately distinguished in acquisition receipts. Receipts record
source URL/origin, UTC retrieval time, input/retained/excluded counts and OPEN
live certification. Immutable byte archives are checked before reuse.

Source geometries, geocodes, references and message metadata are retained in
the raw acquisition snapshot. They are not promoted into certified geometry
by this increment. Explicit CAP relationship modeling, full refresh status
controls, broader product enumeration, and consumer coordination remain work.
No source-row rewrite is executed against the tracked historical ledger during
development; migration occurs through the normal ingestion path after review.

## Rolling sequence

1. Verify NWS identity, reconciliation, semantics and API/GUI regressions.
2. Restore PITIRRE frontend lint and GUI reachability prerequisites.
3. Enumerate and validate product coverage beneath all twelve areas.
4. Reuse existing ingesters; implement each new product through source →
   ingestion → API → GUI with provenance, freshness and failure reporting.
5. Validate live payloads and federation contracts before bounded certification.

Areas: Local; Graphical; Aviation; Marine; Rivers and Lakes; Hurricanes; Severe
Weather; Fire Weather; Sunrise/Sunset; Long Range Forecasts; Climate Prediction;
Space Weather. No broader NOAA scope is added. No live-source or whole-program
certification is claimed.
