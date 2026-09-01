"""Entity promotion for the regulatory ingestion framework.

Consumes ``RegulatoryEntityLink`` rows a human has already approved (through
``POST /regulatory/links/{candidate_id}/decide``, ``server/backend/regulatory_api.py``)
and projects each into a ``RegulatoryEntityCrosswalk`` row — a durable, audited mapping
from a regulatory observation to an AguaLuz asset.

This module **never sets ``decision_state="approved"``** itself; it only reads rows
that already carry that state (which ``schemas/regulatory_entity_link.schema.json``
guarantees means ``decided_at``/``decided_by``/``decision_rationale`` are present and
``contradictions`` is empty — enforced fail-closed by the API before a candidate ever
reaches this state). Promotion here is consumption of an adjudicated decision, not a
decision in its own right — matching the design doc's "Only `approved` links may be
consumed as canonical crosswalk edges" and "Approval must record actor, timestamp,
rationale, evidence references."

Pure function only — no I/O, no wall-clock. The CLI
(``scripts/promote_regulatory_links.py``) does the I/O.
"""

from __future__ import annotations

from typing import Any


def _crosswalk_id(candidate_id: str) -> str:
    """Derive the crosswalk id from the candidate id it promotes.

    One approved candidate always maps to exactly one crosswalk row, so the id is
    just the candidate id with its prefix swapped — traceable at a glance, and
    trivially deterministic (no hashing needed; ``candidate_id`` is already a stable
    hash of (observation_id, candidate_asset_id) per
    ``aguayluz.regulatory_links._candidate_id``).
    """
    return candidate_id.replace("AYL_REGLINK_", "AYL_REGXWALK_", 1)


def promote_approved_links(
    links: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Project every ``approved`` link into a crosswalk row.

    ``observations`` supplies the ``provider`` a crosswalk row records — a link
    itself carries only ``observation_id``, not the provider, so the two stores are
    joined here. A link whose observation cannot be found is skipped rather than
    guessed at (the observation may have been superseded or removed since the link
    was approved; promoting with a fabricated provider would be worse than skipping).
    """
    provider_by_observation = {o["observation_id"]: o["provider"] for o in observations}
    rows: list[dict[str, Any]] = []
    for link in links:
        if link.get("decision_state") != "approved":
            continue
        provider = provider_by_observation.get(link["observation_id"])
        if provider is None:
            continue
        row: dict[str, Any] = {
            "crosswalk_id": _crosswalk_id(link["candidate_id"]),
            "candidate_id": link["candidate_id"],
            "observation_id": link["observation_id"],
            "asset_id": link["candidate_asset_id"],
            "provider": provider,
            "decided_at": link["decided_at"],
            "decided_by": link["decided_by"],
            "decision_rationale": link["decision_rationale"],
        }
        # Optional in the schema, enum-typed with no null member -- omit rather than
        # set to None when the candidate never recorded a match strength.
        if link.get("match_strength") is not None:
            row["match_strength"] = link["match_strength"]
        rows.append(row)
    return rows
