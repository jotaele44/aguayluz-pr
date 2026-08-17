#!/usr/bin/env python3
"""Build a deterministic, bounded AguaYLuz real-data partial export.

This command is intentionally offline and credential-free. It selects whole rows
from committed utility/service datasets, derives only explicitly bounded continuity
candidates, validates every emitted stream against its JSON Schema, and writes a
machine-readable ``PRODUCTION_REAL_DATA_PARTIAL`` manifest.

It does NOT fetch live sources, promote review state, infer feeder identity, invent
recovery projects, or extrapolate EPA WATERS VPU-21 evidence to Puerto Rico-wide
coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker

REPO = Path(__file__).resolve().parent.parent
OUTAGE_TYPES = {"outage", "restoration", "service_interruption"}
FUEL_TOKENS = ("diesel", "fuel oil", "oil", "petroleum", "natural gas", "lng", "coal")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{lineno}: expected object row")
        rows.append(row)
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected object")
    return doc


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load_json(REPO / "schemas" / f"{schema_name}.schema.json")
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_rows(schema_name: str, rows: list[dict[str, Any]]) -> None:
    validator = _validator(schema_name)
    for idx, row in enumerate(rows):
        errors = sorted(validator.iter_errors(row), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"{schema_name} row {idx}: {errors[0].message}")


def _validate_object(schema_name: str, obj: dict[str, Any]) -> None:
    errors = sorted(_validator(schema_name).iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        raise ValueError(f"{schema_name}: {errors[0].message}")


def _is_real_row(row: dict[str, Any], id_field: str) -> bool:
    record_id = str(row.get(id_field) or "").upper()
    source_ref = str(row.get("source_ref") or "").lower()
    if not record_id or record_id.startswith(("TEST_", "EXAMPLE_", "FIXTURE_")):
        return False
    return "example.com" not in source_ref and "localhost" not in source_ref


def _take_sorted(
    rows: list[dict[str, Any]],
    id_field: str,
    limit: int,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    pred = predicate or (lambda _row: True)
    eligible = [row for row in rows if _is_real_row(row, id_field) and pred(row)]
    return sorted(eligible, key=lambda row: str(row[id_field]))[:limit]


def _explicit_fuel_token(asset: dict[str, Any]) -> str | None:
    subtype = str(asset.get("asset_subtype") or "").lower()
    for token in FUEL_TOKENS:
        if token in subtype:
            return token
    return None


def _select_assets(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    usable = [
        row
        for row in rows
        if _is_real_row(row, "asset_id") and row.get("review_status") not in {"rejected", "blocked"}
    ]
    selected: dict[str, dict[str, Any]] = {}

    # Preserve a bounded explicit-fuel subset when the public-derived source row
    # already carries a fuel token. This is candidate classification only.
    fuel_assets = sorted(
        (row for row in usable if row.get("asset_type") == "power" and _explicit_fuel_token(row)),
        key=lambda row: str(row["asset_id"]),
    )[: min(3, limit)]
    for row in fuel_assets:
        selected[str(row["asset_id"])] = row

    # Ensure the partial package contains both water and power domains without
    # aggregating or synthesizing source rows.
    for asset_type in ("power", "water", "wastewater"):
        for row in sorted(
            (r for r in usable if r.get("asset_type") == asset_type),
            key=lambda r: str(r["asset_id"]),
        )[: min(4, limit)]:
            if len(selected) >= limit:
                break
            selected.setdefault(str(row["asset_id"]), row)

    for row in sorted(usable, key=lambda r: str(r["asset_id"])):
        if len(selected) >= limit:
            break
        selected.setdefault(str(row["asset_id"]), row)

    return [selected[key] for key in sorted(selected)]


def _select_outages(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return _take_sorted(
        rows,
        "event_id",
        limit,
        lambda row: row.get("event_type") in OUTAGE_TYPES
        and row.get("review_status") not in {"rejected", "blocked"},
    )


def _continuity_edges(
    dependency_rows: list[dict[str, Any]],
    selected_assets: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for edge in sorted(dependency_rows, key=lambda row: str(row.get("edge_id") or "")):
        edge_id = str(edge.get("edge_id") or "")
        from_id = edge.get("from_node_id")
        to_id = edge.get("to_node_id")
        if not edge_id.startswith("EDGE-WP-") or not from_id or not to_id:
            continue
        if edge.get("evidence_required") is not True:
            raise ValueError(f"{edge_id}: power-water proxy unexpectedly lacks evidence_required=true")
        out.append(
            {
                "edge_id": f"CR-{edge_id}",
                "from_id": str(from_id),
                "to_id": str(to_id),
                "risk_type": "water_asset_power_dependency_candidate",
                "relationship_status": "candidate",
                "identity_binding": "proxy",
                "source_ref": f"data/alert_dependency_edges.jsonl#{edge_id}",
                "confidence": min(int(edge.get("confidence") or 0), 60),
                "review_status": "needs_review",
                "evidence_required": True,
                "notes": str(edge.get("notes") or "Spatial proxy; independent feeder evidence required."),
            }
        )
        if len(out) >= limit:
            break

    # Explicit-fuel tokens are carried from the public EIA/OSM-derived source
    # asset row. They make a fuel-sensitive *candidate*, never a supply-chain fact.
    for asset in sorted(selected_assets, key=lambda row: str(row["asset_id"])):
        token = _explicit_fuel_token(asset)
        if not token:
            continue
        out.append(
            {
                "edge_id": f"CR-FUEL-{asset['asset_id']}-{token.replace(' ', '_').upper()}",
                "from_id": f"fuel:{token}",
                "to_id": str(asset["asset_id"]),
                "risk_type": "fuel_sensitive_candidate",
                "relationship_status": "candidate",
                "identity_binding": "proxy",
                "source_ref": str(asset["source_ref"]),
                "confidence": min(int(asset.get("confidence") or 0), 60),
                "review_status": "needs_review",
                "evidence_required": True,
                "notes": (
                    "Explicit fuel token preserved in asset_subtype; does not establish current "
                    "fuel stock, supplier, delivery route, or outage cause."
                ),
            }
        )

    return sorted(out, key=lambda row: row["edge_id"])[:limit]


def _canonical_jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for row in rows
    )


def _write_stream(path: Path, rows: list[dict[str, Any]]) -> dict[str, int | str]:
    data = _canonical_jsonl(rows)
    path.write_bytes(data)
    return {"sha256": _sha256_bytes(data), "row_count": len(rows), "bytes": len(data)}


def _input_meta(path: Path, row_count: int) -> dict[str, Any]:
    raw = path.read_bytes() if path.is_file() else b""
    return {"path": str(path.relative_to(REPO)), "sha256": _sha256_bytes(raw), "row_count": row_count}


def _require_aware_iso8601(value: str) -> None:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include Z or an explicit UTC offset")


def build(args: argparse.Namespace) -> dict[str, Any]:
    _require_aware_iso8601(args.generated_at)
    assets_path = REPO / args.assets
    events_path = REPO / args.events
    deps_path = REPO / args.dependencies
    recovery_path = REPO / args.recovery_projects
    registry_path = REPO / args.source_registry
    taxonomy_path = REPO / args.taxonomy

    asset_rows = _read_jsonl(assets_path)
    event_rows = _read_jsonl(events_path)
    dependency_rows = _read_jsonl(deps_path)
    recovery_rows = _read_jsonl(recovery_path)
    source_registry = _load_json(registry_path)
    taxonomy = _load_json(taxonomy_path)

    _validate_object("recurring_source_registry", source_registry)
    taxonomy_types = {str(row.get("risk_type")) for row in taxonomy.get("classes", [])}
    required_taxonomy = {"water_asset_power_dependency_candidate", "fuel_sensitive_candidate"}
    if not required_taxonomy.issubset(taxonomy_types):
        raise ValueError("continuity taxonomy lacks required proxy classes")

    selected_assets = _select_assets(asset_rows, args.asset_limit)
    selected_outages = _select_outages(event_rows, args.event_limit)
    selected_recovery = _take_sorted(
        recovery_rows,
        "project_id",
        args.project_limit,
        lambda row: row.get("review_status") not in {"rejected", "blocked"},
    )
    continuity = _continuity_edges(dependency_rows, selected_assets, args.edge_limit)

    if not selected_assets:
        raise ValueError("no real utility assets available for partial export")
    if not selected_outages:
        raise ValueError("no real outage/restoration/service-interruption events available")
    if not any(row["risk_type"] == "water_asset_power_dependency_candidate" for row in continuity):
        raise ValueError("no evidence-gated EDGE-WP-* continuity candidates available")

    _validate_rows("utility_asset", selected_assets)
    _validate_rows("outage_event", selected_outages)
    _validate_rows("recovery_project", selected_recovery)
    _validate_rows("continuity_risk_edge", continuity)

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "utility_assets.jsonl": _write_stream(out_dir / "utility_assets.jsonl", selected_assets),
        "outage_events.jsonl": _write_stream(out_dir / "outage_events.jsonl", selected_outages),
        "recovery_projects.jsonl": _write_stream(
            out_dir / "recovery_projects.jsonl", selected_recovery
        ),
        "continuity_risk_edges.jsonl": _write_stream(
            out_dir / "continuity_risk_edges.jsonl", continuity
        ),
    }

    manifest = {
        "schema_version": "aguayluz_real_data_partial_export_v1",
        "module_id": "aguayluz-pr",
        "data_status": "PRODUCTION_REAL_DATA_PARTIAL",
        "generated_at": args.generated_at,
        "inputs": {
            "utility_assets": _input_meta(assets_path, len(asset_rows)),
            "service_events": _input_meta(events_path, len(event_rows)),
            "alert_dependency_edges": _input_meta(deps_path, len(dependency_rows)),
            "recovery_projects": _input_meta(recovery_path, len(recovery_rows)),
            "source_registry": _input_meta(registry_path, len(source_registry.get("sources", []))),
            "continuity_taxonomy": _input_meta(taxonomy_path, len(taxonomy.get("classes", []))),
        },
        "files": files,
        "coverage": {
            "scope": "Deterministic repository-resident/public-derived sample; not a Puerto Rico-wide completeness claim.",
            "complete": False,
            "utility_assets_selected": len(selected_assets),
            "outage_events_selected": len(selected_outages),
            "recovery_projects_selected": len(selected_recovery),
            "continuity_risk_edges_selected": len(continuity),
            "disclaimer": (
                "Real public-data partial export. Source availability is uneven and point-in-time; "
                "operator/private/credential-gated sources are not substituted or inferred."
            ),
        },
        "caveats": {
            "vpu21_hydro_enrichment": {
                "status": "PROVISIONAL_PARTIAL",
                "scope": (
                    "EPA WATERS/NHDPlus validation is bounded to VPU-21 evidence already present in "
                    "the repository; off-network and no-waterbody outcomes remain explicit."
                ),
                "no_extrapolation": True,
            },
            "power_water_identity": (
                "EDGE-WP relationships are spatial discovery proxies only. Proximity does not prove "
                "feeder/circuit identity; independent authoritative binding evidence is required."
            ),
            "fuel_sensitive": (
                "Fuel-sensitive candidates require an explicit fuel token already present in the "
                "source-derived asset subtype and do not establish current supply, vendor, route, or cause."
            ),
            "live_outage": (
                "MiLUMA acquisition is permission/WAF constrained and PREPS requires an operator snapshot; "
                "this offline package does not fabricate live outage coverage when those inputs are absent."
            ),
        },
        "invariants": {
            "whole_row_selection": True,
            "no_fabricated_recovery_projects": True,
            "no_network_acquisition": True,
            "no_credential_requirement": True,
            "proxy_edges_never_identity": True,
            "deterministic_serialization": True,
        },
    }
    _validate_object("real_data_partial_manifest", manifest)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    (out_dir / "manifest.json").write_bytes(manifest_bytes)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default="data/utility_assets.jsonl")
    parser.add_argument("--events", default="data/service_events.jsonl")
    parser.add_argument("--dependencies", default="data/alert_dependency_edges.jsonl")
    parser.add_argument("--recovery-projects", default="data/recovery_projects.jsonl")
    parser.add_argument("--source-registry", default="registry/utility_source_registry.v1.json")
    parser.add_argument("--taxonomy", default="config/continuity_risk_taxonomy.v1.json")
    parser.add_argument("--out", default="exports/real_data_partial")
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--asset-limit", type=int, default=12)
    parser.add_argument("--event-limit", type=int, default=12)
    parser.add_argument("--project-limit", type=int, default=12)
    parser.add_argument("--edge-limit", type=int, default=12)
    args = parser.parse_args()
    if min(args.asset_limit, args.event_limit, args.project_limit, args.edge_limit) < 0:
        parser.error("limits must be non-negative")
    manifest = build(args)
    print(
        json.dumps(
            {
                "data_status": manifest["data_status"],
                "generated_at": manifest["generated_at"],
                "coverage": manifest["coverage"],
                "manifest": str(Path(args.out) / "manifest.json"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
