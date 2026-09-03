---
name: aguayluz-pr-unified-live-skillpack
description: "Compiled non-activating dispatch contract for shared and aguayluz-pr capabilities."
version: 1.0.0
compatibility: claude
repository: aguayluz-pr
---

# aguayluz-pr Unified Live Skillpack

Pinned base: `0c96ba71ad2c71cb2d44b0c5cdbe8e9992f06427`.

## Execution contract

- Exact capability identifiers only; unknown identifiers fail closed.
- Runtime activation, automatic dispatch, live polling, notifications, external writes, promotion, control actions, merge, and release are disabled.
- Source module semantics remain cryptographically bound in `MANIFEST.json`; this file is the compiled live dispatcher.
- Repository-specific authority overrides shared defaults.

## Capability dispatch

| Capability | Module | Status | Preserved responsibility |
|---|---|---|---|
| `repo-state-reader` | `repository-governance` | `` |  |
| `repo-identity-guard` | `repository-governance` | `` |  |
| `branch-guard` | `repository-governance` | `` |  |
| `task-scope-guard` | `repository-governance` | `` |  |
| `git-action-guard` | `repository-governance` | `` |  |
| `skill-authoring-template` | `skill-lifecycle` | `` |  |
| `skill-package-builder` | `skill-lifecycle` | `` |  |
| `validation-gate-runner` | `validation-and-recovery` | `` |  |
| `failure-packet-builder` | `validation-and-recovery` | `` |  |
| `delta-reporter` | `reporting-and-receipts` | `` |  |
| `status-writer` | `reporting-and-receipts` | `` |  |
| `foia-correspondence-manager` | `foia-operations` | `` |  |
| `foia-request-sender` | `foia-operations` | `` |  |
| `aguayluz-operator` | `orchestration` | `` |  |
| `aguayluz-utility-asset-ingest` | `utility-source-ingestion` | `` |  |
| `aguayluz-outage-event-ingest` | `utility-source-ingestion` | `` |  |
| `aguayluz-hydro-register-import` | `utility-source-ingestion` | `` |  |
| `aguayluz-utility-geo-normalizer` | `geospatial-normalization` | `` |  |
| `aguayluz-alert-builder` | `alert-construction` | `` |  |
| `aguayluz-federation-export` | `federation-export` | `` |  |

## Required output fields

Every execution receipt must include `capability_id`, `repository`, `pinned_base_commit`, `inputs`, `outputs`, `validation`, `limitations`, `authority`, and `next_action`.

## Non-activation boundary

This binding does not invoke repository code. A later runtime adapter requires separate design, tests, review, and explicit authorization.
