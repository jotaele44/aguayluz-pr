#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA_PATH = ROOT / "schemas" / "federation_spatial_manifest_v1.schema.json"
HEX40 = re.compile(r"^[a-f0-9]{40}$")
REQUIRED_CONTRACTS = {"feature", "layer", "map_runtime", "offline_package", "impact_report"}
REQUIRED_CERTIFICATION_GATES = (
    "schema",
    "geometry",
    "tests",
    "postgis",
    "security",
    "performance",
    "desktop",
    "ios",
    "federation",
)
ALLOWED_GATE_STATES = {
    "PASS",
    "FAIL",
    "OPEN",
    "BLOCKED",
    "PROVISIONAL",
    "AUDIT_ONLY",
    "UNRESOLVED",
    "UNKNOWN",
    "NOT_APPLICABLE",
}


def _schema_problems(manifest: dict[str, Any]) -> list[str]:
    try:
        schema = json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaError) as exc:
        return [f"cannot validate spatial manifest schema: {exc}"]
    validator = Draft202012Validator(schema)
    problems: list[str] = []
    for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        problems.append(f"manifest schema {location}: {error.message}")
    return problems


def validate_manifest(manifest: dict[str, Any], *, certification: bool) -> list[str]:
    problems: list[str] = _schema_problems(manifest)
    if manifest.get("contract_version") != "federation-spatial-manifest/1.0":
        problems.append("wrong contract_version")
    if manifest.get("producer_repo") != "aguayluz-pr":
        problems.append("producer_repo mismatch")
    if manifest.get("cross_repo", {}).get("identity_default") != "CANDIDATE_NOT_IDENTITY":
        problems.append("identity default must fail closed")
    if manifest.get("cross_repo", {}).get("hub_correlation_authority") != "thehub-pr":
        problems.append("hub correlation authority drift")
    if not HEX40.fullmatch(str(manifest.get("frozen_base_sha", ""))):
        problems.append("invalid frozen_base_sha")

    contracts = manifest.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != REQUIRED_CONTRACTS:
        problems.append("contract path set mismatch")
        contracts = {} if not isinstance(contracts, dict) else contracts
    for label, rel in contracts.items():
        p = ROOT / str(rel)
        if not p.is_file():
            problems.append(f"missing {label}: {rel}")
        else:
            try:
                schema_doc = json.loads(p.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema_doc)
            except (OSError, UnicodeError, json.JSONDecodeError, SchemaError) as exc:
                problems.append(f"invalid JSON schema {rel}: {exc}")

    storage = manifest.get("storage")
    if not isinstance(storage, dict):
        problems.append("storage object is required")
        storage = {}
    for key in ("postgis_migration", "mvt_migration"):
        rel = storage.get(key)
        if not rel or not (ROOT / str(rel)).is_file():
            problems.append(f"missing storage artifact: {key}")
    if storage.get("ownership") != "REPO_LOCAL":
        problems.append("storage ownership must be REPO_LOCAL")

    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        problems.append("gates object is required")
        gates = {}
    missing_gates = [gate for gate in REQUIRED_CERTIFICATION_GATES if gate not in gates]
    if missing_gates:
        problems.append(f"missing certification gates: {missing_gates}")
    extra_gates = sorted(set(gates) - set(REQUIRED_CERTIFICATION_GATES))
    if extra_gates:
        problems.append(f"unexpected certification gates: {extra_gates}")
    for gate in REQUIRED_CERTIFICATION_GATES:
        if gate not in gates:
            continue
        state = gates[gate]
        if not isinstance(state, str) or state not in ALLOWED_GATE_STATES:
            problems.append(f"invalid gate state {gate}={state!r}")
        elif certification and state != "PASS":
            problems.append(f"certification gate {gate} is {state}, expected PASS")

    return problems


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the AguaYLuz federation spatial manifest. Certification is fail-closed by default."
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="structural audit only; OPEN/BLOCKED gate states are reported but do not cause exit failure",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "AUDIT" if args.audit else "CERTIFICATION"
    try:
        manifest = json.loads((ROOT / "federation.spatial.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - fail closed at the boundary
        print(json.dumps({"ok": False, "mode": mode, "problems": [f"cannot read spatial manifest: {exc}"]}, indent=2))
        return 1
    if not isinstance(manifest, dict):
        print(json.dumps({"ok": False, "mode": mode, "problems": ["spatial manifest root must be an object"]}, indent=2))
        return 1

    problems = validate_manifest(manifest, certification=not args.audit)
    gates = manifest.get("gates", {}) if isinstance(manifest.get("gates"), dict) else {}
    certification_ready = not problems and all(
        gates.get(gate) == "PASS" for gate in REQUIRED_CERTIFICATION_GATES
    )
    payload = {
        "ok": not problems,
        "mode": mode,
        "producer_repo": "aguayluz-pr",
        "certification_ready": certification_ready,
        "certification_state": "PASS" if certification_ready else "BLOCKED",
        "gates": {gate: gates.get(gate, "MISSING") for gate in REQUIRED_CERTIFICATION_GATES},
        "problems": problems,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
