"""Read-only native/Federation electricity contract, isolated from legacy exports."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from aguayluz.electricity.evidence import GeneratorClaim, reconcile_claims
from aguayluz.electricity.store import EvidenceStore


def electricity_projection(store: EvidenceStore) -> dict:
    snapshot = store.snapshot()
    reconciliation = reconcile_claims([GeneratorClaim.model_validate(c) for c in snapshot["claims"]])
    # Content revision excludes projection wall clock and is stable across consumers/replay.
    revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": "aguayluz.electricity-projection/v1", "producer": "aguayluz-pr",
            "jurisdiction": "PR", "revision": revision,
            "generated_at": datetime.now(timezone.utc).isoformat(), "certification": "NOT_CERTIFIED",
            "canonical_promotion": "BLOCKED", "telemetry": "AUTHORITATIVE_FEED_UNAVAILABLE",
            "states": {kind: {"availability": "AVAILABLE_AUDIT_ONLY" if any(m["evidence_class"] == kind for m in snapshot["measurements"]) else "UNAVAILABLE",
                              "measurements": [m for m in snapshot["measurements"] if m["evidence_class"] == kind]}
                       for kind in ("OBSERVED", "RECONSTRUCTED", "FORECAST", "SOURCE_CANDIDATE")},
            "sources": snapshot["sources"], "acquisition_attempts": snapshot["attempts"],
            "generator_claims": reconciliation["claims"],
            "contradictions": reconciliation["contradictions"],
            "gaps": ["RC8_RC14_ORIGINAL_PACKAGES_MISSING", "P0_SCAFFOLD_ARCHIVE_MISSING",
                     "EIA_LIVE_SCHEMA_UNVERIFIED", "INDEPENDENT_SCIENTIFIC_REVIEW_REQUIRED",
                     "FORECAST_BACKTESTS_NOT_AVAILABLE", "FEDERATION_CONSUMER_ACCEPTANCE_OPEN"]}
