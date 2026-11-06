"""Backend readiness scoring for source-intelligence V1."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys

GATE_WEIGHTS = {
    "coverage_matrix": 10,
    "immutable_manifestation_runtime": 15,
    "runtime_health_receipts": 10,
    "reference_transport": 10,
    "reference_parser": 15,
    "identity_invariants": 10,
    "known_good_replay": 10,
    "real_jan_feb_source_bytes": 15,
    "api_contract_frozen": 5,
}

def _reference_receipt_path() -> Path:
    module_path = Path(__file__).resolve()
    candidates = []
    runtime_root = getattr(sys, "_MEIPASS", None)
    if runtime_root:
        candidates.append(
            Path(runtime_root)
            / "evidence"
            / "source_intelligence"
            / "eia860m-reference-2026-11-02.json"
        )
    candidates.extend(
        [
            module_path.parents[3]
            / "evidence"
            / "source_intelligence"
            / "eia860m-reference-2026-11-02.json",
            module_path.parents[2]
            / "evidence"
            / "source_intelligence"
            / "eia860m-reference-2026-11-02.json",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


_REFERENCE_RECEIPT = _reference_receipt_path()


@dataclass(frozen=True)
class BackendReadiness:
    score: int
    states: dict[str, str]
    frontend_authorized: bool
    unresolved: tuple[str, ...]


def score_backend_readiness(states: dict[str, str]) -> BackendReadiness:
    unknown = sorted(set(states) - set(GATE_WEIGHTS))
    missing = sorted(set(GATE_WEIGHTS) - set(states))
    if unknown or missing:
        raise ValueError(f"readiness gate mismatch: unknown={unknown}, missing={missing}")
    score = sum(
        weight
        for gate, weight in GATE_WEIGHTS.items()
        if states[gate] == "PASS"
    )
    unresolved = tuple(
        gate for gate in GATE_WEIGHTS if states[gate] != "PASS"
    )
    return BackendReadiness(
        score=score,
        states=dict(states),
        frontend_authorized=score == 100 and not unresolved,
        unresolved=unresolved,
    )


def _reference_certification_states() -> dict[str, str]:
    if not _REFERENCE_RECEIPT.is_file():
        return {
            "immutable_manifestation_runtime": "OPEN_REFERENCE_RECEIPT_MISSING",
            "runtime_health_receipts": "OPEN_REFERENCE_RECEIPT_MISSING",
            "reference_transport": "OPEN_REFERENCE_RECEIPT_MISSING",
            "reference_parser": "OPEN_REFERENCE_RECEIPT_MISSING",
            "identity_invariants": "OPEN_REFERENCE_RECEIPT_MISSING",
            "known_good_replay": "OPEN_REFERENCE_RECEIPT_MISSING",
            "real_jan_feb_source_bytes": "OPEN_REFERENCE_RECEIPT_MISSING",
        }

    payload = json.loads(_REFERENCE_RECEIPT.read_text(encoding="utf-8"))
    invariants = payload.get("invariants") or {}
    replay = payload.get("jan_feb_replay") or {}
    snapshots = payload.get("snapshots") or {}

    transport = (
        payload.get("state") == "PASS"
        and invariants.get("raw_bytes_acquired") is True
        and invariants.get("expected_sha256_verified") is True
        and invariants.get("xlsx_schema_pass") is True
        and set(snapshots) == {"2026-01", "2026-02"}
    )
    parser = (
        invariants.get("operating_pr_parser_pass") is True
        and invariants.get("retired_pr_parser_pass") is True
    )
    identity = invariants.get("plant_generator_identity_pass") is True
    replay_pass = (
        replay.get("intersection") == 20
        and replay.get("a_only") == 0
        and replay.get("b_only") == 0
        and replay.get("union") == 20
        and replay.get("symmetric_difference") == 0
        and replay.get("changed") == 0
        and replay.get("a_nameplate_mw") == 98.1
        and replay.get("b_nameplate_mw") == 98.1
    )
    manifestations = invariants.get("immutable_manifestation_receipts_pass") is True
    health = invariants.get("runtime_health_receipts_pass") is True

    return {
        "immutable_manifestation_runtime": "PASS" if manifestations else "OPEN",
        "runtime_health_receipts": "PASS" if health else "OPEN",
        "reference_transport": "PASS" if transport else "OPEN",
        "reference_parser": "PASS" if parser else "OPEN",
        "identity_invariants": "PASS" if identity else "OPEN",
        "known_good_replay": "PASS" if replay_pass else "OPEN",
        "real_jan_feb_source_bytes": "PASS" if transport else "OPEN",
    }


def current_backend_readiness(
    *,
    coverage_matrix_ready: bool,
    api_contract_frozen: bool = False,
) -> BackendReadiness:
    states = {
        "coverage_matrix": "PASS" if coverage_matrix_ready else "OPEN",
        **_reference_certification_states(),
        "api_contract_frozen": "PASS" if api_contract_frozen else "OPEN",
    }
    return score_backend_readiness(states)
