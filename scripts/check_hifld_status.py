#!/usr/bin/env python3
"""Probe HIFLD ArcGIS FeatureServer URLs + report per-layer drift.

Why this exists: HIFLD hub URLs are flaky (drafted from memory in M11) and the
`hifld_client.py` fallback masks the drift in production runs. This monitor
checks every URL in `LAYER_URLS` and surfaces FOUR distinct outcomes:

  live          HTTP 200 + valid GeoJSON FeatureCollection + features > 0
  empty         HTTP 200 + valid GeoJSON FeatureCollection + features = 0
  service_error HTTP 200 + ArcGIS error body (URL path wrong)
  down          HTTP 4xx/5xx or network failure

Drift is detected by diffing the current observation against
`tests/baseline/hifld_layer_status.json`. Transitions are categorized:

  live → down            critical    we lost a source
  down → live            info        a flaky URL came back; refresh fixture
  live → live, count    warn        dataset moved >25%
  unchanged             no alert

Modes:
  --check (default)   Compare live status to the committed baseline; exit 1
                      on any unexpected change.
  --write-baseline    Persist the current observation as the new baseline.
                      Use after manually accepting a transition.
  --refresh-snapshot LAYER FILE
                      Pull the live layer (PR features only) and overwrite
                      a committed GeoJSON fixture at FILE. Lets the operator
                      regenerate `tests/fixtures/hifld/pr_substations_sample.geojson`
                      when a URL eventually starts working.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.ingest.hifld_client import LAYER_URLS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "tests" / "baseline" / "hifld_layer_status.json"
DEFAULT_TIMEOUT_S = 20.0
USER_AGENT = "aguayluz-pr/m24-hifld-monitor"
PROBE_MAX_FEATURES = 100  # cap on what we pull just to count features


# Transition tolerance: a >25% swing in feature_count between observations
# is a real dataset move; under 25% is noise (EPA edits, retired records).
FEATURE_COUNT_DRIFT_PCT = 25.0


def _probe_layer(*, url: str, state: str = "PR", timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Return `{status, feature_count, error?}` for one layer URL."""
    params = {
        "where": f"STATE='{state}'",
        "outFields": "*",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": str(PROBE_MAX_FEATURES),
    }
    try:
        response = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        return {"status": "down", "feature_count": 0, "error": f"network: {exc.__class__.__name__}"}

    if response.status_code != 200:
        return {
            "status": "down",
            "feature_count": 0,
            "error": f"HTTP {response.status_code}",
        }

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {"status": "down", "feature_count": 0, "error": "non-JSON 200 body"}

    if isinstance(payload, dict) and payload.get("error"):
        # ArcGIS's habit: 200 OK with an `error` body when the URL path is wrong.
        return {
            "status": "service_error",
            "feature_count": 0,
            "error": str(payload["error"])[:200],
        }

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        return {"status": "down", "feature_count": 0, "error": "unexpected response shape"}

    features = payload.get("features") or []
    return {
        "status": "live" if features else "empty",
        "feature_count": len(features),
    }


def probe_all_layers(*, layers: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Probe every known layer. Returns `{layer_name: observation}`."""
    sources = layers if layers is not None else LAYER_URLS
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict[str, dict[str, Any]] = {}
    for layer, url in sources.items():
        observation = _probe_layer(url=url)
        observation["url"] = url
        observation["observed_at"] = observed_at
        out[layer] = observation
    return out


def diff_observations(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return per-layer transition findings; empty list = no drift."""
    findings: list[dict[str, Any]] = []
    all_layers = set(baseline) | set(current)
    for layer in sorted(all_layers):
        prev = baseline.get(layer) or {}
        curr = current.get(layer) or {}
        prev_status = prev.get("status")
        curr_status = curr.get("status")

        # New layer in LAYER_URLS — neutral, just record.
        if not prev_status:
            findings.append({
                "layer": layer,
                "kind": "new",
                "severity": "info",
                "prev_status": None,
                "curr_status": curr_status,
                "message": f"new layer added to LAYER_URLS, current status={curr_status}",
            })
            continue
        # Removed layer.
        if not curr_status:
            findings.append({
                "layer": layer,
                "kind": "removed",
                "severity": "warn",
                "prev_status": prev_status,
                "curr_status": None,
                "message": f"layer removed from LAYER_URLS (was {prev_status})",
            })
            continue

        if prev_status == "live" and curr_status != "live":
            findings.append({
                "layer": layer,
                "kind": "went_down",
                "severity": "critical",
                "prev_status": prev_status,
                "curr_status": curr_status,
                "message": f"layer went down: {prev_status} → {curr_status}",
            })
            continue
        if prev_status != "live" and curr_status == "live":
            findings.append({
                "layer": layer,
                "kind": "came_back",
                "severity": "info",
                "prev_status": prev_status,
                "curr_status": curr_status,
                "message": (
                    f"layer came back online: {prev_status} → live "
                    f"({curr.get('feature_count', 0)} features). Consider running "
                    f"--refresh-snapshot {layer} <fixture-path>."
                ),
            })
            continue
        if prev_status == "live" and curr_status == "live":
            prev_count = prev.get("feature_count", 0)
            curr_count = curr.get("feature_count", 0)
            if prev_count and curr_count:
                delta_pct = abs(curr_count - prev_count) / prev_count * 100.0
                if delta_pct > FEATURE_COUNT_DRIFT_PCT:
                    findings.append({
                        "layer": layer,
                        "kind": "count_drift",
                        "severity": "warn",
                        "prev_status": prev_status,
                        "curr_status": curr_status,
                        "prev_count": prev_count,
                        "curr_count": curr_count,
                        "message": (
                            f"feature_count moved {prev_count} → {curr_count} "
                            f"({delta_pct:.1f}% drift)"
                        ),
                    })
    return findings


def _refresh_fixture(*, layer: str, fixture_path: Path) -> int:
    """Pull layer's PR records and overwrite the committed fixture."""
    url = LAYER_URLS.get(layer)
    if url is None:
        print(f"refresh-snapshot: unknown layer {layer!r}", file=sys.stderr)
        return 2
    params = {
        "where": "STATE='PR'",
        "outFields": "*",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": "1000",
    }
    response = httpx.get(url, params=params, timeout=DEFAULT_TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    if response.status_code != 200:
        print(f"refresh-snapshot: HTTP {response.status_code} for {layer}", file=sys.stderr)
        return 3
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        print(f"refresh-snapshot: service error for {layer}: {payload['error']}", file=sys.stderr)
        return 4
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    feature_count = len(payload.get("features") or [])
    try:
        display = fixture_path.relative_to(REPO_ROOT)
    except ValueError:
        display = fixture_path
    print(f"refreshed {display} ({feature_count} features)")
    return 0


def _format_findings(findings: list[dict[str, Any]]) -> str:
    lines = ["hifld status drift:"]
    for f in findings:
        lines.append(f"  - [{f['severity']}] {f['layer']}: {f['message']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Monitor HIFLD layer URLs for drift")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="Compare live observation against the committed baseline (default)")
    group.add_argument("--write-baseline", action="store_true",
                       help="Persist the current observation as the new baseline")
    group.add_argument("--refresh-snapshot", nargs=2, metavar=("LAYER", "PATH"),
                       help="Pull a live layer and overwrite a committed GeoJSON fixture")
    p.add_argument("--baseline-path", type=Path, default=BASELINE_PATH)
    p.add_argument("--from-file", type=Path, default=None,
                   help="Read observations from a JSON file instead of probing live (for tests)")
    args = p.parse_args(argv)

    if args.refresh_snapshot:
        layer, path_str = args.refresh_snapshot
        return _refresh_fixture(layer=layer, fixture_path=Path(path_str))

    if args.from_file:
        current = json.loads(args.from_file.read_text(encoding="utf-8"))
    else:
        current = probe_all_layers()

    if args.write_baseline:
        payload = {
            "_README": (
                "HIFLD per-layer status baseline. Regenerate via "
                "`python scripts/check_hifld_status.py --write-baseline` after manually "
                "verifying a transition (e.g. a URL came back online). M24's oas-monitor.yml "
                "workflow runs --check against this file and notifies Slack on drift."
            ),
            "layers": current,
        }
        args.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
        live = sum(1 for o in current.values() if o.get("status") == "live")
        print(f"wrote baseline: {len(current)} layers, {live} live")
        return 0

    # Default: check.
    if not args.baseline_path.exists():
        print(f"check_hifld_status: baseline missing at {args.baseline_path}", file=sys.stderr)
        return 2
    baseline_payload = json.loads(args.baseline_path.read_text(encoding="utf-8"))
    baseline_layers = baseline_payload.get("layers") or {}
    findings = diff_observations(baseline_layers, current)
    live = sum(1 for o in current.values() if o.get("status") == "live")
    summary = (
        f"hifld: {len(current)} layers probed, {live} live "
        f"({', '.join(sorted(name for name, o in current.items() if o.get('status') == 'live')) or 'none'})"
    )
    if findings:
        print(_format_findings(findings), file=sys.stderr)
        print(summary, file=sys.stderr)
        return 1
    print(summary)
    print("hifld status: in sync ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
