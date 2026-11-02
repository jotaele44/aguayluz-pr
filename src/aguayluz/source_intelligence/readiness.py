"""Backend readiness scoring for source-intelligence V1."""
from __future__ import annotations

from dataclasses import dataclass

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


def current_backend_readiness(*, coverage_matrix_ready: bool) -> BackendReadiness:
    return score_backend_readiness(
        {
            "coverage_matrix": "PASS" if coverage_matrix_ready else "OPEN",
            "immutable_manifestation_runtime": "IMPLEMENTED_UNQUALIFIED",
            "runtime_health_receipts": "IMPLEMENTED_UNQUALIFIED",
            "reference_transport": "IMPLEMENTED_UNQUALIFIED",
            "reference_parser": "IMPLEMENTED_UNQUALIFIED",
            "identity_invariants": "IMPLEMENTED_UNQUALIFIED",
            "known_good_replay": "DERIVED_FIXTURE_ONLY",
            "real_jan_feb_source_bytes": "BLOCKED_SOURCE_BYTES_UNAVAILABLE",
            "api_contract_frozen": "OPEN",
        }
    )
