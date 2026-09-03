# Refresh automation audit — 2026-08-17

## Scope

Audit the scheduled `refresh` workflow on `main`, focusing on the repeated appearance/disappearance of AguaYLuz `HYDRO_OPS` proxy alerts and whether workflow success can silently mask data-quality or lifecycle regressions.

## Frozen observations

- Workflow: `.github/workflows/refresh.yml`
- Schedule: every 15 minutes (`--fast`), daily 07:00 UTC (`--daily`), Monday 07:00 UTC (`--weekly`).
- Latest audited fast run: Actions run `32017645608`, started 2026-08-17T09:55:37Z from `main@51abed8fb80bec933022bd27eb670a3b0b37e4fd`.
- That run completed successfully and committed `d983e35004564ac3b0b74c7af484554080a3a90f` with two deletions.
- Previous audited fast run `32013575745` completed successfully but made no commit.

## Findings

### F1 — fast cadence recomputes slow-moving hydro alerts from stale daily inputs

`PLANS["fast"]` does **not** refresh `STEP_USGS_LEVELS` or `STEP_USGS_GW`, but it **does** execute `STEP_ALERTS` and `STEP_ALERT_SYSTEM`. Therefore every 15-minute run recomputes `HYDRO_OPS` reservoir/groundwater alerts using the most recently persisted daily reservoir/groundwater input files rather than newly fetched daily observations.

This is not necessarily incorrect, but it means a fast run can alter the canonical alert corpus even when no new reservoir or groundwater measurement has been acquired.

### F2 — canonical alert generation is replacement-oriented, not lifecycle-preserving

The observed history shows hydro proxy records can appear and disappear between scheduled refresh commits. The current workflow writes the recomputed `data/alert_events.jsonl` and commits it directly. Alert absence therefore carries no explicit terminal reason such as `recovered`, `recomputed_out`, `source_missing`, `stale_input`, or `superseded`.

This creates a semantic hazard: downstream consumers may interpret disappearance as physical recovery even though the workflow only proved that the current generator no longer emitted the record.

### F3 — optional source failures do not fail the workflow

The latest audited run logged a persistent USGS RTFI HTTP 422 for `https://api.waterdata.usgs.gov/rtfi-api/referencepoints/state/PR`. `STEP_USGS_RTFI` is optional, so the workflow continued and concluded `success`.

This is intentional in code, but workflow-level `success` therefore does not mean every configured provider succeeded.

### F4 — workflow success does not enforce alert-delta sanity

The latest fast run generated 4 `HYDRO_OPS` alerts and then committed two deletions to the repository. No pre-commit gate classified alert removals by cause or rejected unexplained disappearance of active hydro proxies.

### F5 — Hub dispatch follows any committed data delta

When a refresh commit is created, the workflow dispatches `aguayluz-export` to `thehub-pr`. Consequently an unexplained alert deletion can propagate immediately to the federation hub.

## Required adjustment

Before changing production runtime behavior, add an explicit **alert-delta audit gate** between `build_alerts.py` / `build_alert_system.py` and `git commit`.

The gate should compare pre-refresh and post-refresh alert IDs and emit at minimum:

- `intersection`
- `pre_only`
- `post_only`
- `union`
- `symmetric_difference`
- removals grouped by `module_id`, `event_type`, and evidence tier
- source freshness for removed derived alerts
- whether the cadence refreshed the source family that produced the removed alert

For `HYDRO_OPS`, a removal on `--fast` should be classified `RECOMPUTED_OUT_WITHOUT_NEW_DAILY_SOURCE` unless direct source-refresh evidence proves otherwise. It must not be labeled recovery.

## Fail-closed policy recommended

Do **not** block all fast refreshes. Instead:

1. Always write a machine-readable audit artifact under `reports/refresh_alert_delta.json`.
2. If active T1/T2 operational alerts disappear, preserve the removal in a lifecycle sidecar with `last_seen_at`, `terminal_reason`, `source_freshness`, and `recovery_evidence`.
3. If a `HYDRO_OPS` alert disappears during a cadence that did not refresh its source family, mark it `recomputed_out_without_new_source`; do not infer recovery.
4. Block Hub dispatch when an unexplained active-alert deletion exceeds a configurable threshold or when the lifecycle sidecar cannot be written.
5. Record optional-provider failures in a refresh-health artifact so Actions `success` remains distinguishable from full provider success.

## Current certification

- Workflow execution health: **PASS with advisory gaps**.
- Provider completeness: **PROVISIONAL** because optional RTFI is failing with HTTP 422.
- Hydro alert lifecycle semantics: **FAIL**.
- Physical recovery inference from alert deletion: **BLOCKED**.
- Federation propagation of unexplained deletions: **OPEN risk**.

This document is audit-only and changes no runtime behavior.
