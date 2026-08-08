# Patillas–Guayama T1 source coverage v0.5

## Scope

This post-merge design package maps the evidence required for one synchronized Patillas–Guayama volumetric water-balance window. It does **not** execute a real balance, poll providers, persist observations, expose an API or GUI surface, export federation data, send alerts or notifications, schedule work, or issue control actions.

Base: `main@debbef3e901c7edeb5e6d91c9dfc888383b2024c`.

## Required interval inputs

A real 15-minute slice requires all of the following:

1. external reservoir inflow;
2. reservoir stage at the slice start and end, transformed through the merged PRVD02 v0.4.1 stage–storage model;
3. reservoir/canal release;
4. direct Guayama treatment withdrawal;
5. downstream terminal canal flow;
6. area-weighted direct precipitation volume;
7. open-water evaporation volume;
8. documented operational-loss volume.

A daily balance may be assembled only from 96 individually admitted 15-minute slices.

## Public-source adjudication

### Upstream inflow

USGS 50092000 provides public machine-readable discharge and is T1 technical evidence. It is not yet promoted as the complete reservoir-inflow term because the boundary must prove that all other tributary/local inflow is either measured, modeled explicitly, or outside the balance boundary. Current instantaneous values are provisional subject to revision.

### Reservoir storage

USGS 50093045 provides PRVD02 reservoir elevation. The merged v0.4.1 stage–storage relation can transform admitted stage observations to storage. Current instantaneous observations remain blocked until their revision state and measurement uncertainty/calibration evidence satisfy the v0.5 gate.

### Release

USGS 50093053 provides Canal de Patillas forebay discharge. That is useful T1 evidence but is not automatically identical to dam release because it is downstream of the release point. USGS gate-opening heights at 50093045 are explicitly temporary operational measurements; gate opening is not discharge without an authoritative rating or operation relation. The real release term therefore remains blocked.

### Direct treatment withdrawal

Puerto Rico Statistics/AAA publicly describes a dataset containing average monthly raw-water extraction and production for each filtration plant or well, reported in MGD. That is authoritative public context but is too coarse for a 15-minute synchronized slice. A synchronized difference between USGS stations above and below the Guayama filtration plant may be retained as a derived diversion estimate, but it must not be labeled a direct plant-meter withdrawal.

### Downstream terminal flow

USGS 50093078 and 50093083 provide downstream canal discharge observations. Neither is currently proven to be the terminal boundary of the Patillas canal balance, and additional diversions may occur downstream. They remain intermediate T1 gauges/proxies until topology closure is complete.

### Precipitation

NOAA/NWS MRMS provides public machine-readable gridded precipitation products for the Caribbean, and USGS 50093045 provides an independent point precipitation observation. Conversion to reservoir precipitation volume requires the water-surface geometry applicable to the slice, exact spatial clipping/area weighting, and a quantified QPE uncertainty model. Until those are bound, precipitation is a T1 precursor rather than an admitted volume.

### Evaporation

USGS documents historical Puerto Rico reservoir/pan-evaporation methods and regional climatology. No current public direct interval Lago Patillas open-water evaporation observation was identified in this v0.5 sweep. A modeled interval term would require meteorological inputs, model version, water-surface area, and uncertainty; historical climatology alone is not admissible.

### Documented operational losses

AEE/PREPA public transition material confirms the Patillas irrigation system serves AAA filtration plants, agriculture, AES, domestic services, and other contracted uses. The reviewed public material does not expose synchronized flushing, leakage, spill, maintenance-discharge, or other operational-loss volumes. No balancing value is inserted for this missing term.

## Admission policy

Every real observation must be T1, nonprovisional, current/accepted revision, calibration-verified, source-hash bound, topology-version bound, and accompanied by a numeric uncertainty with provenance. Rate/volume terms must represent the exact 15-minute interval. Stage observations must use PRVD02 and fall within 7.5 minutes of the corresponding boundary timestamp.

`proxy_only` and `public_document_only` records cannot satisfy a real interval balance input.

## Public OSINT disposition

The bounded v0.5 sweep identifies public sources and remaining gaps but sends no operator requests. Further public-path work should focus on authoritative AEE/PREPA canal ratings/release records, any machine-readable AAA plant extraction history beyond monthly averages, reservoir stage-area geometry for precipitation and evaporation transforms, and any public operational-loss records.

## Safety of inference

A future balance residual is an accounting discrepancy. It is not proof of theft, fraud, illegal diversion, unauthorized activity, or a specific leak/failure location. Root-cause attribution requires independent corroboration.
