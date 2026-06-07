#!/usr/bin/env python3
"""Diff the live EPA WATERS OpenAPI surface against a committed shape snapshot.

What "shape" means: per-path × method, the response-200 schema component reference
(e.g. `/v1/pointindexing GET → #/components/responses/x414`). If the path set,
method set, or response references change, our adapters might silently break.

Two modes:
  --write-snapshot   Fetch live OAS, compute shape, write tests/baseline/waters_oas_shape.json.
                     Use this after manually accepting an upstream change.
  --check (default)  Fetch live OAS, compute shape, diff against the committed snapshot.
                     Exits non-zero on any drift; M23 CI uses this to fail and notify.

The script does NOT touch the production WATERS gates — drift here means an
operator needs to look. After the operator confirms the change is safe, they
re-run with --write-snapshot and commit the new snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "tests" / "baseline" / "waters_oas_shape.json"
OAS_URL = "https://api.epa.gov/waters/oas30"
DEFAULT_TIMEOUT_S = 30.0
USER_AGENT = "aguayluz-pr/0.1 m23-oas-monitor (+https://github.com/jotaele44/aguayluz-pr)"

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def fetch_oas(*, timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Pull the live OpenAPI document. Raises httpx.HTTPError on transport failure."""
    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(OAS_URL)
        response.raise_for_status()
        return response.json()


def compute_shape(oas: dict[str, Any]) -> dict[str, Any]:
    """Reduce the OAS document to a deterministic shape signature.

    The signature ignores irrelevant churn (descriptions, examples, server URLs,
    parameter ordering) and captures what would actually break our adapters:
      - the set of paths
      - per path, the set of HTTP methods
      - per method, the response-200 schema component reference
    """
    paths = oas.get("paths", {}) or {}
    out_paths: dict[str, dict[str, str | None]] = {}
    for path, ops in sorted(paths.items()):
        if not isinstance(ops, dict):
            continue
        per_method: dict[str, str | None] = {}
        for method in sorted(ops):
            if method.lower() not in _HTTP_METHODS:
                continue
            op = ops[method] or {}
            responses = (op.get("responses") or {})
            ok = responses.get("200") or responses.get("default") or {}
            # EPA's OAS puts `$ref` on the response object itself rather than
            # on the inner schema. Check both shapes — the inner schema $ref
            # form is also valid OpenAPI and would catch a future format flip.
            ref = ok.get("$ref")
            if ref is None:
                content = (ok.get("content") or {}).get("application/json") or {}
                schema = content.get("schema") or {}
                ref = schema.get("$ref")
            per_method[method.lower()] = ref
        out_paths[path] = per_method
    return {
        "version": "1.0",
        "info_version": (oas.get("info") or {}).get("version"),
        "server_url": ((oas.get("servers") or [{}])[0] or {}).get("url"),
        "paths": out_paths,
    }


def shape_signature(shape: dict[str, Any]) -> str:
    """SHA-256 over the canonical serialization — stable across re-runs with identical shape."""
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode("utf-8")).hexdigest()


def _diff_paths(prev: dict[str, Any], curr: dict[str, Any]) -> list[str]:
    """Human-readable diff between two shape `paths` dicts."""
    findings: list[str] = []
    prev_paths = set(prev.keys())
    curr_paths = set(curr.keys())
    for added in sorted(curr_paths - prev_paths):
        findings.append(f"path added: {added}")
    for removed in sorted(prev_paths - curr_paths):
        findings.append(f"path removed: {removed}")
    for shared in sorted(prev_paths & curr_paths):
        prev_methods = prev[shared] or {}
        curr_methods = curr[shared] or {}
        added_methods = sorted(set(curr_methods) - set(prev_methods))
        removed_methods = sorted(set(prev_methods) - set(curr_methods))
        for m in added_methods:
            findings.append(f"  {shared}: method added: {m}")
        for m in removed_methods:
            findings.append(f"  {shared}: method removed: {m}")
        for m in sorted(set(prev_methods) & set(curr_methods)):
            if prev_methods.get(m) != curr_methods.get(m):
                findings.append(
                    f"  {shared} {m.upper()}: response shape changed "
                    f"{prev_methods.get(m)!r} → {curr_methods.get(m)!r}"
                )
    return findings


def diff_shapes(prev: dict[str, Any], curr: dict[str, Any]) -> list[str]:
    """Return a list of findings; empty list means shapes match."""
    findings: list[str] = []
    if prev.get("server_url") != curr.get("server_url"):
        findings.append(
            f"server_url changed: {prev.get('server_url')!r} → {curr.get('server_url')!r}"
        )
    if prev.get("info_version") != curr.get("info_version"):
        findings.append(
            f"info.version changed: {prev.get('info_version')!r} → {curr.get('info_version')!r}"
        )
    findings.extend(_diff_paths(prev.get("paths") or {}, curr.get("paths") or {}))
    return findings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diff live WATERS OAS shape vs committed snapshot")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="Compare live shape against committed snapshot (default)")
    group.add_argument("--write-snapshot", action="store_true",
                       help="Write live shape to tests/baseline/waters_oas_shape.json")
    p.add_argument("--from-file", type=Path, default=None,
                   help="Read OAS from a local JSON file instead of the live URL (for tests)")
    p.add_argument("--snapshot-path", type=Path, default=SNAPSHOT_PATH)
    args = p.parse_args(argv)

    oas = (
        json.loads(args.from_file.read_text(encoding="utf-8"))
        if args.from_file
        else fetch_oas()
    )
    current_shape = compute_shape(oas)
    current_sig = shape_signature(current_shape)

    if args.write_snapshot:
        payload = {
            "_README": (
                "WATERS OAS shape snapshot. Regenerate via `python scripts/check_oas_shape.py "
                "--write-snapshot` after manually verifying an upstream change is safe to adopt. "
                "M23's oas-monitor.yml workflow runs --check against this file and notifies Slack "
                "on drift."
            ),
            "shape_signature": current_sig,
            "shape": current_shape,
        }
        args.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
        path_count = len(current_shape.get("paths") or {})
        try:
            display_path = args.snapshot_path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = args.snapshot_path  # outside repo (e.g. tmp dir in tests)
        print(f"wrote {display_path} ({path_count} paths, sig={current_sig[:16]}…)")
        return 0

    # Default: check.
    if not args.snapshot_path.exists():
        print(f"check_oas_shape: snapshot missing at {args.snapshot_path}", file=sys.stderr)
        return 2
    committed = json.loads(args.snapshot_path.read_text(encoding="utf-8"))
    committed_shape = committed.get("shape") or {}
    findings = diff_shapes(committed_shape, current_shape)
    if findings:
        print("oas shape drift detected:", file=sys.stderr)
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        # Always log the new signature so the operator can copy it into the snapshot.
        print(f"\nlive signature: {current_sig}", file=sys.stderr)
        return 1
    print(f"oas shape: in sync ({current_sig[:16]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
