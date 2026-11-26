# WATER_HEALTH 463-control — PRDOH public-records acquisition specification

## Purpose

Request the authoritative public-water-system inventory maintained by the Puerto Rico Department of Health (PRDOH), Drinking Water Section / Public Water Supply Supervision Program (PWSS), needed to reproduce and audit the September 2025 control denominator of **463 regulated public water systems**.

The PRDOH 2025 Annual Violations Report states that, as of September 2025, the Drinking Water Section regulated **463 systems**. The same report gives **160 PRASA systems** and **303 Non-PRASA systems**, with the Non-PRASA group composed of **241 community systems (CWS), 54 non-transient non-community systems (NTNCWS), and 8 transient non-community systems (TNCWS)**.

## Records requested

Please provide, preferably in CSV, XLSX, database-export, or another machine-readable format:

1. The complete inventory of all public water systems regulated by PRDOH **as of September 30, 2025**.
2. The complete inventory current **as of October 8, 2026**, or the exact inventory manifestation used to support the PWSS webpage stating 463 current systems.
3. The system-membership/status change history from **September 1, 2025 through October 8, 2026**, including activations, deactivations, mergers, splits, changes from public to non-public, ownership/operator classification changes, or PWSID changes.

For each system, please include every field maintained by PRDOH that identifies or classifies the system, including where available:

- PWSID or other stable PRDOH system identifier
- system name
- PRASA / Non-PRASA classification
- regulatory system type (CWS, NTNCWS, TNCWS)
- active/status code
- effective/activation date
- deactivation/end date
- predecessor/successor PWSID for mergers, splits, or identifier revisions
- PRDOH region
- population served
- primary source-water type

## Denominator controls

The September 2025 manifestation should reproduce:

- **463 total systems**
- **160 PRASA**
- **303 Non-PRASA**
- Non-PRASA: **241 CWS + 54 NTNCWS + 8 TNCWS = 303**

Please preserve the original system identifiers and values rather than substituting normalized names.

## Reason for requesting the change history

EPA SDWIS currently exposes a later 2026Q3 Puerto Rico inventory with 464 active systems. Because that is a different reporting period, the requested PRDOH change history is needed to determine the exact identity/status difference without inferring membership from counts, system names, PWSID prefixes, ownership codes, telephone numbers, or geographic proximity.
