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
ALLOWED_PAIR_BINDING_STATES = {"UNBOUND", "BOUND_RELATION_NOT_IDENTITY"}


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
    for ev in row["evidence"]:
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
        if not isinstance(row, dict):
            raise HTRContextError("HTR row must be an object")
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise HTRContextError("missing candidate_id")
        if candidate_id in seen:
            raise HTRContextError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        state = row.get("state")
        if state not in ALLOWED_STATES:
            raise HTRContextError(
                f"unsupported HTR state {state!r}; allowed: {sorted(ALLOWED_STATES)}"
            )
        if row.get("identity_state") != "DISTINCT_ENTITIES":
            raise HTRContextError("HTR context must preserve distinct entities")
        if row.get("downstream_semantics") != "CONTEXT_ONLY_NOT_IDENTITY":
            raise HTRContextError("missing context-only HTR contract")
        relation = row.get("relation_type")
        if not isinstance(relation, str) or not relation:
            raise HTRContextError("relation_type must be a non-empty string")
        if relation in FORBIDDEN_RELATIONS:
            raise HTRContextError("identity relation forbidden")
        pair_binding_state = row.get("pair_binding_state")
        if pair_binding_state not in ALLOWED_PAIR_BINDING_STATES:
            raise HTRContextError(
                "unsupported pair_binding_state "
                f"{pair_binding_state!r}; allowed: {sorted(ALLOWED_PAIR_BINDING_STATES)}"
            )
        source_id = row.get("source_observation_id")
        hydro_id = row.get("hydro_entity_id")
        if not isinstance(source_id, str) or not source_id:
            raise HTRContextError("source_observation_id must be a non-empty string")
        if not isinstance(hydro_id, str) or not hydro_id:
            raise HTRContextError("hydro_entity_id must be a non-empty string")
        if source_id == hydro_id:
            raise HTRContextError("HTR endpoints must remain distinct")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
            raise HTRContextError("evidence must be a list of objects")
        connectivity_eligible = _authoritative_pair_binding(row)
        accepted.append(
            {
                "candidate_id": candidate_id,
                "source_observation_id": source_id,
                "hydro_entity_id": hydro_id,
                "relation_type": relation,
                "context_only": True,
                "canonical_identity": False,
                "connectivity_eligible": connectivity_eligible,
                "connectivity_basis": (
                    "AUTHORITATIVE_EXPLICIT_PAIR_BINDING"
                    if connectivity_eligible
                    else "NONE_NAME_PROXIMITY_NOT_CONNECTIVITY"
                ),
                "evidence": evidence,
            }
        )
    return sorted(accepted, key=lambda r: r["candidate_id"])
