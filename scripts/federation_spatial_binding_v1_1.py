#!/usr/bin/env python3
"""Bind AguaYLuz producer records to the federation spatial identity plane.

This adapter is intentionally post-domain-export. It does not replace AguaYLuz
hydrologic, water, power, environmental, or exposure semantics and it never
creates canonical geometry. Identity resolution is permitted only through an
explicit stable-ID/authoritative binding index supplied by the spatial plane.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

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
    text = "" if value is None else str(value).strip()
    if not namespace or not text:
        raise ValueError("stable namespace and value are required")
    return f"{PRODUCER}:{namespace}:{text}"


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
    basis = {str(v) for v in evidence_basis}
    if not basis:
        raise ValueError("evidence_basis is required")
    if basis <= FORBIDDEN_SOLE_BASIS:
        raise ValueError("heuristic-only evidence cannot be used for identity binding")

    candidates = [str(v) for v in canonical_index.get(key, ()) if str(v)]
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
        }

    unique = sorted(set(candidates))
    if len(unique) > 1:
        return {
            "contract_version": CONTRACT_VERSION,
            "producer_repo": PRODUCER,
            "producer_key": key,
            "canonical_ids": unique,
            "cardinality": "1:N",
            "identity_state": "UNRESOLVED",
            "identity_semantics": "CANDIDATE_NOT_IDENTITY",
            "evidence_basis": sorted(basis),
        }

    if not (basis & STRONG_BASIS):
        raise ValueError("single-candidate binding still requires stable/authoritative evidence")

    return {
        "contract_version": CONTRACT_VERSION,
        "producer_repo": PRODUCER,
        "producer_key": key,
        "canonical_ids": unique,
        "cardinality": "1:1",
        "identity_state": "PROVISIONAL",
        "identity_semantics": "IDENTITY_BINDING",
        "evidence_basis": sorted(basis),
    }
