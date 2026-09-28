# Blockers and unblock plan — aguayluz-pr (2026-09-28)

**Audit date:** 2026-09-28 · **`main` at audit:** `7e11961` (not branch-protected) · **Production status:** `PRODUCTION_REAL_DATA_PARTIAL`

**Post-audit update (2026-09-28 20:35Z):** the record_cell_binding v0.2 series was pushed straight to `main` after the audit. The Cell_Set PR #299 now conflicts with `main` and is superseded (X-05). The same series left `ruff check .` red on `main` (X-10); this PR carries the one-line fix.

This document lists every blocker that the repository, its CI, and its GitHub issues and pull requests recorded as of the audit date, then gives an ordered plan to clear them. It changes no code, gate, ledger, or status file.

Cross-repository blockers (IDs `X-nn`) are described in full in
`jotaele44/thehub-pr` → `docs/BLOCKERS_AND_UNBLOCK_PLAN_2026-09-28.md`.

## How this inventory was built

Sources checked:

- all 8 open issues and all 10 open pull requests;
- CI on `main`, for push and scheduled runs;
- per-PR check results from the thehub federation completion-gate artifact (run `36326861596`, 2026-09-27 14:42Z);
- `docs/unfinished_implementation_ledger.v1.json`, reconciled against PR history;
- `docs/ROAD_TO_100.md`, `docs/ROAD_TO_100_NORMALIZED.md`, `docs/REALTIME_DATA_AUDIT_2026-09-23.md`, `AUDIT.md`;
- `.github/actions-restoration-notice.md`;
- thehub `docs/FEDERATION_MAX_AUDIT_2026-09-24.md` and `docs/FEDERATION_UI_OPERATIONS_FAILURE_LEDGER.csv`;
- the branch list and branch protection.

## Summary

Each blocker is counted once, under its primary type.

| Type | Count |
|---|---:|
| CI (red now) | 1 |
| GATE | 3 |
| CRED | 1 |
| DATA | 4 |
| IMPL | 1 |
| PR | 1 group (10 PRs) |
| STALE | 1 |
| **Total** | **12** |

## Blocker inventory

| ID | Blocker | Type | Evidence | Owner | Unblock step | Exit criterion |
|---|---|---|---|---|---|---|
| AY-01 | The scheduled `refresh` workflow fails whenever data changes | CI | `refresh.yml` (every 15 minutes) failed on 26 of its last 83 runs, most recently run `36366895263` on 2026-09-28. The step "Promote refreshed snapshot to Floot" (`.github/workflows/refresh.yml:110-118`) curls `https://aguayluz-pr.floot.app/_api/sync/github`, which fails with `SSL routines::sslv3 alert handshake failure` (exit 35). The data commit has already been pushed, but the next step, "Notify Hub of new export (repository_dispatch)" (`:126`), is skipped, so the Hub is never notified. `archive/floot-export-2026-09-12` and `reconcile/floot-archive-2026-09-12` exist in every federation repo, which suggests the Floot deployment was retired. | Agent/maintainer | Confirm Floot's status. If retired, delete the step. Otherwise make it non-fatal (`continue-on-error`) and move it after the Hub dispatch. | Refresh runs green, and the dispatch fires on every data change |
| AY-02 | Bot refresh commits keep every aguayluz PR behind `main` | GATE | 10 of the 14 commits to `main` since 09-26 are `chore: scheduled refresh … [skip ci]`. The thehub completion gate classifies any PR whose base is not the current `main` as `REBASE_REQUIRED`, so aguayluz PRs cannot stay current (X-01). | Maintainer (thehub gate owner) | Fix the gate rule (X-01), or batch data commits or move them to a data branch | Aguayluz PRs stop being classified actionable purely because of bot drift |
| AY-03 | NEON live certification is blocked | CRED | #220 P0 needs `NEON_API_TOKEN` replaced or repaired "only in the authorized runtime secret store", then a bounded live smoke with HTTP 200 and an exact D04 site set. `neon-live-smoke.yml` runs on `workflow_dispatch` or PR only. P1–P4 (unit identity, deferred products, provider plane, tombstones) follow. | Operator, then agent | Repair the token, dispatch the smoke, keep the receipt; then implement P1 → P4 | `AGUAYLUZ NEON INTEGRATION CERTIFIED` gates in #220 pass |
| AY-04 | No authorized live outage feed | DATA | Ledger AYL-006. Outage attribution rests on a 2025-03-03 point-in-time snapshot (`docs/ROAD_TO_100_NORMALIZED.md`). MiLUMA acquisition is ToS/WAF gated (thehub UI-ops ledger F013). `aguayluz.fetch_luma_live` stays `BLOCKED_UNTIL_TOS_AND_LIVE_SOURCE_CERTIFIED`. | External (utility / data authority) | Data-sharing agreement or authorized per-municipio feed | Reproducible authorized feed with lifecycle records |
| AY-05 | No direct current measurements for Laguna Cartagena | DATA | Ledger AYL-007. `direct_current_observations = 0`; `current_condition.status = unknown` | External | Keep fail-closed; admit only eligible direct measurements | At least one eligible direct measurement admitted |
| AY-06 | Live verification of the ten USGS categories | DATA (operator run) | Ledger AYL-002. #116 merged the auditable coverage; the live run is still an operator task | Operator | Run with secret-safe receipts | Every promoted category `live_verified` |
| AY-07 | Mycelial Phase 1 is blocked at evidence acquisition | DATA/GOV | Ledger AYL-005. #239 W03: "original biological payloads captured: 0" because the tested download routes failed in the agent environment (DNS/binary). #255 W08: 0 approved targets, sites, substrate units or visits; needs taxonomic and field review and permissions. | Operator + reviewers | Run the W03 archive fetch (for example CUP DwC-A) in a network-enabled runner such as GitHub Actions; reviewers decide on the W08 candidate target | W03 bytes hash-frozen; W08 target approved |
| AY-08 | Federation spatial certification can report a false green | GATE | #231: strict producer certification mode, rejection of OPEN/BLOCKED/UNKNOWN/SKIP gates, executed-test evidence. Paired with thehub #253. | Agent/maintainer | Implement the #231 scope together with thehub #253 | Certified ingestion rejects unresolved manifests end to end |
| AY-09 | FOOD_SYSTEM_RESILIENCE Phase 3/4 is locked | GATE | #194: locked until the Vector B/C coefficient and scenario gates pass. The lock is reviewed on 2027-02-28. | Research/maintainer | Only passing the Vector B/C gates unlocks it | Gates pass, or the lock is explicitly renewed on 2027-02-28 |
| AY-10 | The real-data partial export gate is not built | IMPL | #11: every task is unchecked. PR #168 ("certify bounded real-data partial export") was closed unmerged on 2026-09-03. | Agent | New PR scoped to #11 (schemas, source registry, fixture, continuity taxonomy, caveats) | The Hub ingests the partial package without treating it as full coverage |
| AY-11 | Open PRs are red or waiting | PR | See the next table | Agent + maintainer | Per-PR actions below | No red PRs |
| AY-12 | Stale trackers from the Actions outage | STALE | #234 and #256 track the 2026-09-06 → 09-19 runner outage. `.github/actions-restoration-notice.md` already says RESTORED, and its exit criterion (a real runner on `main`) is met: push CI on `cbdbd6b` is green with executed steps. | Agent | Close both issues with the green run IDs; archive the notice | Trackers closed |

### Open pull requests (AY-11)

| PR | State | Action |
|---|---|---|
| #299 Cell_Set uncertainty contract | Conflicts with `main` since the post-audit v0.2 series, which already carries the contract in `federation/spatial/registry_version.json` | Confirm v0.2 covers it, then close as superseded (X-05) |
| #280 MiLUMA historical schema evidence | RED: Federation GUI Capability Parity | Register its capability in `.federation/gui-capabilities.json`, rerun |
| #284 npm minor/patch group | Green | Update the branch and merge |
| #288 recharts 3 | Green | Update the branch and merge |
| #290 codacy action 1.1 → 4.4.7 | Green | `codacy.yml` is repo-local (not rendered from thehub templates), so review the major bump and merge |
| #291 python minor/patch group | Green | Update the branch and merge |
| #289 actions minor/patch group | RED: Federation template drift | Land the bump in thehub `federation-templates`, re-render, close this PR |
| #287 jsdom 30 | RED: GUI Reachability E2E | Investigate the E2E failure, or pin jsdom |
| #286 eslint 10 | RED: dashboard-build, 3 builds, E2E | Migrate to eslint 10, or ignore the major (X-02) |
| #285 maplibre-gl 6 | RED: 6 checks | Migrate the map API, or ignore the major |

## Unblock plan

### P1 — executable now
1. **AY-01:** remove or neutralize the Floot promotion step so the refresh turns green and the Hub dispatch fires.
2. **AY-12:** close #234 and #256 with evidence; archive the restoration notice.
3. **AY-11:** merge the green dependabot PRs and fix #280's parity registration.
4. **AY-10:** open a scoped PR for #11.

### P2 — operator inputs
1. **AY-03:** repair `NEON_API_TOKEN` and dispatch `neon-live-smoke.yml`.
2. **AY-06:** run the USGS live verification.
3. **AY-07:** run the W03 byte acquisition in a network-enabled runner.
4. **AY-04, AY-05:** pursue the authorized outage feed and direct Laguna Cartagena measurements.

### P3 — maintainer decisions
1. Decide the X-01 gate rule or bot-commit strategy (AY-02).
2. Approve the W08 target and sites (AY-07).
3. Enable branch protection on `main` (X-03; thehub #256 names this repo).

### P4 — longer horizon
1. **AY-08:** #231 strict certification together with thehub #253.
2. **AY-03:** NEON P1–P4.
3. **AY-09:** FOOD_SYSTEM_RESILIENCE Vector B/C gates.

## Ledger reconciliation (`docs/unfinished_implementation_ledger.v1.json`, dated 2026-08-04)

| Ledger ID | Ledger state | State on 2026-09-28 |
|---|---|---|
| AYL-001 | closed_merged | Closed |
| AYL-002 | operator_run | Still open → AY-06 |
| AYL-003 | open_pr (PR-114) | Resolved: #114 merged 2026-08-05 |
| AYL-004 | stacked_open_pr (PR-115) | Resolved: #115 merged 2026-08-05 |
| AYL-005 | governance_blocked | Still open → AY-07 (Ballot A contracts merged in #134; Phase 1 ingestion not started) |
| AYL-006 | external_data | Still open → AY-04 |
| AYL-007 | merged_context_only | Still open → AY-05 |
| AYL-008 | main_design_authority (PR-120) | Largely resolved: increments #171, #173, #174, #176 and #178 ("final regulatory increment") merged; operator certification remains |

## Hygiene
- Duplicate branches `tmp-ignore-usace`, `tmp-ignore-usace-2` … `-6` and `usace-pr-hydrospatial-corpus-v1-copy` all point at `6bceeae`; prune them.
- 34 branches on origin.

## Federation-wide blockers that affect this repo
- X-01: completion gate, made worse by AY-02.
- X-02: dependabot backlog and template drift.
- X-03: `main` is unprotected.
- X-05: the Cell_Set PR set, now superseded by v0.2 on `main`.
- X-07: stale ledgers.
- X-10: `main` lint is red since the v0.2 series; this PR carries the fix.

See the thehub document for details.

## Not verifiable with the access used for this audit
- Code-scanning and Dependabot security-alert inventories. Post-audit: GitHub's push notice on 2026-09-28 reports 12 open Dependabot alerts on `main` (2 critical, 5 high, 5 moderate). Triage them at `https://github.com/jotaele44/aguayluz-pr/security/dependabot`; the per-alert detail is not visible with this access.
- Which Actions secrets exist (the NEON token state is taken from #220).
- The Floot deployment's status, inferred from the TLS failure and the archive branches.
