# PRASA production: open-source ledger before a public-records request (2026-11-14)

A dated snapshot. It records what open sources publish about Puerto Rico Aqueduct and
Sewer Authority (PRASA; in Spanish AAA) drinking-water production by source and by
facility, what they do not, and the request drafted from the difference.

**No request has been sent.** The draft is
[`prasa_production/solicitud_informacion_publica_v0.1.md`](prasa_production/solicitud_informacion_publica_v0.1.md).
The machine-readable inventory is in `research/prasa_production_osint_v0_1/`: 45 sources
with retrieval time, SHA-256 where the source is a stable file, and a terminal state; and a
coverage matrix of the twelve metrics wanted.

## Finding

Per-facility production records exist and are not published. Island-wide annual totals
are published and consistent across PRASA's own documents. The split between filtration
plants and wells is published only as a rounded share with no method.

## What is published

Read by the analyst in the hashed documents, at the PDF page given.

| Claim | Source | Page | Tier |
|---|---|---|---|
| FY2024 production 513 MGD, "approximately 88% or 453 MGD are from WTPs" | Consulting Engineer's Report (CER) FY2024, Arcadis, §4.2.2.2 | 63–64 | T2 |
| FY2023 production 513 MGD, "approximately 88% or 454 MGD" | CER FY2023 | 56 | T2 |
| FY2025: 507.10 MGD (summary, Table 4-14) **and** 496 MGD, "88% or 437 MGD" (§4.2.2.2) | CER FY2025 | 28, 93, 63 | T2 |
| Production FY2020–FY2024: 541, 551, 519, 513, 513 MGD | CER FY2024 Table 4-16 | 86 | T2 |
| FY2019 542 MGD, about 487 from plants; FY2020 539 / 485; FY2021 551 / 494 | CER FY2019, FY2020, FY2021 | 59, 58, 59 | T2 |
| FY2018 total 507 MGD; plants about 455 (FY2017) and 466 (FY2018) | CER FY2018 | 25, 23 | T2 |
| FY2014 598, FY2015 557, FY2016 508 MGD produced | CER FY2014, FY2015, FY2016 | 65, 79, 95 | T2 |
| Annual production FY2019 541.7, FY2024 513.2 MGD | 2025 Certified Fiscal Plan, Table 1-2 | 37 | T1 |
| FY2023 annual production 513.09 MGD | 2024 Certified Fiscal Plan | 31 | T1 |
| Surface sources "supply nearly 90% of PRASA's treated water … remaining 10% … approximately 250 active wells" | 2025 Certified Fiscal Plan | 88 | T1 |
| 104 plants of up to 10 MGD average 165 MGD in total; 4 plants of 10–20 MGD, 58 MGD | 2025 Certified Fiscal Plan | 75 | T1 |
| 112 plants (design about 570 MGD), 244 wells, 136 intakes; about 168 systems, 109 surface and 59 groundwater | CER FY2024 | 39, 62, 63 | T2 |
| "In fiscal year 2020, only 58% of the island's production was being measured" | Strategic Plan 2026–2029 | 33 | T1 |
| PRASA-reported 2013 production 617.0 MGD against a DRNA estimate of 588.7 | DRNA PIRA 2016 | 179 | T1 |
| PRASA south-coast wells 21.57 mgd in 2014; Salinas 3.96, Santa Isabel 6.47 | DRNA PIRA 2016 | 282 | T1 |
| Withdrawals by public water system, surface and groundwater: 545.06 (2017), 593.21 (2018), 589.99 (2019), 601.74 (2020) Mgal/d | USGS 10.5066/P9HWON2W, Table 2 of each year | TOTAL row | T1 |

This settles a point left open in [`WATER_USE_INTEGRATION.md`](WATER_USE_INTEGRATION.md):
the figure "513 Mgal/d in fiscal year 2024, about 88% from filtration plants" is **confirmed**
in PRASA's engineering report. That document's own table should be updated when this ledger
is merged.

## What is not published

Twenty PRASA investor documents (every engineer's report from FY2010 to FY2025, the
supplemental reports and the 2020 offering memorandum) were text-scanned for per-facility
production tables. None has one.

1. Production per filtration plant, at any time step.
2. Extraction per well.
3. Production by operational region. Only telemetry coverage by region is public.
4. Design capacity per plant and per well, beyond the island total and size tiers.
5. Which intake feeds which plant.
6. Which facilities are metered, and the size of the "metering-error adjustment" footnoted
   in the production tables.
7. The water-balance audit worksheets behind the published summary.
8. The method behind the 88% plant share.
9. The 2024 Master Plan.

Two sources show the records exist:

- **USGS**, on the 2020 data release: "Daily raw-water inflow volume to each PRASA
  water-treatment plant and water pumped from PRASA public-supply wells on the island in
  2020, as well as coordinate information for these facilities were provided by PRASA. The
  raw data are not publicly available owing to restrictions (sensitivity concern). Contact
  PRASA directly for more information."
- **Puerto Rico Institute of Statistics** lists an AAA product, "Extracciones de agua cruda y
  producción", with no history; its one data link (`acueductos.pr.gov/INFORMESESTADISTICOS/`)
  returned HTTP 404 on 2026-11-14.

## Contradictions

- **FY2025 total.** 507.10 MGD and 496 MGD in the same report. Unresolved; the request asks
  for the supporting record.
- **Plant share.** About 90% for FY2019–FY2021 (487/542, 485/539, 494/551), then
  "approximately 88%" for FY2023, FY2024 and FY2025, with plant volumes that are exactly 88%
  of each total. A share that does not move across three years while the total does reads
  as a carried assumption. That is an inference; no document says so.
- **Plant capacity.** About 625 MGD in the FY2023 report and about 570 MGD a year later, with
  the same count of plants and no explanation.
- **Withdrawal against production.** USGS 2020 withdrawals (601.74) exceed PRASA FY2020
  production (539–541). They measure different things — raw water taken, including
  non-PRASA systems, against finished water — on different year bases. They must not be
  compared as one series.
- **Metering.** With 58% of production metered in FY2020 and PIRA 2016 finding production
  meters over-read, per-facility records before about 2021 may be partly estimated.

## Confidence

| Statement | Confidence | Basis |
|---|---|---|
| Island production was about 513 MGD in FY2023 and FY2024 | High | Engineer's report, two fiscal plans and a transition statement agree |
| Per-facility production records exist | High | USGS states it received them |
| Groundwater supplies about a tenth of production | Medium | Rounded shares in PRASA documents; USGS withdrawals give 10.8% for 2020 |
| The 88% share is measured, not assumed | Low | No method; constant across three years |
| FY2025 production | Low | Two published values |

## Request mechanics

Read in the Department of State certified text of Ley 156-2025, which amends Ley 141-2019
and is hosted by PRASA itself.

- **Addressing (Art. 6).** Notify the agency head with copy to the Oficial de Información.
  A request not so notified is defective and does not start the clock. It must give a postal
  and an email address.
- **Deadline (Art. 7).** 20 business days for a record of up to 300 folios or less than three
  years old; 30 otherwise; one extension of 20 if requested within the first term with a
  reason. Silence is a denial. A denial must state its legal grounds in writing.
- **Scope (Arts. 2.1, 4, 8).** Information already published free on official sites is
  outside the process. The agency need not create a record that does not exist. Formats are
  paper, PDF, URL or inspection, and an existing record must be given in the format asked
  for where it exists in that format.
- **Remedy (Art. 9).** Recurso Especial in the Tribunal de Primera Instancia, San Juan,
  within a strict 30 days; no filing fees; no lawyer required.
- **Recipients.** PRASA's transparency page names three information officers and gives the
  postal and physical addresses. It gives no email for them.

## Precedent

Reported by the sweep; the ruling was not re-read by the analyst.

- *Comisión Ciudadana para la Auditoría Integral del Crédito Público v. AAA*, Court of
  Appeals KLCE202300762 (19 Sept 2023): a 2022 request for financial records met generic
  objections and a web link; full disclosure in digital form was ordered after about eleven
  months. It predates the 2025 amendment.
- No earlier request for production data was found.

## Likelihood

Analyst estimates, not measured base rates.

- Per-facility monthly volumes released on request: **35–50%**. Down from the 40–55% given in
  `WATER_USE_INTEGRATION.md`, because PRASA has already invoked "sensitivity" with USGS and
  litigated the one precedent found.
- Partial release (regional or by system, capacities, water-balance worksheets): **60–75%**.
- A reply or extension within the statutory term: **45–60%**.

## Blind spots

- `web.archive.org` could not be reached, so an archived copy of the AAA statistics page may
  exist unseen. This is the most likely place for already-public per-facility data.
- `emma.msrb.org` was not searchable from here. The 2020 offering memorandum hosted by PRASA
  was read instead and repeats the engineer's report.
- The Comptroller's audit database, PIRA 2008 and the 2023 consent-decree modification were
  not read.
- Whether the Metro-region supply diagram in the 2025 AAFAF plan shows capacity or output
  was not determined.
- Who presides PRASA today, and whether PRASA has an internal regulation on these requests,
  were not verified.
- The SDWIS facility counts identify PRASA by its switchboard number (155 systems found
  against 160 reported by the Department of Health).

## Vector status

Structural analysis, evidence expansion, contradiction testing, confidence scoring and
blind-spot identification are recorded above. Every source is in a terminal state: 37
exhausted, 4 holding nothing on the question, 2 unavailable, 2 blocked. The open-source
vector is exhausted to the extent this environment allows; the two blocked sources are
named so they can be checked from another network before sending.

## Queued

- Ingest of the USGS per-system tables (2017–2020), the island production series and the
  SDWIS facility registry.
- A separate request to DRNA for PRASA's water-franchise records.
