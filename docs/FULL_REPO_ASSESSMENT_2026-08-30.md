# AguaYLuz-PR full repo assessment and implementation strategy

Assessment date: 2026-08-30

Repository: `jotaele44/aguayluz-pr`

Current hosted main: `372e5cc39cbc0c2655887ffdf96f7ae22162f680`

Assessment branch: `audit/full-repo-assessment-20260830`

## Session context anchor

FACT: Hosted `main` advanced after the earlier local session. The current GitHub default branch head is `372e5cc39cbc0c2655887ffdf96f7ae22162f680`, pushed at 2026-08-30T15:12:12Z.

FACT: Latest hosted `validate` workflow for that SHA completed successfully. Jobs observed as success: `dashboard-build`, `typecheck`, `lock`, `test (3.10)`, `test (3.12)`, and `geo-import-check`. The `live-smoke` job was skipped, so live-source certification is not implied.

FACT: Latest hosted CodeQL workflow for that SHA completed successfully.

FACT: `federation.json` reports `production_status = PRODUCTION_REAL_DATA_PARTIAL`, `ready_for_hub_discovery = true`, `ready_for_hub_live_execution = true`, and no blocking readiness conditions.

FACT: The committed repo does not currently include generated `outputs/*.json` or `exports/federation/*` artifacts on `main`; `outputs/` contains only `.gitkeep`, and `exports/` is absent in the hosted tree. The canonical commands generate these locally/runtime.

FACT: Local command execution inside the Codex task failed before shell startup with `No such file or directory`, so local working-tree status, local-only branches, generated artifacts, and fresh local tests were not recertified in this pass.

## Goal

Convert the current repo state from locally and hosted-green code into a certified federation-ready producer posture, without confusing code health, data freshness, hosted CI, local generated artifacts, downstream acceptance, or live-source availability.

## Gates

| Gate | State | Evidence | Remaining action |
|---|---:|---|---|
| Hosted code/test/build | PASS | `validate` run for `372e5cc` succeeded across dashboard build, typecheck, lock, Python 3.10, Python 3.12, geo import check | None for hosted code health |
| CodeQL | PASS | CodeQL run for `372e5cc` succeeded | None |
| Local checkout currentness | BLOCKED | Codex shell failed before startup | Restore local execution, then run `git status`, `git fetch`, `git log`, `pytest` |
| Generated canonical export | OPEN | `outputs/*.json` and `exports/federation/*` are runtime artifacts, not committed | Run `python3 scripts/federation_export.py --mode test` locally and preserve hashes/counts |
| Live-source certification | OPEN | `live-smoke` skipped; NEON token and MiLUMA WAF gates remain source-specific | Run live smoke only with approved credentials and source terms |
| Downstream hub acceptance | OPEN | `federation.json` targets `thehub-pr`, but this pass did not execute the hub consumer | Validate exported package against TheHub schema and ingestion path |
| Loose branch cleanup | OPEN | Hosted repo has many branches; six open PR branches are all divergent from current `main` | Rebase/rescue branch work before merge or delete |

## Vector A: current repo health

COMPUTED: Current hosted health is strong. `main` has passing build/test/typecheck/lock/geo-import/CodeQL checks on the latest observed SHA.

BINDING: This is not universal completion. Hosted CI does not prove live-source freshness, local generated artifact correctness, or downstream hub ingestion.

Implementation sequence:

1. Restore local command execution.
2. Fetch remote state and confirm local `main` equals `origin/main@372e5cc39cbc0c2655887ffdf96f7ae22162f680`.
3. Run `uv pip install -e .[dev]` or the declared setup in `federation.json`.
4. Run `python -m pytest -q`.
5. Run `python scripts/validate_repo.py`.
6. Run dashboard lint/test/build from `dashboard/`.
7. Record exact command output, SHA, UTC, and dirty-state status.

Required classification after Vector A:

- PASS only if local and hosted checks both pass on the same SHA.
- PROVISIONAL if hosted passes but local execution remains blocked.
- FAIL if local differs from hosted or generated artifacts fail validation.

## Vector B: branch and artifact hygiene

FACT: Open hosted PRs at assessment time:

| PR | Branch | State | Compare against current main | Classification |
|---:|---|---|---|---|
| #196 | `claude/gis-capability-repos-jfvm9u` | draft | ahead 2, behind 37 | SALVAGE_REQUIRED: event-density/barrios work must be rebased onto current dashboard/backend |
| #195 | `feature/htr-context-consumer-v1` | open | ahead 9, behind 19 | SALVAGE_REQUIRED: HTR context-only guard is conceptually valuable but must rebase and re-test |
| #191 | `agent/cave-karst-consolidation-v1-2` | draft | ahead 32, behind 28 | SALVAGE_REQUIRED: large cave/karst lineage branch, not safe to merge or delete without replay |
| #95 | `codex/aguayluz-v23-gis-gates-20260730` | draft | ahead 8, behind 626 | SUPERSEDED_OR_REPLAY: very stale GIS gate work; compare against current geo-import checks before replay |
| #63 | `audit/road-to-100-normalization-v0-2` | draft | ahead 1, behind 684 | SUPERSEDED_OR_DOC_REPLAY: documentation-only roadmap may need current-main rewrite |
| #21 | `gpt/offline-operator-model-v1` | draft | ahead 2, behind 821 | SUPERSEDED_OR_REPLAY: offline operator scaffold predates current launcher/runtime work |

INFERENCE: No open PR is merge-ready as-is. All are divergent, and several are hundreds of commits behind. Merging directly would risk template drift, deleted file resurrection, stale workflow behavior, or dashboard regressions.

Branch cleanup implementation strategy:

1. Preserve exact head SHA and compare output for each branch before any deletion.
2. For open PR branches, create a current-main replay branch rather than force-mutating the original draft branch.
3. Reapply only semantically current files. Reject stale generated artifacts, old workflows, and launcher rewrites unless still needed.
4. Run full local and hosted checks for each replay.
5. Close or delete only after the replay is merged or explicitly marked SUPERSEDED with preserved evidence.

For local-only branches, apply the same classification but do it from the local checkout after shell execution returns:

- MERGED: branch head is ancestor of `main`.
- SUPERSEDED: equivalent work exists on `main`; preserve commit list and `git diff --stat` before deletion.
- SALVAGE_REQUIRED: branch contains unique code/data/docs not on `main`.
- BLOCKED: cannot compare cleanly because local state, promisor objects, or dirty files are missing.

## Vector C: federation readiness

FACT: `federation.json` declares `active_vector = AGUAYLUZ_WATER_POWER_INFRASTRUCTURE_INTELLIGENCE` and `hub_parent = thehub-pr`.

FACT: `config/federation_manifest.yaml` owns water/wastewater assets, PRASA/AAA public references, power/grid records, outages/restoration/service interruptions, utility recovery projects, utility geospatial summaries, and sanitized exports to the hub. It explicitly does not own funding/vendor joins, subsurface corridor inference, airspace observation, UAP/USO reports, or central dashboard responsibilities.

FACT: `scripts/federation_export.py` writes runtime artifacts under `outputs/` and `exports/federation/`, including `hub_export.json`, `integration_report.json`, source manifest, review queue, bridge summary, and JSONL federation streams.

COMPUTED: Federation readiness is PROVISIONAL, not certified, until a current local export is generated from current data and accepted by the hub consumer.

Implementation sequence:

1. Run `python3 scripts/federation_export.py --mode test` on current `main`.
2. Capture generated file list, record counts, SHA-256 hashes, and source manifest coverage.
3. Confirm gates G01-G08 are PASS in `outputs/integration_report.json`.
4. Confirm no source rows rely on name-only or proximity-only identity promotion.
5. Confirm water measurement and infrastructure scope remains separate from spiderweb-style subsurface/corridor layers.
6. Confirm runtime-only generated artifacts are either intentionally gitignored or published through the hub handoff mechanism.
7. Run TheHub consumer validation against `exports/federation/manifest.json` and the four stream files.
8. Mark readiness:
   - CERTIFIED only if local export, schema gates, source manifests, record arithmetic, and hub consumer validation pass on the same input snapshot.
   - PROVISIONAL if code passes but generated artifacts or hub consumer validation were not run.
   - BLOCKED if required credentials/source authorization are unavailable.

## Gaps

OPEN: Live per-municipio outage attribution remains constrained by MiLUMA WAF and source authorization.

OPEN: NEON readings require `NEON_API_TOKEN`; metadata remains keyless, readings are token-gated.

OPEN: `docs/ROAD_TO_100.md` is anchored to 2026-08-04 and an older `main` SHA. It should be refreshed after branch triage and export certification.

OPEN: The active branch inventory is large. Hosted branch count exceeds the open PR set, including many `agent/*`, `rescue/*`, `design/*`, `cert/*`, and `ci/*` branches. These require bulk classification after local command execution is restored.

OPEN: The repo currently contains cave/karst data and mycelial docs on `main`. These may be historical or cross-vector artifacts, but they should be reconciled against the current federation ownership boundary so AguaYLuz does not silently become the system of record for out-of-scope domains.

## Variables

BINDING: Do not use source taxonomy as canonical identity proof.

BINDING: Do not prove identity with `NAME_ONLY`, normalized name only, count equality, nearest-only, proximity-only, category equality, or source absence.

BINDING: Preserve raw, normalized, and canonical strings separately.

BINDING: For proposed equivalence, compute INTERSECTION, A_ONLY, B_ONLY, UNION, and SYMMETRIC_DIFFERENCE.

ASSUMPTION: The latest hosted state is authoritative for remote evidence because local shell execution was unavailable in this task.

UNKNOWN: Current local working tree status, local-only branch contents, local generated artifact hashes, and downstream TheHub runtime acceptance.

## Readiness

Hosted code readiness: PASS.

Local execution readiness: BLOCKED in this task until the shell runner is restored.

Federation export readiness: OPEN.

Downstream hub readiness: OPEN.

Loose branch readiness: OPEN, with all six open PR branches classified as not merge-ready as-is.

Overall state: PRODUCTION_REAL_DATA_PARTIAL with strong hosted CI and unresolved certification vectors.

## Most productive next implementation actions

1. Restore local shell execution and bring `/Users/jotaele/Developer/aguayluz-pr` to `origin/main@372e5cc39cbc0c2655887ffdf96f7ae22162f680`.
2. Run the declared setup/test/export commands from `federation.json`.
3. Generate and hash `outputs/*` and `exports/federation/*` without committing bulky runtime artifacts unless policy explicitly changes.
4. Rebase PR #196 first if the event-density choropleth is still desired; it is small, user-facing, and only 37 commits behind.
5. Rebase PR #195 next; preserve the HTR rule that recurrence/fuzzy/proximity evidence is context only, not identity.
6. Triage PR #191 separately because it is larger and crosses cave/karst privacy and access semantics.
7. Treat #95, #63, and #21 as likely superseded until their current-main replay proves otherwise.
8. Refresh `docs/ROAD_TO_100.md` only after export and branch triage are complete.

🚩 This assessment pattern should train a federation repo-certification skill: separate hosted CI proof, local generated artifact proof, live-source proof, downstream hub proof, branch hygiene, and semantic ownership boundaries.
