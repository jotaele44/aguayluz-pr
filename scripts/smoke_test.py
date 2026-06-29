#!/usr/bin/env python3
"""Live smoke test for the AguaYLuz federation pipeline.

Invoked by CI's ``live-smoke`` job (workflow_dispatch) as
``python scripts/smoke_test.py``. Runs two checks:

1. **Offline pipeline** (always): build the canonical federation streams from a
   tiny in-memory asset + event and confirm the expected entity types appear.
2. **Live EPA WATERS** (only when an API key is set): point-index a known Puerto
   Rico coordinate and confirm it snaps to a flowline in NHDPlus VPU 21 — proving
   auth, connectivity, and PR coverage end-to-end.

Exit code: 0 on success (including the no-key *skip* of the live check), non-zero
on any failure.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# scripts/ holds federation_export; src/ holds the installed `aguayluz` package
# (CI runs `pip install -e .[dev]`, but add both so a plain checkout also works).
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
for _p in (SCRIPTS_DIR, REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# A point in the Río de la Plata basin, Puerto Rico (NHDPlus VPU 21).
_PR_LON, _PR_LAT = -66.232, 18.388
_API_KEY_VARS = ("EPA_WATERS_API_KEY", "API_DATA_GOV_KEY")


def _has_api_key() -> bool:
    return any(os.environ.get(v) for v in _API_KEY_VARS)


def check_offline_pipeline() -> bool:
    """Build canonical streams from a minimal asset+event; confirm entity types."""
    from federation_export import build_streams  # scripts/ is on sys.path

    assets = [{
        "asset_id": "A1", "asset_name": "PRASA Ponce Plant", "asset_type": "water",
        "asset_subtype": "treatment", "operator": "PRASA", "municipality": "Ponce",
        "source_ref": "prasa-registry", "source_hash": "h1", "confidence": 80,
        "evidence_tier": "T2", "review_status": "approved", "status": "active",
        "geometry_type": "point", "comid": 12345,
    }]
    events = [{
        "event_id": "E1", "event_type": "outage", "affected_area": "Ponce",
        "source_ref": "luma-report", "confidence": 70, "evidence_tier": "T3",
        "review_status": "approved", "linked_asset_ids": ["A1"],
    }]
    try:
        streams = build_streams(assets, events, "2026-01-01T00:00:00Z")
    except Exception as exc:  # noqa: BLE001 — any failure is a smoke failure
        print(f"[pipeline] FAIL: build_streams raised: {exc!r}")
        return False

    types = {e.get("entity_type") for e in streams.get("entities", [])}
    expected = {"utility_asset", "utility_operator", "municipality", "service_event"}
    missing = expected - types
    if missing:
        print(f"[pipeline] FAIL: missing entity types {sorted(missing)} (got {sorted(types)})")
        return False
    print(f"[pipeline] OK: built canonical streams covering {sorted(expected)}")
    return True


def check_live_waters() -> bool:
    """Point-index a known PR coordinate; confirm a VPU-21 flowline comes back."""
    from aguayluz.waters import (
        AuthError,
        RateLimitExceeded,
        WatersClient,
        WatersServerError,
    )
    from aguayluz.waters.endpoints import first_flowline, point_indexing

    try:
        with WatersClient() as client:
            resp = point_indexing(client, lon=_PR_LON, lat=_PR_LAT)
    except (AuthError, RateLimitExceeded, WatersServerError) as exc:
        print(f"[live] FAIL: WATERS request errored: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 — surface any unexpected failure
        print(f"[live] FAIL: unexpected error: {exc!r}")
        return False

    flowline = first_flowline(resp)
    if not flowline:
        print("[live] FAIL: pointindexing returned no flowline for the PR probe point")
        return False
    region = str(flowline.get("nhdplus_region", ""))
    if region != "21":
        print(f"[live] FAIL: expected NHDPlus VPU 21 (Puerto Rico), got region={region!r}")
        return False
    print(f"[live] OK: pointindexing snapped to comid={flowline.get('comid')} in VPU {region}")
    return True


def main() -> int:
    ok = check_offline_pipeline()

    if _has_api_key():
        ok = check_live_waters() and ok
    else:
        print(f"[live] SKIP: no API key ({' / '.join(_API_KEY_VARS)} unset); live check skipped")

    print("SMOKE PASS" if ok else "SMOKE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
