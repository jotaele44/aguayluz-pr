# PR-IOM: infrastructure obsolescence, open-source baseline ledger (2026-11-25)

A dated snapshot. It opens the Puerto Rico Infrastructure Obsolescence Master (PR-IOM,
execution vector `PR-IOM-001`): an investigation into which obsolete components in the
electricity and water systems can be replaced, refurbished, remanufactured or retrofitted.
It records what public sources say about obsolete and hard-to-obtain components, what they
do not say, and what has to be requested.

**No request has been sent, and no component is classified as obsolete.** The
machine-readable package is in `research/pr_iom_v0_1/`: 48 sources with retrieval time,
SHA-256 where the source is a stable file, and a terminal state; a 30-step plan; a taxonomy;
an asset baseline; a coverage matrix; and 15 candidate component records. The record schema
is `schemas/pr-iom/v0.1/component_record.schema.json`; the checks are `tests/test_pr_iom.py`.

## Finding

The public record supports the investigation but does not yet contain a single component
shown to be out of production. Three things are established:

1. A part-level inventory of the thermal generation fleet is public: about 12,400 line
   items with equipment manufacturer and model, filed in June 2023. It records no alternate
   supplier for any line.
2. Parts are a recurring factor in long forced outages: in the last two reported quarters a
   part was needed to return the unit to service in 35 of 61 outages of 24 hours or more
   (57%).
3. The operator has named 15 specific equipment items as at "end of life" or "obsolete",
   by plant and unit, with no manufacturer, model or part number.

In the regulator's docket, "obsolete parts" mostly means warehouse stock awaiting disposal.
That is a different problem from equipment whose manufacturer stopped production, and the
two must not be counted together.

Nothing was found for hydroelectric equipment or for AAA pumping equipment, the two
priority areas.

## What is published

Read by the analyst in the hashed documents, at the page or sheet given. PREB is the Puerto
Rico Energy Bureau; Genera is the operator of the thermal generation fleet.

| Claim | Source | Page / sheet | Tier |
|---|---|---|---|
| "due to the age of the island's generation assets, finding replacement parts may require reverse engineering or long wait times, sometimes up to 2 years" (attributed to "some stakeholders") | GAO-26-107772 | PDF p. 32 | T1 |
| About $2.7 billion obligated to FEMA's FAASt equipment and materials project | GAO-26-107772 | PDF p. 32 | T1 |
| LUMA's energy management system "is composed of obsolete hardware and software"; $44 million obligated, 65 percent complete | GAO-26-107772 | PDF p. 40 | T1 |
| Spare-parts inventory by plant, unit, equipment OEM and model: 12,319 line items by its own summary; 4,269 with insufficient stock; $94.1 million of parts to order | Genera letter attachment, June 2023 (`PREB-MI20210014-F26`) | Summary Totals | T2 |
| Same workbook, analyst count: 12,409 part rows; OEM part number on 3,283 (26.5%); part manufacturer on 112 (0.9%); alternate supplier on none; 19 rows (0.15%) with obsolete / discontinued wording | `PREB-MI20210014-F26` | eight plant sheets | T2 |
| PREB asked for Genera's plan to "obtain needed parts that are obsolete or no longer available"; the answer describes auditing and writing off obsolete stock | Comment responses (`PREB-MI20210014-F25`) | comments 3, 7 | T2 |
| Q4 FY2026: 33 forced outages of 24 hours or more; a part was needed in 19 | `PREB-MI20210014-F02` | Outages 24h or more | T2 |
| Q1 FY2027: 28 such outages; a part was needed in 16, not needed in 11, pending in 1 | `PREB-MI20210014-F01` | Parts Availability 24h+ | T2 |
| Classification of warehouse inventory, including obsolete materials, "remains pending" three years after it was promised within six months | Q1 FY2027 report, 16 Nov 2026 (`PREB-MI20210014-F00`) | PDF p. 19–21 | T2 |
| Disposal procedure for unusable property sent to P3A on 7 Oct 2026; review pending, no timeline | `PREB-MI20210014-F00` | PDF p. 57 | T2 |
| "Critical Replacement Parts – FY 2024": 15 items described as end of life (14) or obsolete (1), including 1000 HP condenser circulating water pump motors said to be "unrepairable" and the Mayagüez control system | Anejo 1, Dec 2024 (`PREB-MI20240005-F31`) | PDF p. 1–8 | T2 |
| Obsolete equipment defined as "any working or in-service piece of … equipment that the manufacturer is no longer making"; recommends a "Spare Parts Availability" indicator in condition assessments | TVA OIG 2015-15265 | PDF p. 1–3 | T1 |
| Many water assets operate beyond expected useful life; availability of critical parts listed as a challenge | Water supply stabilisation plan, 2025 | PDF p. 26, 114 | T1 |

Tier T2 here means an operator's own statement filed with the regulator. It is a primary
record of what the operator said, not independent verification of the equipment's condition.

## What is not published

- The manufacturing status of any component: whether the maker still produces it, has a
  successor part, or still exists.
- Manufacturer, model or part number for any of the 15 end-of-life items.
- Whether a needed part was in stock, how long it took to arrive, or what it cost, for any
  outage.
- Which parts were reverse-engineered. GAO reports the practice; no filing read names a case.
- Any equipment inventory for the hydroelectric plants or for AAA pump stations and
  treatment plants.
- Capacity lost to specific components, as opposed to outage hours per unit.

## Contradictions

- **Two meanings of "obsolete".** The docket's "Managing Obsolete Parts" section concerns
  surplus stock to be written off. GAO and the December 2024 annex concern installed
  equipment that is hard to replace. PREB's own question asked about both; the answer
  addressed only the first.
- **Line-item count.** The June 2023 workbook's summary gives 12,319 line items; counting
  rows gives 12,409. The 90-row difference is unexplained and may be the counting rule.
- **End of life versus obsolete.** Fourteen of the 15 items are called "end of life", which
  is wear. Only the Mayagüez control system is called "obsolete". The proposal's premise
  that these are obsolescence cases is unverified for all 15.
- **Approvals for disposal.** Genera said no approvals were pending, having earlier said
  disposal awaited PREB and P3A; PREB asked it to explain (PDF p. 57 of the 16 Nov 2026 report).
- **Filing date of "Attachment 13 – Spare Parts.xlsx".** The proposal gives 30 September
  2026; the file sits in the site's October 2026 upload folder. The filing date was not
  verified.
- **TVA summary page versus report.** A search summary reported the public summary page as
  saying "No recommendations"; the report PDF contains two. The PDF was read; the page was not.

## Confidence

| Statement | Confidence | Basis |
|---|---|---|
| A public part-level inventory of the thermal fleet exists | High | Workbook read; eight sheets, consistent columns |
| Parts were needed in over half of long forced outages in the last two quarters | High | Two operator workbooks, counted directly; 19 of 33 and 16 of 28 |
| Parts were *unavailable* in those outages | Low | Not stated in either workbook |
| The 15 listed items are worn out | Medium | Single operator source, unverified, two years old |
| Any of the 15 is out of production | Low | No source says so |
| Replacement parts sometimes need reverse engineering or waits up to two years | Medium | GAO reports it as stakeholder testimony, without cases |
| The inventory records no alternate suppliers | Medium | Column empty in all rows by position; rows not read one by one |
| Hydro and AAA equipment has an obsolescence problem | Not assessed | No source retrieved |

## Request mechanics

No request is drafted in this package. The legal mechanics for Puerto Rico public-records
requests are recorded in
[`PRASA_PRODUCTION_OSINT_LEDGER_2026-11-14.md`](PRASA_PRODUCTION_OSINT_LEDGER_2026-11-14.md)
and apply here unchanged. Genera is a private operator under contract; records it holds are
most directly reached through the PREB dockets or through PREPA and P3A as public bodies.
That routing was not verified.

## Likelihood

Analyst estimates, not measured base rates.

| Lead | Estimated chance of obtaining it |
|---|---|
| Manufacturer and model for the 15 items, via a PREB information requirement or a request to PREPA | 40–55% |
| Current fleet spare-parts inventory with supplier data, beyond what is on the docket | 30–45% |
| List of parts reverse-engineered or bought from non-OEM sources, with lead times | 20–35% |
| Hydroelectric plant equipment inventory from PREPA | 25–40% |
| AAA pump-station equipment inventory (motor and pump make, model, age) | 30–45%; AAA has cited sensitivity before |
| FEMA / COR3 scopes of work naming equipment | 50–65%; partly public already, not retrieved here |

## Blind spots

- Two retrieved filings were hashed but not read: an 879-page PDF (August 2024) and a
  legacy-format spreadsheet (November 2025). Twenty-two others were only keyword-scanned.
- Only filings whose title or file name mentions spare parts or consumables were swept, out
  of 210 and 400 document links on the two dockets.
- The June 2023 inventory was counted by column, not read row by row. It may be superseded.
- `www.gao.gov` and `fema.gov` refused automated retrieval; the GAO report was obtained from
  `files.gao.gov`. The FEMA funding note was not read.
- No AAA, COR3, PREPA procurement, Comptroller or manufacturer source was retrieved. No
  EPRI document was identified.
- The repository has facility rows, not unit or equipment rows. The Aguirre combined-cycle
  plant and most peaker sites have no asset row, so five records bind to nothing.
- The "Hydroelectric Master" and the electrical ownership and control investigation that
  the proposal builds on are not in this repository.
- Press reports of AAA pump repairs needing parts ordered from the mainland (La Plata, 2026)
  surfaced in search results only and were not read.

## Vector status

Active vector: `PR-IOM-001`. Not exhausted.

- Phase 00 (baseline): taxonomy done at v0.1; inventories, asset universe and historical
  claims partial.
- Phase 01 (acquisition): Genera inventories and PREB records partial; four steps open.
- Phases 02–05: open. No identification, alternatives, economics or qualification work has
  been done.

Of 48 sources: 7 exhausted, 30 partial, 2 superseded, 3 blocked, 6 not attempted.

## Queued

Logged, not started.

- Read the two unread filings and the 22 keyword-scanned ones; sweep the remaining docket
  filings.
- Read the June 2023 inventory row by row and extract the 19 rows marked obsolete.
- Locate AAA procurement records and COR3 / FEMA equipment scopes.
- Hub registration: an ownership proposal in thehub-pr (policy authority there, registry
  here), status proposed.
- Spatial binding in spiderweb-pr: its hub-facing types have no asset or component values
  and its reader for this repository's exports does not cover power assets.
- Economics (Phase 04) belongs with moneysweep-pr; docket monitoring with centinelas-pr.
- Engineering review requirements (step 27) need a licensed engineer.
