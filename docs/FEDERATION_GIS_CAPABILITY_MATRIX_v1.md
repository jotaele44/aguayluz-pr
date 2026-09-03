# Federation GIS Capability / Duplication Matrix v1

Frozen baseline: spiderweb-pr `02169e73bf7ae110eeccb8cfaf47a4f7dfa2989f`; moneysweep-pr `b5661dd29b5905015016041057136b6c945ddf5a`; aguayluz-pr `d46758886a40a290c15a3b138e131910163b0d1e`; skywatcher-pr `6d7831c1cc665ad3080c9cab92a673cc5eb8e2e9`.

Authoritative boundaries: Spiderweb = cross-domain investigation/fusion GIS; MoneySweep = capital/contracts/ownership/project geography; AguaYLuz = water/power/environmental infrastructure; Skywatcher = aviation/airspace/terrain/4D trajectories.

Shared invariants: WGS84/CRS84 interchange; explicit projected CRS for computation; distinct logical/source-manifestation hashes; spatial proximity defaults to `CANDIDATE_NOT_IDENTITY`; repo-owned PostGIS planes; `federation-map-runtime/1.0`; `fedgeopack/1.0`; mandatory `federation-spatial-impact/1.0` reports.

Current deficits under this branch: MoneySweep no-fabrication point/flow materialization; Skywatcher geodesic meters replacing planar degrees as production proximity; AguaYLuz deterministic hydro-network/raster interfaces; Spiderweb typed auditable cross-domain spatial relations.

`FOUR-REPO GIS CERTIFIED` requires schema + geometry + tests + security + performance + federation + desktop + iOS gates; passing code tests alone is not certification.
