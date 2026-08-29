"""HTR context adapter for AguaYLuz.

Toponym recurrence is contextual evidence only. Connectivity is eligible only
when TheHub supplies an explicitly pair-bound adjudicated relation supported by
an authoritative source; name/fuzzy/proximity signals can never create it.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ALLOWED_STATES = {"CONTEXT_SUPPORTED", "ADJUDICATED"}
CONNECTIVITY_RELATIONS = {"HYDRAULICALLY_CONNECTED_TO", "ELECTRICALLY_CONNECTED_TO"}
FORBIDDEN_RELATIONS = {"SAME_AS", "IDENTICAL_TO", "CANONICAL_IDENTITY"}


class HTRContextError(ValueError):
    pass


def _authoritative_pair_binding(row: dict[str, Any]) -> bool:
    if row.get("state") != "ADJUDICATED":
        return False
    if row.get("pair_binding_state") != "BOUND_RELATION_NOT_IDENTITY":
        return False
    relation = row.get("relation_type")
    if relation not in CONNECTIVITY_RELATIONS:
        return False
    for ev in row.get("evidence") or []:
        if (
            ev.get("binds_candidate_pair") is True
            and ev.get("authoritative") is True
            and ev.get("relation_type") == relation
            and isinstance(ev.get("source_id"), str)
            and ev.get("source_id")
        ):
            return True
    return False


def consume_htr_context(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise HTRContextError("missing candidate_id")
        if candidate_id in seen:
            raise HTRContextError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        if row.get("state") not in ALLOWED_STATES:
            raise HTRContextError("discovery-only HTR row cannot enter AguaYLuz")
        if row.get("identity_state") != "DISTINCT_ENTITIES":
            raise HTRContextError("HTR context must preserve distinct entities")
        if row.get("downstream_semantics") != "CONTEXT_ONLY_NOT_IDENTITY":
            raise HTRContextError("missing context-only HTR contract")
        if row.get("relation_type") in FORBIDDEN_RELATIONS:
            raise HTRContextError("identity relation forbidden")
        connectivity_eligible = _authoritative_pair_binding(row)
        accepted.append({
            "candidate_id": candidate_id,
            "source_observation_id": row.get("source_observation_id"),
            "hydro_entity_id": row.get("hydro_entity_id"),
            "relation_type": row.get("relation_type"),
            "context_only": True,
            "canonical_identity": False,
            "connectivity_eligible": connectivity_eligible,
            "connectivity_basis": (
                "AUTHORITATIVE_EXPLICIT_PAIR_BINDING"
                if connectivity_eligible
                else "NONE_NAME_PROXIMITY_NOT_CONNECTIVITY"
            ),
            "evidence": row.get("evidence") or [],
        })
    return sorted(accepted, key=lambda r: r["candidate_id"])
