# Ionosphere RC2 — real frozen TEC context integration

State: PROVISIONAL, feature flags OFF. No release or skill promotion.
Baseline RC0 and RC1 commits remain preserved. Do not redownload the mutable NOAA
source to reproduce this tranche; use the committed capture archive.

## Frozen acquisition

The CI runner acquired a source that this local environment could not retrieve.
This supersedes universal source-blocked wording; the local 403 remains valid.
Run: https://github.com/jotaele44/aguayluz-pr/actions/runs/39991895111
Artifact ID: 12518166220. The job executed PR merge SHA
4f49a0fa586187b242c91ba7403557f204e2ee7d for branch head
e7b002e6f216ddbc9111f170de5ab17e7b5cf20b.

Archive: data-sources/ionosphere/glotec_20261023T163500Z.zip
Archive SHA256: b089a7d7e540f2809dab6d6fb0901226f961980e3fe055e020fcdbc745ad64e8
Raw source: https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt/glotec_icao_20261023T163500Z.geojson
Raw source SHA256: 511f8418b3a5b8f1a5058ca6045970ad9b5dd62647eb6202a2f5cd5d6ce0393b
Raw size: 2,503,439 bytes. Model epoch: 2026-10-23T16:35:00Z.
Receipt records acquisition-start UTC 2026-10-23T17:03:25.188418+00:00;
job logs emitted the completed capture at 17:03:25.9988918Z. The receipt timestamp
must not be interpreted as a separately measured response-completion timestamp.
Archive member paths, uncompressed sizes and SHA256 values are frozen in
capture_manifest.json. The original listing and original receipt are retained.

## Full source inventory and bounded interpretation

UTF-8 GeoJSON FeatureCollection; 5,184 Point features; two coordinate dimensions;
no declared additional CRS member. Interpret longitude/latitude through GeoJSON
semantics; no reprojection or Z/M loss performed. All 72 by 72 expected coordinate
pairs were verified, with no missing or duplicate grid nodes. Property fields:
tec, anomaly, hmF2, NmF2, quality_flag. TEC units are explicitly TECU in metadata;
there are zero null TEC values in this capture. The raw quality distribution is
0:3618, 1:208, 2:236, 3:171, 4:143, 5:808. Flags describe model observation support,
not confidence percentages or actual positioning errors.

The complete grid is read before selecting a context window [-70,16,-60,22].
Six model points are selected and 5,178 excluded; 6 + 5,178 = 5,184. This bbox is
DISCOVERY_CONTEXT_ONLY, not authoritative PR geometry. No municipality, land,
asset, EEZ or service-impact identity is assigned. Full source rows are preserved.
The nearby source node at -67.5,18.75 reports TEC=33.722296197975645, quality_flag=5.
That is a modeled grid-node value at the source epoch, not a Puerto Rico-wide or
municipality measurement. No interpolation, alert, or ROTI calculation is performed.

## Implemented vertical slice

Immutable original archive -> full-grid/hash validation -> read-only preview API
-> dashboard archived-model panel -> source link, SHA256, freshness, raw quality
and count conservation. Corruption/missing capture produces an explicit failure.
The original local HTTP 403 audit remains separate from the successful CI capture.
Archived samples remain marked nonoperational. Both preview flags default OFF.

## Gates

- ION-01 PASS retained; ION-03 frozen TEC acquisition PASS for this exact snapshot.
- ION-02/ION-08 PROVISIONAL until exact RC2 enabled/default GUI and CI pass.
- ION-04 regional model context validated; authoritative PR boundary coverage OPEN.
- ION-05 UNRESOLVED: GNSS station candidates HUPR/GEOL exist, but their download
  links redirect to EarthScope authentication; no receiver observables or ROTI acquired.
- ION-06 BLOCKED: PITIRRE identity verified; its pinned schema excludes ionosphere.
- ION-07 archived capture persisted in Aguayluz; cross-repository producer ingestion OPEN.
- ION-09/ION-10 BLOCKED: cross-repo schema, ROTI, live refresh, native packaging,
  rollback of future data mutations, release/deployment and skill gates remain.

RC1 GitHub validate and default/enabled GUI workflows passed. One unrelated PFAS
Evidence Freeze job failed at downloading the EPA archive; no source was replaced
or gate suppressed. See run 39991895014. This prevents a full-repository PASS claim.
RC2 must receive its own exact-head evidence; RC1 results are not inherited as RC2 PASS.

Local RC2 verification: 19 Python tests plus 25 parameter subtests PASS;
repository ruff and GUI inventory PASS. Three archived-panel UI tests, changed JSX lint and default Vite build PASS.
Rollback is code deactivation (both flags unset and dashboard rebuilt); the snapshot
is immutable and no authoritative operational database is written by this tranche.
Plan score 95/100; hardening design 97/100. These are judgments, not execution scores.
