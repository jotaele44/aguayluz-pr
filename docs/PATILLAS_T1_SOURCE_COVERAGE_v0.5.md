# Patillas–Guayama T1 source coverage v0.5

## Scope

This post-merge design package maps the evidence required for one synchronized Patillas–Guayama volumetric water-balance window. It does **not** execute a real balance, poll providers, persist observations, expose an API or GUI surface, export federation data, send alerts or notifications, schedule work, or issue control actions.

Origin base: `main@debbef3e901c7edeb5e6d91c9dfc888383b2024c`. Latest reviewed main during v0.5 construction: `01a991d6b7ecaf36458d6faf1acd1012b84da897`.

## Required interval inputs

A real 15-minute slice requires all of the following:

1. Río Grande de Patillas inflow;
2. Río Marín inflow;
3. reservoir stage at the slice start and end, transformed through the merged PRVD02 v0.4.1 stage–storage model;
4. outlet-works/canal release;
5. below-dam Río Grande de Patillas discharge representing any distinct river outlet/spill pathway;
6. direct Guayama treatment withdrawal;
7. downstream terminal canal flow;
8. area-weighted direct precipitation volume;
9. open-water evaporation volume;
10. documented operational-loss volume.

A daily balance may be assembled only from 96 individually admitted 15-minute slices. No required inflow or outflow component may be silently imputed as zero.

## Public-source adjudication

### Reservoir inflow topology

USGS Scientific Investigations Map 3128 places Lago Patillas at the confluence of Río Grande de Patillas and Río Marín. USGS stations 50092000 and 50093000 provide public discharge records for those two named tributaries. The model therefore treats total upstream inflow as a derived composite of both admitted tributary measurements plus any separately quantified local runoff between gauges and the reservoir. A single 50092000 series is not accepted as total reservoir inflow.

### Reservoir storage

USGS 50093045 provides PRVD02 reservoir elevation. The merged v0.4.1 stage–storage relation can transform admitted stage observations to storage. Current instantaneous observations remain blocked until revision state and measurement uncertainty/calibration evidence satisfy the v0.5 gate.

### Canal outlet

USGS 50093053 provides Canal de Patillas forebay discharge. It is useful T1 evidence but is not automatically identical to outlet-works release because it is downstream of the dam. USGS gate-opening heights at 50093045 are operational context and are not discharge without an authoritative rating or operation relation.

### Below-dam river outlet

USGS 50093120 measures Río Grande de Patillas below Lago Patillas. This is retained as a separate reservoir-outflow term because it can capture water leaving the reservoir through a river/spill/outlet pathway distinct from irrigation flow in Canal de Patillas. A zero value cannot be assumed solely from normal canal operating practice; the interval must be observed or otherwise documented.

### Direct treatment withdrawal

Puerto Rico Statistics/AAA publicly describes average monthly raw-water extraction and production by filtration plant or well in MGD. That is authoritative public context but is too coarse for a 15-minute synchronized slice. A synchronized difference between USGS stations above and below the Guayama filtration plant may be retained as a derived diversion estimate, but it must not be labeled a direct plant-meter withdrawal.

### Downstream terminal flow

USGS 50093078 and 50093083 provide downstream canal discharge observations. Neither is currently proven to be the terminal balance boundary, and additional diversions may occur downstream. They remain intermediate T1 gauges/proxies until topology closure is complete.

### Precipitation

NOAA/NWS MRMS provides public machine-readable gridded precipitation products for the Caribbean, and USGS 50093045 provides an independent point precipitation observation. Conversion to reservoir precipitation volume requires water-surface geometry applicable to the slice, exact spatial clipping/area weighting, temporal integration, and quantified QPE/geometry uncertainty.

### Evaporation

USGS documents historical Puerto Rico reservoir/pan-evaporation methods and regional climatology. No current public direct interval Lago Patillas open-water evaporation observation was identified in the v0.5 sweep. A modeled interval term would require meteorological inputs, model version, water-surface area, and uncertainty; historical climatology alone is not admissible.

### Documented operational losses

AEE/PREPA public transition material confirms multiple Patillas irrigation-system consumers. The reviewed public material does not expose synchronized flushing, leakage, maintenance-discharge, or other operational-loss volumes. No balancing value is inserted for this missing term.

## Admission policy

Every real observation must be T1, nonprovisional, current/accepted revision, calibration-verified, source-hash bound, topology-version bound, and accompanied by numeric uncertainty with provenance. Rate/volume terms must represent the exact 15-minute interval. Stage observations must use PRVD02 and fall within 7.5 minutes of the corresponding boundary timestamp.

`proxy_only` and `public_document_only` records cannot satisfy a real interval balance input.

## Public OSINT disposition

The bounded v0.5 sweep now closes two source-discovery blind spots: the Río Marín tributary and the below-dam Río Grande de Patillas gauge. The real balance remains blocked because source discovery is not the same as admission. Further public-path work should focus on authoritative AEE/PREPA outlet/canal ratings, machine-readable AAA interval extraction if publicly exposed, terminal-canal topology, stage-area geometry, current evaporation modeling inputs, and any public operational-loss ledger.

No operator request has been sent.

## Safety of inference

A future balance residual is an accounting discrepancy. It is not proof of theft, fraud, illegal diversion, unauthorized activity, or a specific leak/failure location. Root-cause attribution requires independent corroboration.
