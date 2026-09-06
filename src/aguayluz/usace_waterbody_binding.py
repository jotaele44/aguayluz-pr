from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from aguayluz.usace_corpus import discovery_key

CERTIFIED_EVIDENCE = {
    "STABLE_ID",
    "AUTHORITATIVE_BINDING",
    "CERTIFIED_GEOMETRY_PLUS_ALIAS",
    "POINT_IN_POLYGON_PLUS_INDEPENDENT_ALIAS",
}


@dataclass(frozen=True)
class WaterbodyRecord:
    canonical_id: str
    canonical_name: str
    stable_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    municipality: str | None = None


@dataclass(frozen=True)
class BindingCandidate:
    project_raw: str
    waterbody_id: str
    evidence_type: str
    evidence_value: str
    state: str


def discover_name_candidates(
    project_raw: str, waterbodies: Iterable[WaterbodyRecord]
) -> list[BindingCandidate]:
    """Name/alias matching is discovery only and never proves project-waterbody identity."""
    key = discovery_key(project_raw)
    out: list[BindingCandidate] = []
    for waterbody in waterbodies:
        names = (waterbody.canonical_name, *waterbody.aliases)
        if any(discovery_key(name) and discovery_key(name) in key for name in names):
            out.append(
                BindingCandidate(
                    project_raw,
                    waterbody.canonical_id,
                    "NORMALIZED_NAME_ONLY",
                    waterbody.canonical_name,
                    "CANDIDATE_NOT_IDENTITY",
                )
            )
    return out


def bind_with_evidence(
    project_raw: str,
    waterbody: WaterbodyRecord,
    evidence_type: str,
    evidence_value: str,
) -> BindingCandidate:
    state = "PASS" if evidence_type in CERTIFIED_EVIDENCE else "CANDIDATE_NOT_IDENTITY"
    return BindingCandidate(
        project_raw,
        waterbody.canonical_id,
        evidence_type,
        evidence_value,
        state,
    )


def adjudicate(candidates: Iterable[BindingCandidate]) -> dict[str, Any]:
    """Preserve candidate sets; tied top hard evidence remains unresolved."""
    rows = list(candidates)
    passed = [row for row in rows if row.state == "PASS"]
    serialized = [asdict(row) for row in rows]
    if not rows:
        return {"cardinality": "0:1", "state": "UNRESOLVED", "candidates": []}
    if len(passed) == 1:
        return {
            "cardinality": "1:1",
            "state": "PASS",
            "winner": asdict(passed[0]),
            "candidates": serialized,
        }
    if len(passed) > 1:
        return {
            "cardinality": "1:N",
            "state": "UNRESOLVED_TIED_HARD_EVIDENCE",
            "candidates": serialized,
        }
    return {
        "cardinality": f"1:{len(rows)}",
        "state": "CANDIDATE_NOT_IDENTITY",
        "candidates": serialized,
    }
