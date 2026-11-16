# Puerto Rico hydrologic feature inventory

## Why

The repository monitored groundwater as individual USGS wells. It had no aquifer as an
entity, no way to say which aquifer a well draws from, and no account of wells that only
other agencies list. The goal set for this work was to include every known aquifer, well,
spring and stream, and to reflect what is known rather than what any one source says.

This document covers **phase 1** (aquifers and wells), **phase 2** (springs), **phase 3**
(streams, named watercourses, waterfalls, waterbodies, reservoirs, intakes, gauges and
watersheds) and **phase 5** (canals, wetlands, dams, treatment and wastewater plants, pump
stations, tanks and non-PRASA community water systems). Phase 4 (an aquifer-level series and
the map workspace) adds no feature type. Every feature type is enumerated; the receipt's
`phase_scope` would name any that were not, and the page would say so.

Phase 5 uses official registries only. Files supplied by the user (OSM extracts, canal and
facility spreadsheets, project registers) were used to find these registries and as test
cross-checks, never as claims.

## What "100%" means here

The denominator is the union of the enumerated sources. Coverage is complete for those
sources when three things hold:

- every claim from every source is either assigned to exactly one feature or excluded with
  a stated reason;
- the arithmetic closes (`source = retained + excluded`, checked per source);
- disagreements between sources are kept and shown.

It does **not** mean every possible match between sources has been resolved. Where identity
is uncertain, the count is a range. It also does not mean no other aquifer or well exists:
`completeness_claimed` is `false`, and the known gaps are listed.

## Sources

| Source | What it contributes | Tier | Pinned? |
|---|---|---|---|
| USGS HA 730-N polygons, `aquifers_pr`, [doi:10.5066/P98YGFVN](https://doi.org/10.5066/P98YGFVN) | 473 polygons, of which 210 are Puerto Rico aquifer polygons in 104 groups | T1 | SHA-256 |
| USGS HA 730-N text, `pubs.usgs.gov/ha/ha730/ch_n/` | Esperanza–Resolución Valley aquifer (Vieques); the Mona/Culebra and North Coast area statements | T1 | quotes must still be on the page |
| USGS aquifer-code dictionaries (Water Data API) | 35 local codes, 2 national codes | T1 | hashed per run |
| USGS monitoring locations, state 72 (Water Data API) | 7,318 sites, of which 5,437 are wells | T1 | hashed per page |
| USGS NWIS site service, groundwater | cross-check only: same 5,437 wells, same aquifer codes, or the run fails | T1 | hashed |
| Water Quality Portal, site type Well | 5,434 USGS rows (I1 joins) and 240 Puerto Rico EQB wells | T2 | hashed |
| EPA SDWIS well facilities | 1,384 wells (712 active, 672 inactive), **with no coordinates** | T2 | hashed |
| DRNA PIRA 2016 | 17 named aquifer units, hand-transcribed with page references | T2 | SHA-256 of the PDF |
| Water Quality Portal, site type Spring | 221 rows, all USGS (I1 joins) | T2 | hashed |
| USGS GNIS domestic names, Puerto Rico | 434 hydrographic names of 5,818 rows: springs, streams, canals, falls, lakes, swamps and reservoirs | T2 | hashed |
| USGS NHD large scale, flowlines (The National Map) | 17,093 mapped reaches; 1,212 coastline segments excluded by reason | T1 | hashed per page |
| USGS NHD large scale, waterbodies | 3,869 polygons (lakes and ponds, swamps, reservoirs) | T1 | hashed per page |
| USGS Watershed Boundary Dataset | 6 HUC8 and 29 HUC10 watersheds | T1 | hashed |
| EPA SDWIS intake facilities | 690 intakes (353 active), **with no coordinates** | T2 | hashed |
| NOAA NWPS gauges (`data/nwps_gauge_state.jsonl`) | 118 forecast gauges, each publishing its USGS site number | T1 | hashed |
| Repository assets (`data/utility_assets.jsonl`) | 124 OSM reservoirs and 7 local intake points (which carry no coordinates) | T3 | hashed |
| PRASA public facility layer, ArcGIS `PR_PRASA_Facilities` (May 2020 snapshot) | 4,325 facilities; 4,254 retained, 71 offices excluded | T2 | hashed per page |
| USACE National Inventory of Dams, nation CSV | 36 Puerto Rico dams | T1 | hashed |
| EPA ECHO, Clean Water Act facilities in Puerto Rico | 2,820 NPDES permittees; 63 publicly owned treatment works retained, 2,757 excluded by reason | T1 | hashed per page |
| EPA SDWIS facilities of type TP, SP and ST | 1,648 treatment plants, 5 springs, 2 storage, **with no coordinates** | T2 | hashed |
| FEMA Region 2, EPA non-PRASA sites (2017) | 235 rows; 233 community systems keyed by PWSID, 2 excluded (no id) | T2 | hashed |
| USFWS National Wetlands Inventory (MapServer) | 16,357 polygons; 7,960 wetlands and 1,673 ponds and lakes retained, 6,724 excluded by reason | T1 | hashed per page |

All sources, URLs and pins are in `config/hydro_inventory_sources.v1.json`.

## Springs (phase 2)

223 spring features: the 221 USGS spring sites (each joined to its Water Quality Portal copy
by site number) and the 2 springs GNIS names in Puerto Rico. No GNIS spring lies within
150 m of a USGS spring, so there are no candidate pairs and the count is not a range.
Phase 5 adds the 5 springs EPA SDWIS lists as water sources, without coordinates, for 228.

Each spring is linked to the HA 730-N polygon it sits in (`SPRING_IN_AQUIFER`,
`DERIVED_TOPOLOGICAL`). None of the 221 USGS springs carries a USGS aquifer code.

This is a small number for an island with extensive karst. It is what the public sources
enumerate, not an estimate of how many springs exist; springs known only from speleological
or local records are listed as a known gap.

## Surface water (phase 3)

| Feature type | Count | How it is built |
|---|---|---|
| Stream reaches | 13,373 | every NHD flowline that is not coastline or canal/ditch, keyed by its NHD permanent identifier |
| Canals | 2,508 | NHD flowlines of FType 336 (canal/ditch), same identifier; added in phase 5 |
| Named watercourses | 324 | GNIS streams, canals, channels and guts; joined to their reaches through the GNIS id NHD publishes (I2) |
| Waterfalls | 5 | GNIS falls |
| Waterbodies | 3,276 | NHD lakes, ponds and swamps grouped by published GNIS id, plus GNIS lakes, swamps and basins |
| Reservoirs | 798 | NHD reservoirs and GNIS reservoirs grouped by published GNIS id, plus the 124 OSM reservoirs as their own features |
| Intakes | 697 | 690 SDWIS intakes and 7 local intake points, none with coordinates |
| Gauges | 1,670 | every USGS monitoring location that is not a well or spring; NWS gauges merge on the USGS id they publish (I2) |
| Watersheds | 35 | WBD HUC8 and HUC10 |

Rules specific to this phase:

- **GNIS ids are compared as numbers.** NHD zero-pads them (`01609456`) and GNIS does not
  (`1609456`). Read as text, every reach would fail to join its watercourse. After
  normalising, 1 GNIS id published by NHD has no GNIS record.
- **One reach of a named river is not the river.** The watercourse feature is the named
  stream; its reaches (stream and canal) are features of their own, linked by
  `REACH_OF_WATERCOURSE`.
- **OSM reservoirs never merge with NHD reservoirs.** No published identifier joins them, so
  each OSM reservoir inside an NHD polygon gets a candidate link instead
  (54 links).
- **Waterbody kind disagreements are kept.** Where NHD and GNIS classify the same named
  waterbody differently (lake against reservoir, for instance), a conflict records both.
- **Location gives watershed membership and gauges on waterbodies, nothing more.**
  18,141 placed features carry their HUC10; 73 lake gauges sit inside an NHD
  waterbody (`GAUGE_ON_WATERBODY`, `DERIVED_TOPOLOGICAL`). A gauge's reach on the stream
  network is not computed, because that needs network navigation, not distance.

Geometry is committed simplified (0.0003°, five decimals) in files of at most 2 MB:
`data/geo/streams/<huc8>.geojson`, `data/geo/pr_waterbodies.geojson` and
`data/geo/pr_watersheds.geojson`. Feature rows are split the same way, one file per type and,
for streams, per HUC8, so every file stays under the commit limit.

## Aquifer series and map (phase 4)

### Aquifer depth anomaly

On Monitoring, choosing an aquifer on a groundwater series adds the **aquifer depth anomaly**
(`GET /hydro/aquifer-series`). It is computed per request from the reading files on the
server; nothing is stored.

1. **Members.** The wells USGS assigns to the aquifer by code. An opt-in toggle adds wells that
   only sit inside the mapped outline, but never a well USGS assigns to a *different* aquifer,
   so the upper and lower North Coast Limestone aquifers are never pooled.
2. **Readings.** Parameter 72019 only (depth below land surface, feet). 62610 runs the other
   way and is counted and skipped. Each well's readings are reduced to a monthly median, and an
   approved value for a month wins over a provisional one.
3. **Baseline.** For each well and calendar month, the median of that well's whole approved
   record for that month, if it has at least **five** years. A well without one does not
   contribute.
4. **Anomaly.** The month's value minus the baseline, in feet; positive means deeper water than
   usual for that well.
5. **Aggregate.** The median across contributing wells, with quartiles and the well list,
   shown only when **three** or more wells contribute. Months where the set of wells changes
   are marked, because a step can be a change of membership. Provisional months form a
   separate series that is not drawn on the line.

It is not a water-table elevation and not a storage or volume estimate. Wells are not
weighted by area, and nothing alerts on it. A server without reading files (a fresh checkout,
CI) says so instead of drawing an empty line.

### Map workspace

The Monitoring page's map workspace, previously a placeholder, now draws only source
geometry:

- HA 730-N aquifers, coloured by class;
- HUC10 watersheds and NHD waterbodies;
- NHD stream reaches, loaded per HUC8 when the layer is turned on;
- located wells, coloured by monitoring state and ringed when USGS assigns an aquifer code;
- springs and gauges.

Features whose source publishes no location are never placed. A layer that fails to load is
reported on the page.

Building the map exposed a phase 1 defect: polygons with no class name had been written with
`NaN`, which is not JSON, so browsers rejected the whole aquifer file. Every writer now refuses
NaN, missing attributes are dropped, and a test parses every committed inventory file as
strict JSON.

## Water infrastructure and wetlands (phase 5)

| Feature type | Count | Sources and how it is built |
|---|---|---|
| Dams | 36 | USACE NID, keyed by NID ID; each dam within 500 m of a mapped NHD waterbody gets a `DAM_ON_RESERVOIR` candidate link (32 dams, 47 links) |
| Treatment plants | 1,762 | 114 PRASA filtration plants (placed) and 1,648 SDWIS treatment facilities (unlocated) |
| Wastewater plants | 114, range 89–114 | 51 PRASA plants and 63 NPDES publicly owned treatment works; 25 name-and-distance (≤ 500 m) candidates narrow the range |
| Pump stations | 2,112 | PRASA potable and sanitary pump stations |
| Tanks | 1,573 | 1,571 PRASA tanks and 2 SDWIS storage facilities |
| Non-PRASA water systems | 233 | FEMA Region 2's EPA sites, one point per community system, keyed by PWSID |
| Wetlands | 7,960 | NWI estuarine/marine, freshwater emergent and forested/shrub wetlands |
| Wells, intakes, reservoirs, springs, waterbodies | + 260, + 138, + 8, + 5, + 1,673 | PRASA wells, intakes and reservoirs; SDWIS springs; NWI ponds and lakes |

Rules specific to this phase:

- **Publishers that share no id never merge.** PRASA, EPA and USACE publish no common
  facility identifier. PRASA wells, intakes and wastewater plants get name-and-distance
  candidates against the other publishers' placed features (wells ≤ 150 m, intakes ≤ 300 m,
  wastewater plants ≤ 500 m). Unlocated SDWIS facilities get name-only candidates (I5,
  exact normalised name) against PRASA facilities of the same type.
- **A community system's location is not a facility's.** SDWIS facilities whose PWSID matches
  a FEMA/EPA site link to that system (`FACILITY_OF_SYSTEM`, I1, 498 links). The system's
  point is never copied onto the facility, which stays unlocated.
- **NWI ponds are not NHD lakes.** 534 NWI ponds and lakes inside an NHD waterbody polygon are
  I5 candidates; they do not narrow the waterbody range.
- **Canals are flowlines.** NHD FType 336 reaches are claimed as `canal`. Their geometry stays
  in the stream tiles and is drawn grey.
- **Exclusions are counted, not dropped.** 71 PRASA offices; 2,757 NPDES permittees that are
  not publicly owned treatment works; 2 FEMA rows with no id; NWI riverine polygons (5,621,
  represented by the reaches), deepwater (1,068), untyped (21) and outside the Puerto Rico
  watersheds (14). The PRASA pipe-network layers (about 335,000 segments) and SDWIS
  distribution entries are outside the hydrologic scope and are not read.
- **Sources that could not be used are named in the receipt** (`residue_sources`):
  `sige.pr.gov` and `geoserver2.pr.gov`, unreachable; EPA's "Non PRASA Pseudo Locations",
  excluded because its own description says *"The locations DO NOT represent actual Non PRASA
  locations"*; OpenStreetMap, not official.
- **Count disagreements are shown.** Wastewater plants (PRASA 51, NPDES 63), treatment plants
  (PRASA 114, SDWIS 1,648) and reservoirs (NID 36 dams, PRASA 8, NHD 798 polygons) are
  conflicts with no single feature. 31 PRASA rows typed `Tanque` carry the abbreviation
  `WTP`; they are listed as tanks and the disagreement is recorded.
- **Discovery lists are checked against the registry, not added.** All 17 PREPA dams named in
  the FEMA DR-4339 FAASt project sites are NID dams. The list spells one of them "Luchetti";
  NID publishes "Lucchetti" (also "Yauco Dam").

NWI geometry is committed simplified (0.0003°, five decimals) as `data/geo/wetlands/<huc8>.geojson`;
the largest tile is 1.3 MB. The PRASA facility points are shown with their vintage on the page
and the map.

## Identity: when two claims are one feature

| Tier | Evidence | Effect |
|---|---|---|
| I1 | The same authority identifier: one USGS site number seen through the Water Data API, the Water Quality Portal `USGS-…` id, and the existing `USGSGW_`/`USGSFM_`/`USGSWQ_` assets | merge |
| I2 | One source publishes another's identifier | merge |
| I3 | The same dataset in a newer release | merge |
| I4 | Compatible names **and** within 150 m (wells), or a written analyst name equivalence (aquifers) | candidate link only |
| I5 | Proximity only | candidate link only, and it does not move the range |

Names are compared by containment of distinguishing words, never by overlap, so
"Toa Baja" does not match "Toa Alta". The rules that keep this honest are below.

- **Municipio names are dropped before comparing.** Two Guánica wells share that word and
  nothing else.
- **Numbers are kept, and Roman numerals are read as numbers.** Well 4 is not well 5.
- **Road addresses are never names.** The Puerto Rico EQB stations in the Water Quality
  Portal put an address in the name field ("ROAD #103 KM 3.8") and the well's name in the
  identifier (`PREQB_GW-CABO ROJO II`), so the identifier is used for them.
- **No aquifer claims merge.** No source publishes an identifier that crosses USGS map
  classes, USGS aquifer codes and DRNA units.

So "North Coast Limestone upper aquifer" appears three times: as an HA 730-N class, a USGS
code, and a PIRA unit. They are joined by candidate links. The range's low figure merges
them; the high figure does not.

## Links

| Link | Meaning | Edge class |
|---|---|---|
| `WELL_IN_AQUIFER` from a USGS aquifer code | USGS assigned the well to that aquifer | `AUTHORITATIVE` |
| `WELL_IN_AQUIFER` from location | the well is inside the HA 730-N polygon | `DERIVED_TOPOLOGICAL` (the map says nothing about screen depth) |
| `AQUIFER_WITHIN` | a local USGS code sits under a national one, from co-assignment on the same sites | `AUTHORITATIVE` |
| `CODED_WELLS_WITHIN_POLYGON` | wells carrying a USGS code fall inside a map polygon (this is how unnamed alluvial polygons can be named later) | `DERIVED_TOPOLOGICAL` |
| `CANDIDATE_SAME_FEATURE` | possible same feature, never merged | `CANDIDATE` |

Upper and lower North Coast Limestone polygons are never treated as candidates for each
other, and the lower aquifer underlies the upper one. That is why polygon membership is
derived, and why coded membership is the default everywhere.

## Disagreements kept

| Attribute | What the sources say |
|---|---|
| South Coast aquifer units | USGS: one aquifer (HA 730-N class 114, national code N300STHCST). PIRA 2016: "No existe lo que comúnmente se refiere como el 'Gran Acuífero del Sur'. Cada valle aluvial forma un acuífero independiente" (PDF p. 113). |
| Mona and Culebra | HA 730-N text: "the islands of Mona and Culebra lack any significant aquifers". The same release maps alluvial and volcanic aquifer polygons on Culebra, and USGS has aquifer codes for two Mona units. |
| North Coast area | HA 730-N: "nearly 700 square miles". PIRA 2016: about 905 mi². The polygons, as computed here, give a third figure. |
| Same well, different place | 12 USGS sites where the Water Data API and the Water Quality Portal locations are more than 100 m apart. They are all about 225 m apart, close to the NAD27 versus Puerto Rico 1940 offset measured on the polygons, which suggests one service converted those sites' original datum differently. That is an inference; neither source says so. |
| HA 730-N datum | See below. This is the only disagreement resolved, by measurement. |

## Datum (load-bearing)

The HA 730-N `.prj` declares NAD27. Read that way, the island's outline sits a median 241 m
from the Census coastline, with a systematic **210 m northward offset**. Read as Puerto
Rico 1940 (EPSG:4139), the median is 26 m and the north–south offset 2 m.

`scripts/ingest_hydro_aquifers.py` measures both readings on every run. It uses Puerto Rico
1940, refuses any transformation with no stated accuracy (PROJ's "ballpark" offsets), and
fails if the median coastline distance is not under 100 m.

An independent check agrees: 138 of the 145 wells USGS codes to the South Coast aquifer
fall inside the South Coast polygon.

Simplification (0.0003°, five decimals) changes no class's area by more than 0.7%; the run
fails above 2%.

## Monitoring state

Monitoring state is computed per request from the reading files on the server
(`groundwater_levels.jsonl`, `usgs_field_measurements_readings.jsonl`,
`usgs_continuous_readings.jsonl`):

- `MONITORED_NOW`: last groundwater reading within 400 days (one field-visit cycle);
- `HISTORICAL_ONLY`: older than that;
- `NO_DATA`: no reading on file for that well;
- `READINGS_ABSENT_ON_SERVER`: the server holds none of those files.

The reading files are gitignored, so a fresh checkout and CI show `READINGS_ABSENT_ON_SERVER`.
That is a property of the server, not of the wells, and the page says so.

## What was wired

| Piece | Path |
|---|---|
| Source registry and pins | `config/hydro_inventory_sources.v1.json` |
| Pure module: claims, identity, links, conflicts, ledgers, read side (stdlib only) | `src/aguayluz/hydro_inventory.py` |
| Aquifer ingest (needs the `[geo]` extra) | `scripts/ingest_hydro_aquifers.py` |
| Site ingest | `scripts/ingest_hydro_sites.py` |
| GNIS names ingest | `scripts/ingest_hydro_names.py` |
| Surface-water ingest (needs shapely) | `scripts/ingest_hydro_nhd.py` |
| Water-infrastructure ingest | `scripts/ingest_hydro_infrastructure.py` |
| Wetlands ingest (needs shapely) | `scripts/ingest_hydro_wetlands.py` |
| Builder, with `--check` | `scripts/build_hydro_inventory.py` |
| Claims, features, links, conflicts, receipts (committed) | `data/hydro/` |
| Aquifer polygons, WGS84 (committed) | `data/geo/pr_aquifers.geojson` |
| Stream, waterbody, watershed and wetland geometry (committed) | `data/geo/streams/`, `data/geo/pr_waterbodies.geojson`, `data/geo/pr_watersheds.geojson`, `data/geo/wetlands/` |
| API | `server/backend/hydro_inventory_api.py`: `/hydro/aquifer-series`, `/hydro/points.geojson`, `/hydro/geo/{name}.geojson`, `/hydro/stream-tiles`, `/hydro/inventory/summary`, `/hydro/features`, `/hydro/features/{id}`, `/hydro/aquifer-wells`, `/hydro/conflicts`, `/hydro/candidates`, `/hydro/aquifers.geojson` |
| Page | **Hydro Inventory** (`/hydro-inventory`, under Water & Weather): `dashboard/src/pages/HydroInventoryPage.jsx` |
| Monitoring | aquifer filter and aquifer depth anomaly (`dashboard/src/components/MonitoringCharts.jsx`, `AquiferSeriesChart.jsx`); map workspace (`HydroMapWorkspace.jsx` in `WaterMonitoringConsole.jsx`) |
| GUI-parity capability | `hydro-feature-inventory` in `.federation/gui-capabilities.json` |
| Tests | `tests/test_hydro_inventory.py`, `tests/test_ingest_hydro_sites.py`, `tests/test_ingest_hydro_names.py`, `tests/test_ingest_hydro_nhd.py`, `tests/test_ingest_hydro_infrastructure.py`, `tests/test_ingest_hydro_wetlands.py`, `tests/test_ingest_hydro_aquifers.py`, `tests/test_hydro_inventory_api.py`, `dashboard/src/pages/HydroInventoryPage.test.jsx`, `dashboard/src/lib/hydro-inventory-api.test.js`, `dashboard/tests/hydro-inventory.spec.mjs` |

Claims are stored with the fields every claim in a file shares written once per block. The
per-claim SHA-256 is kept as an index into the block's list of manifestations, which keeps
every file under the 5,120 KB commit limit. `read_claims` restores full claims.

## Known gaps

- **PRASA's production wells.** EPA SDWIS lists them without coordinates. PRASA's public
  layer places 260 PRASA wells, but it is a May 2020 snapshot and publishes no SDWIS id, so
  the two are linked by name only (I5 candidates). The SDWIS wells stay unlocated and are
  never bound to an aquifer by location.
- **PRASA facilities after May 2020.** The public layer is a snapshot; facilities built,
  retired or renamed since then are not reflected. A current copy is a records-request item.
- **Drinking-water treatment plants outside PRASA's layer.** SDWIS lists 1,648 treatment
  facilities without coordinates.
- **Irrigation canals at survey detail.** The Junta de Planificación canal layer
  (`sige.pr.gov`) could not be reached; NHD canal/ditch reaches stand in at coarser detail.
- **Gobierno de PR geoserver** (`geoserver2.pr.gov`, workspace `pr_geodata`, with PRASA and
  DRNA layers). The connection was reset on every attempt from the build environment.
- **Wetland mapping vintage.** NWI mapping for Puerto Rico is largely from 1980s imagery.
- **DRNA water-franchise registry.** No public registry was found.
- **DRNA and Junta de Planificación aquifer layers.** `sige.pr.gov` and `gis.otg.pr.gov`
  could not be reached from the build environment.
- **Names of the 98 HA 730-N alluvial-valley polygons.** The release labels them only by
  class. They are labelled here by the municipios they cover, and flagged as unnamed in the
  source.
- **Intakes.** EPA SDWIS lists 690 without coordinates; PRASA's 2020 layer places 138 PRASA
  intakes, linked to SDWIS by name only.
- **Gauge position on the stream network.** Gauges are placed in watersheds by location;
  their reach is not computed.
- **DRNA reservoir and embalse lists.** `sige.pr.gov` could not be reached.
- **Springs outside the public sources.** GNIS names only 2 springs in Puerto Rico and USGS
  monitors 221; no public spring registry was found.
- **USGS stratigraphic codes with no Puerto Rico well assigned.** Ten are listed in the
  receipt as known but not enumerated.

## Verifying a change

```bash
python -m pytest -q tests/test_hydro_inventory.py tests/test_ingest_hydro_*.py tests/test_hydro_inventory_api.py
python scripts/build_hydro_inventory.py --check       # committed outputs equal a rebuild
python scripts/ingest_hydro_sites.py --fetch --dry-run
python scripts/ingest_hydro_aquifers.py --fetch --dry-run   # needs .[geo]
python scripts/ingest_hydro_infrastructure.py --fetch --dry-run
python scripts/ingest_hydro_wetlands.py --fetch --dry-run   # needs shapely
python scripts/check_gui_parity.py
cd dashboard && npx vitest run src/pages/HydroInventoryPage.test.jsx src/lib/hydro-inventory-api.test.js
```
