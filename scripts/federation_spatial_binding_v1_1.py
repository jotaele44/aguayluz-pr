#!/usr/bin/env python3
"""Bind AguaYLuz producer records to the federation spatial identity plane.

This adapter is intentionally post-domain-export. It does not replace AguaYLuz
hydrologic, water, power, environmental, or exposure semantics and it never
creates canonical geometry. Identity resolution is permitted only through an
explicit stable-ID/authoritative binding index supplied by the spatial plane.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CONTRACT_VERSION = "federation-spatial-contract/1.1"
PRODUCER = "aguayluz-pr"
FORBIDDEN_SOLE_BASIS = {
    "NAME_ONLY",
    "NORMALIZED_NAME_ONLY",
    "NEAREST_ONLY",
    "PROXIMITY_ONLY",
    "MUNICIPIO_CENTROID",
    "DERIVED_CENTROID",
    "SAME_CATEGORY",
}
STRONG_BASIS = {"STABLE_ID", "AUTHORITATIVE_BINDING", "CERTIFIED_CROSSWALK"}


def stable_key(namespace: str, value: Any) -> str:
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("stable namespace and value are required")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("stable namespace and value are required")
    text = str(value).strip()
    if not text:
        raise ValueError("stable namespace and value are required")
    return f"{PRODUCER}:{namespace.strip()}:{text}"


def normalized_basis(evidence_basis: Sequence[str]) -> tuple[list[str], set[str]]:
    if isinstance(evidence_basis, (str, bytes)) or not isinstance(evidence_basis, Sequence):
        raise ValueError("evidence_basis must be an array of non-empty strings")
    raw_basis = list(evidence_basis)
    if not raw_basis or any(not isinstance(value, str) or not value.strip() for value in raw_basis):
        raise ValueError("evidence_basis must be an array of non-empty strings")
    return raw_basis, {value.strip().upper() for value in raw_basis}


def candidate_ids(canonical_index: Mapping[str, Sequence[str]], key: str) -> list[str]:
    if not isinstance(canonical_index, Mapping):
        raise ValueError("canonical_index must be an object")
    values = canonical_index.get(key, ())
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"canonical_index[{key!r}] must be an array")
    candidates: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"canonical_index[{key!r}] contains an invalid canonical ID")
        candidates.append(value.strip())
    if len(candidates) != len(set(candidates)):
        raise ValueError(f"canonical_index[{key!r}] contains duplicate canonical IDs")
    return sorted(candidates)


def bind_record(
    record: Mapping[str, Any],
    *,
    id_field: str,
    id_namespace: str,
    canonical_index: Mapping[str, Sequence[str]],
    evidence_basis: Sequence[str],
) -> dict[str, Any]:
    """Return a bounded identity-binding candidate for one producer record.

    ``canonical_index`` is owned by the federation spatial plane and maps an
    explicit producer stable key to zero/one/many canonical IDs. This function
    does not perform fuzzy matching, geocoding, nearest-neighbour search, PIP,
    or geometry inference.
    """
    key = stable_key(id_namespace, record.get(id_field))
    raw_basis, basis = normalized_basis(evidence_basis)
    if basis <= FORBIDDEN_SOLE_BASIS:
        raise ValueError("heuristic-only evidence cannot be used for identity binding")

    candidates = candidate_ids(canonical_index, key)
    if not candidates:
        return {
            "contract_version": CONTRACT_VERSION,
            "producer_repo": PRODUCER,
            "producer_key": key,
            "canonical_ids": [],
            "cardinality": "0:1",
            "identity_state": "UNRESOLVED",
            "identity_semantics": "CANDIDATE_NOT_IDENTITY",
            "evidence_basis": sorted(basis),
            "evidence_basis_raw": raw_basis,
        }

    if len(candidates) > 1:
        return {
            "contract_version": CONTRACT_VERSION,
            "producer_repo": PRODUCER,
            "producer_key": key,
            "canonical_ids": candidates,
            "cardinality": "1:N",
            "identity_state": "UNRESOLVED",
            "identity_semantics": "CANDIDATE_NOT_IDENTITY",
            "evidence_basis": sorted(basis),
            "evidence_basis_raw": raw_basis,
        }

    if not (basis & STRONG_BASIS):
        raise ValueError("single-candidate binding still requires stable/authoritative evidence")

    return {
        "contract_version": CONTRACT_VERSION,
        "producer_repo": PRODUCER,
        "producer_key": key,
        "canonical_ids": candidates,
        "cardinality": "1:1",
        "identity_state": "PROVISIONAL",
        "identity_semantics": "IDENTITY_BINDING",
        "evidence_basis": sorted(basis),
        "evidence_basis_raw": raw_basis,
    }
