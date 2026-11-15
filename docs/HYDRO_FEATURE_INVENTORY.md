# Puerto Rico hydrologic feature inventory

## Why

The repository monitored groundwater as individual USGS wells. It had no aquifer as an
entity, no way to say which aquifer a well draws from, and no account of wells that only
other agencies list. The goal set for this work was to include every known aquifer, well,
spring and stream, and to reflect what is known rather than what any one source says.

This document covers **phase 1** (aquifers and wells), **phase 2** (springs) and **phase 3**
(streams, named watercourses, waterfalls, waterbodies, reservoirs, intakes, gauges and
watersheds). Every feature type is now enumerated. Phase 4 (an aquifer-level series and the
map workspace) adds no new feature type. The receipt's `phase_scope` names them as
not enumerated, and the page says so.

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

All sources, URLs and pins are in `config/hydro_inventory_sources.v1.json`.

## Springs (phase 2)

223 spring features: the 221 USGS spring sites (each joined to its Water Quality Portal copy
by site number) and the 2 springs GNIS names in Puerto Rico. No GNIS spring lies within
150 m of a USGS spring, so there are no candidate pairs and the count is not a range.

Each spring is linked to the HA 730-N polygon it sits in (`SPRING_IN_AQUIFER`,
`DERIVED_TOPOLOGICAL`). None of the 221 USGS springs carries a USGS aquifer code.

This is a small number for an island with extensive karst. It is what the public sources
enumerate, not an estimate of how many springs exist; springs known only from speleological
or local records are listed as a known gap.

## Surface water (phase 3)

| Feature type | Count | How it is built |
|---|---|---|
| Stream reaches | 15,881 | every NHD flowline that is not coastline, keyed by its NHD permanent identifier |
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
  stream; its 15,881 reaches are features of their own, linked by
  `REACH_OF_WATERCOURSE`.
- **OSM reservoirs never merge with NHD reservoirs.** No published identifier joins them, so
  each OSM reservoir inside an NHD polygon gets a candidate link instead
  (54 links).
- **Waterbody kind disagreements are kept.** Where NHD and GNIS classify the same named
  waterbody differently (lake against reservoir, for instance), a conflict records both.
- **Location gives watershed membership and gauges on waterbodies, nothing more.**
  11,884 placed features carry their HUC10; 73 lake gauges sit inside an NHD
  waterbody (`GAUGE_ON_WATERBODY`, `DERIVED_TOPOLOGICAL`). A gauge's reach on the stream
  network is not computed, because that needs network navigation, not distance.

Geometry is committed simplified (0.0003°, five decimals) in files of at most 2 MB:
`data/geo/streams/<huc8>.geojson`, `data/geo/pr_waterbodies.geojson` and
`data/geo/pr_watersheds.geojson`. Feature rows are split the same way, one file per type and,
for streams, per HUC8, so every file stays under the commit limit.

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
| Builder, with `--check` | `scripts/build_hydro_inventory.py` |
| Claims, features, links, conflicts, receipts (committed) | `data/hydro/` |
| Aquifer polygons, WGS84 (committed) | `data/geo/pr_aquifers.geojson` |
| Stream, waterbody and watershed geometry (committed) | `data/geo/streams/`, `data/geo/pr_waterbodies.geojson`, `data/geo/pr_watersheds.geojson` |
| API | `server/backend/hydro_inventory_api.py`: `/hydro/inventory/summary`, `/hydro/features`, `/hydro/features/{id}`, `/hydro/aquifer-wells`, `/hydro/conflicts`, `/hydro/candidates`, `/hydro/aquifers.geojson` |
| Page | **Hydro Inventory** (`/hydro-inventory`, under Water & Weather): `dashboard/src/pages/HydroInventoryPage.jsx` |
| Monitoring | aquifer filter on the groundwater series in `dashboard/src/components/MonitoringCharts.jsx` |
| GUI-parity capability | `hydro-feature-inventory` in `.federation/gui-capabilities.json` |
| Tests | `tests/test_hydro_inventory.py`, `tests/test_ingest_hydro_sites.py`, `tests/test_ingest_hydro_names.py`, `tests/test_ingest_hydro_nhd.py`, `tests/test_ingest_hydro_aquifers.py`, `tests/test_hydro_inventory_api.py`, `dashboard/src/pages/HydroInventoryPage.test.jsx`, `dashboard/src/lib/hydro-inventory-api.test.js`, `dashboard/tests/hydro-inventory.spec.mjs` |

Claims are stored with the fields every claim in a file shares written once per block. The
per-claim SHA-256 is kept as an index into the block's list of manifestations, which keeps
every file under the 5,120 KB commit limit. `read_claims` restores full claims.

## Known gaps

- **PRASA's production wells.** EPA SDWIS lists them without coordinates. They are in the
  inventory as unlocated wells, never placed on a map and never bound to an aquifer by
  location.
- **DRNA water-franchise registry.** No public registry was found.
- **DRNA and Junta de Planificación aquifer layers.** `sige.pr.gov` and `gis.otg.pr.gov`
  could not be reached from the build environment.
- **Names of the 98 HA 730-N alluvial-valley polygons.** The release labels them only by
  class. They are labelled here by the municipios they cover, and flagged as unnamed in the
  source.
- **PRASA's intakes.** EPA SDWIS lists 690 without coordinates; they are listed, not
  placed.
- **Gauge position on the stream network.** Gauges are placed in watersheds by location;
  their reach is not computed.
- **DRNA reservoir and embalse lists.** `sige.pr.gov` could not be reached.
- **Springs outside the public sources.** GNIS names only 2 springs in Puerto Rico and USGS
  monitors 221; no public spring registry was found.
- **USGS stratigraphic codes with no Puerto Rico well assigned.** Ten are listed in the
  receipt as known but not enumerated.

## Verifying a change

```bash
python -m pytest -q tests/test_hydro_inventory.py tests/test_ingest_hydro_sites.py tests/test_ingest_hydro_aquifers.py tests/test_hydro_inventory_api.py
python scripts/build_hydro_inventory.py --check       # committed outputs equal a rebuild
python scripts/ingest_hydro_sites.py --fetch --dry-run
python scripts/ingest_hydro_aquifers.py --fetch --dry-run   # needs .[geo]
python scripts/check_gui_parity.py
cd dashboard && npx vitest run src/pages/HydroInventoryPage.test.jsx src/lib/hydro-inventory-api.test.js
```
