# Bounded NOAA coverage qualification — 2026-10-05

State: AUDIT_ONLY. Offline snapshot verification PASS. Live-source certification OPEN.

## Mergeability adjudication

The earlier normalized PR325 response reported false. The raw GitHub PR API instead
reported `mergeable: null`, `mergeable_state: unknown`; this does not establish a
content conflict. Against fetched main `1f4df9b00940537fa4fa595473c4d09590595053`
and PR head `a7df1b91e7fe32642d1ea2ef19e10e99661a2a55`,
`git merge-tree --write-tree` exited 0 with merged tree
`cd874f84be940b27c0ad66fbd9b589ed99133b19`. No ref was moved or PR merged.
The content-conflict concern is resolved for these exact inputs; remote readiness
and review remain separate. Existing passed runtime tests were not repeated.

## Frozen coverage

Eight payloads are preserved exactly, with hashes, HTTP status, headers, request
URL and retrieval UTC in the two receipt files. Acquisition occurred between
15:36:03 and 15:36:49 UTC. The seven-identifier discovery request was supplemented
only for TJMZ after inspecting the existing eight-entry PITIRRE airport registry.
No earlier frozen successful payload was downloaded again for that supplement.
Initial connectivity probes preceded this snapshot and were not byte-preserved;
they are not used as certification evidence.

| Existing registry ICAO | Station metadata returned | METAR returned | TAF returned |
|---|---|---|---|
| TJBQ | Yes | Yes | Yes |
| TJCP | No | No | No |
| TJIG | Yes | Yes | No |
| TJMZ | Yes | No: HTTP 204 | No: HTTP 200 empty array |
| TJPS | Yes | Yes | Yes |
| TJRV | Yes | No | Yes |
| TJSJ | Yes | Yes | Yes |
| TJVQ | No | No | No |

Source: AWC API responses in this directory, joined only by exact ICAO identifier.
Registry source: `skywatcher-pr/configs/airport_registry.yaml`, inspected local
commit `35392483019658dfad2d602d72f32444f5e7a29c` (same tree as remote prerequisite
commit `b93517d4145452c88fb24ec15f715219fd7f24a4`). This query scope is not an
exhaustive Puerto Rico airport/station census. No polygon or municipality identity
was adjudicated. Spiderweb retains geometry authority.

Arithmetic: station metadata 6 returned + 2 not returned = 8; METAR 4 + 4 = 8;
TAF 4 + 4 = 8. No unexpected or duplicate returned ICAO IDs. All returned rows
are retained; exclusions = 0. Not returned is an acquisition observation, not
proof of permanent source absence or station closure.

METAR ∩ TAF = {TJBQ, TJPS, TJSJ}; METAR-only = {TJIG}; TAF-only = {TJRV};
union = {TJBQ, TJIG, TJPS, TJRV, TJSJ}; symmetric difference = {TJIG, TJRV}.
Equal product counts did not imply equal station coverage.

The point 18.3783,-66.0183 is a discovery sample, not certified geometry or an
island-wide denominator. NWS returned SJU grid 169,124 and a forecast containing
14 contiguous periods. Source updateTime is 2026-10-05T08:25:37+00:00;
generatedAt is 2026-10-05T15:36:20+00:00. Period coverage runs from
2026-10-05T11:00:00-04:00 through 2026-10-12T06:00:00-04:00.
These timestamps have distinct meanings. Forecast units are `us`.

## Validation and build implications

Run `python docs/evidence/noaa-coverage-20261005/verify_snapshot.py` from the
AguaYLuz root. It performs no network calls or production writes. It verifies
all eight hashes and byte sizes, query accounting, exact-ID uniqueness,
coordinates, TAF validity at acquisition, non-future METAR observation times,
and forecast period identity/order/continuity. The output is verification.json.
The mixed HTTP 204 and HTTP 200 empty results are preserved separately.
The raw TJMZ acquisition receipt's broad `HTTP_ERROR_OR_NO_DATA` label is
superseded for interpretation by HTTP 204 = successful no-content; raw receipt
is retained without rewriting. The offline verifier treats it accordingly.

YES_AFTER: product-specific no-data/freshness handling must precede enabling
aviation weather. Weather belongs to SkyWatcher, but the existing airport-state
weather_json field must not force TAF forecasts into an observed-at-only model
or turn weather into a confirmed operational disruption. Reuse airport identities,
provenance and console infrastructure; keep METAR observation time and TAF
issue/valid times distinct. Preserve visibility strings such as `10+` and units.

Local forecast has a successful one-point candidate path. Expand only through
explicit intended locations; do not interpolate municipal coverage from this
sample. Reuse AguaYLuz refresh/monitoring and expose forecast freshness and
failure states through its GUI before enabling scheduling.

No production adapter or GUI was enabled by this evidence increment. Remaining:
product contracts and negative fixtures; complete backend/API/GUI implementation;
freshness policy; contract tests; deployment verification; bounded live certification.
No live-source claim is promoted from script success.
