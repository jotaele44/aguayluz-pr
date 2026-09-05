# Federation Upgrade / Certification Skill

## Status
CANDIDATE_NOT_ACTIVATED. This procedure may be used as an audit/runbook while the reference repair in `aguayluz-pr#232` and downstream enforcement in `thehub-pr#254` are under validation. It MUST NOT emit CERTIFIED until one complete reference execution closes every required gate.

## Purpose
Upgrade a federation producer and its Hub consumer without discarding passed evidence, silently changing source identity, converting discovery into canonical identity, or treating CI/script success as certification.

## Entry conditions
1. Freeze the producer repository full name, starting commit SHA and tree SHA.
2. Freeze the Hub repository full name, starting commit SHA and tree SHA.
3. Inventory active PRs/branches and identify already-merged work before replaying anything.
4. Preserve historical passed artifacts as immutable evidence. Do not regenerate them merely to replace old evidence.
5. Record contradictions as BYTE, SCHEMA, GEOMETRY, NAME, COUNT, CLASS, IDENTITY, TIME, or SCOPE and adjudicate the narrowest conflict first.

## Required sequence
1. **Repository identity** — prove local/hosted repository and commit identity with stable Git identifiers; NAME_ONLY is insufficient.
2. **Change-set retention** — enumerate every path in the prior accepted change set; prove presence; classify post-merge modifications; allow a modified path only when explicitly adjudicated and its required semantics remain present.
3. **Contract preservation** — validate federation compatibility and HAF contracts before domain replay. Separate adapter release version from contract/schema version.
4. **Audit vs certification** — audit/readiness mode may report OPEN/SKIP. Certification mode requires PASS for every required gate; OPEN, BLOCKED, UNKNOWN, UNRESOLVED, WARN, SKIP, missing gates, malformed states, and disabled required gates fail closed.
5. **Executed tests** — test-file existence is never execution proof. Certification requires a FULL test-execution receipt bound to the exact Git commit and tree being certified.
6. **Spatial identity** — proximity/search/buffer/nearest are discovery only. Cross-producer spatial relations remain `CANDIDATE_NOT_IDENTITY` unless independent identity evidence closes the binding.
7. **Runtime manifestation** — generate operator outputs and canonical federation streams exactly once from the frozen producer commit. Never mix artifacts from different commits/runs.
8. **Artifact freeze** — record sorted path, byte size and SHA256 for every emitted file plus producer commit/tree, command, runtime versions, generated UTC, schema/count ledger and unresolved residue.
9. **Arithmetic closure** — assert source/retained/excluded/review/export counts and stream counts. Any unexplained mismatch fails closed.
10. **Downstream consumption** — TheHub may load unresolved producer data only as `AUDIT_ONLY` and non-promotable. Certified ingestion requires the producer's complete certification gate set to be PASS and must validate the exact frozen package.
11. **Dependency-directed rerun** — after a downstream failure, reuse passed upstream artifacts. Rerun only the failed gate and any gate whose inputs changed.
12. **Promotion boundary** — branch cleanup, branch protection, required checks, rollback and production smoke are distinct from code/test success and must close independently.

## Positive regression gates
- complete PASS producer manifest is accepted in certification mode;
- exact FULL pytest receipt bound to current commit/tree is accepted;
- all retained GIS paths are present and adjudicated modifications preserve declared semantic markers;
- exact frozen runtime package is accepted by the Hub;
- cross-producer proximity emits candidate relations without identity promotion.

## Negative regression gates
- any required OPEN/BLOCKED/UNKNOWN/UNRESOLVED/SKIP/WARN/missing gate rejects certification;
- stale test receipt, wrong commit/tree, malformed SHA, duplicate/missing retention path, or unadjudicated post-merge modification rejects certification;
- producer-repository mismatch, HAF version drift, compatibility BLOCKED state, or federation manifest drift rejects certification;
- malformed geometry/hash or identity promotion rejects Hub consumption;
- Hub audit ingestion can never become promotable merely because structural validation succeeds;
- runtime artifact mutation after freeze invalidates the package receipt.

## Required execution receipt
Every run must record: `capability_id`, `repository`, `pinned_base_commit`, `pinned_tree`, `hub_repository`, `hub_commit`, `inputs`, `retained_artifacts`, `changed_artifacts`, `commands`, `outputs`, `sha256`, `counts`, `validation`, `contradictions`, `limitations`, `unresolved_residue`, `authority`, `next_action`, and final state.

## Certification rule
Issue `FEDERATION SPATIAL ARCHITECTURE CERTIFIED` only when the defined scope has frozen inputs, explicit inclusion/exclusion, complete change-set retention accounting, compatibility/HAF closure, required producer gates all PASS, FULL executed-test evidence, one coherent hashed runtime manifestation, arithmetic closure, exact Hub certified ingestion, preserved `CANDIDATE_NOT_IDENTITY` semantics, passed positive/negative regressions, promotion prerequisites as required by scope, and zero material unresolved residue. Otherwise return PASS only for individual closed gates and overall OPEN/BLOCKED/AUDIT_ONLY.
