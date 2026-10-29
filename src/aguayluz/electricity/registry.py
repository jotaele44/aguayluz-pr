"""Read-only temporal source identities; no inferred crosswalks or winners."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from aguayluz.electricity.evidence import GeneratorClaim, SourceReceipt, StrictModel
from aguayluz.electricity.review import claim_identifier
from aguayluz.electricity.store import EvidenceStore

SourceSystem = Literal["EIA-860M", "EIA-860", "EIA-923"]


class RegistryConflict(ValueError):
    """The caller must refresh its pinned scientific revision."""


class RegistryQuery(StrictModel):
    entity_kind: Literal["plant", "generator"] = "generator"
    source_system: SourceSystem | None = None
    plant_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    search: str = Field(default="", max_length=100)
    at: AwareDatetime | None = None
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=20, ge=1, le=100)
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def pinned_pages(self) -> RegistryQuery:
        if self.offset and self.revision is None:
            raise ValueError("continuation pages require a source revision")
        if any(ord(char) < 32 for char in self.search):
            raise ValueError("control characters refused")
        return self


class RegistryEntity(StrictModel):
    entity_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_kind: Literal["plant", "generator"]
    source_system: SourceSystem
    plant_id: str
    generator_id: str | None
    identity_basis: Literal["SOURCE_GENERATOR_IDENTIFIER", "GENERATOR_SOURCE_PLANT_ID_REFERENCE"]
    names: list[str]
    statuses: list[str]
    generator_ids: list[str]
    selected_claim_count: int = Field(ge=0)
    history_claim_count: int = Field(ge=1)
    conflicting_pair_count: int = Field(ge=0)
    evidence_class: Literal["SOURCE_CANDIDATE"] = "SOURCE_CANDIDATE"
    review_state: Literal["AUDIT_ONLY"] = "AUDIT_ONLY"


class RegistryClaim(StrictModel):
    claim_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim: GeneratorClaim
    selected_at: bool
    conflicting_claim_ids: list[str]


class RegistryPage(StrictModel):
    schema_version: Literal["aguayluz.electricity-registry/v1"] = "aguayluz.electricity-registry/v1"
    producer: Literal["aguayluz-pr"] = "aguayluz-pr"
    jurisdiction: Literal["PR"] = "PR"
    certification: Literal["NOT_CERTIFIED"] = "NOT_CERTIFIED"
    canonical_promotion: Literal["BLOCKED"] = "BLOCKED"
    source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    interval_semantics: Literal["HALF_OPEN_SOURCE_ASSERTIONS_NOT_OPERATIONAL_STATE"] = "HALF_OPEN_SOURCE_ASSERTIONS_NOT_OPERATIONAL_STATE"
    availability: Literal["UNAVAILABLE", "AVAILABLE_AUDIT_ONLY"]
    selection: RegistryQuery
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_offset: int | None
    entities: list[RegistryEntity]


class RegistryHistory(StrictModel):
    schema_version: Literal["aguayluz.electricity-registry-history/v1"] = "aguayluz.electricity-registry-history/v1"
    producer: Literal["aguayluz-pr"] = "aguayluz-pr"
    jurisdiction: Literal["PR"] = "PR"
    certification: Literal["NOT_CERTIFIED"] = "NOT_CERTIFIED"
    canonical_promotion: Literal["BLOCKED"] = "BLOCKED"
    source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    at: AwareDatetime | None
    entity: RegistryEntity
    total: int = Field(ge=1)
    offset: int = Field(ge=0)
    next_offset: int | None
    claims: list[RegistryClaim]
    sources: list[SourceReceipt]


def source_entity_id(claim: GeneratorClaim, kind: Literal["plant", "generator"]) -> str:
    """Tuple encoding preserves literal IDs and avoids delimiter collisions."""
    key = ["aguayluz.electricity-source-identity/v1", kind, claim.source_system, claim.plant_id]
    if kind == "generator":
        key.append(claim.generator_id)
    return hashlib.sha256(json.dumps(key, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _selected(claim: GeneratorClaim, at: datetime | None) -> bool:
    return at is None or (claim.valid_from <= at and (claim.valid_to is None or at < claim.valid_to))


def _conflicts(claims: list[GeneratorClaim]) -> dict[str, set[str]]:
    result = {claim_identifier(c.model_dump(mode="json")): set() for c in claims}
    groups: dict[tuple, list[GeneratorClaim]] = {}
    for claim in claims:
        groups.setdefault((claim.source_system, claim.plant_id, claim.generator_id), []).append(claim)
    for group in groups.values():
        ordered = sorted(group, key=lambda c: (c.valid_from, claim_identifier(c.model_dump(mode="json"))))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                if left.valid_to is not None and right.valid_from >= left.valid_to:
                    break
                if (left.name, left.status, left.nameplate_mw) != (right.name, right.status, right.nameplate_mw):
                    a, b = (claim_identifier(c.model_dump(mode="json")) for c in (left, right))
                    result[a].add(b)
                    result[b].add(a)
    return result


class SourceRegistry:
    """Snapshot once, verify raw evidence, then serve deterministic bounded pages."""

    def __init__(self, store: EvidenceStore, revision: str | None = None):
        snapshot = store.snapshot()
        self.revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if revision is not None and revision != self.revision:
            raise RegistryConflict("ELECTRICITY_REGISTRY_REVISION_CHANGED")
        self.sources = snapshot["sources"]
        self.groups: dict[str, tuple[str, list[GeneratorClaim]]] = {}
        for raw in snapshot["claims"]:
            claim = GeneratorClaim.model_validate(raw)
            for kind in ("plant", "generator"):
                identifier = source_entity_id(claim, kind)
                self.groups.setdefault(identifier, (kind, []))[1].append(claim)

    def _summary(self, identifier: str, at: datetime | None) -> RegistryEntity:
        kind, history = self.groups[identifier]
        first = history[0]
        selected = [c for c in history if _selected(c, at)]
        conflicts = _conflicts(selected)
        return RegistryEntity(entity_id=identifier, entity_kind=kind, source_system=first.source_system,
                              plant_id=first.plant_id, generator_id=first.generator_id if kind == "generator" else None,
                              identity_basis="SOURCE_GENERATOR_IDENTIFIER" if kind == "generator" else "GENERATOR_SOURCE_PLANT_ID_REFERENCE",
                              names=sorted({c.name for c in selected}), statuses=sorted({c.status for c in selected}),
                              generator_ids=sorted({c.generator_id for c in selected}),
                              selected_claim_count=len(selected), history_claim_count=len(history),
                              conflicting_pair_count=sum(len(v) for v in conflicts.values()) // 2)

    def page(self, query: RegistryQuery) -> dict:
        if query.revision is not None and query.revision != self.revision:
            raise RegistryConflict("ELECTRICITY_REGISTRY_REVISION_CHANGED")
        entities = []
        for identifier, (kind, history) in self.groups.items():
            first = history[0]
            if kind != query.entity_kind or (query.source_system and first.source_system != query.source_system):
                continue
            if query.plant_id and first.plant_id != query.plant_id:
                continue
            selected = [c for c in history if _selected(c, query.at)]
            # Case-sensitive literal substring search is display filtering only.
            if not selected or (query.search and not any(query.search in value for c in selected
                    for value in (c.plant_id, c.generator_id, c.name))):
                continue
            entities.append(self._summary(identifier, query.at))
        entities.sort(key=lambda e: (e.source_system, e.plant_id, e.generator_id or "", e.entity_id))
        end = query.offset + query.limit
        return RegistryPage(source_revision=self.revision, selection=query,
                            availability="AVAILABLE_AUDIT_ONLY" if entities else "UNAVAILABLE",
                            entities=entities[query.offset:end], total=len(entities), offset=query.offset,
                            next_offset=end if end < len(entities) else None).model_dump(mode="json")

    def history(self, identifier: str, query: RegistryQuery) -> dict:
        if query.revision is None or query.revision != self.revision:
            raise RegistryConflict("ELECTRICITY_REGISTRY_REVISION_CHANGED")
        if identifier not in self.groups:
            raise KeyError(identifier)
        _, claims = self.groups[identifier]
        conflicts = _conflicts(claims)
        ordered = sorted(claims, key=lambda c: (c.valid_from, claim_identifier(c.model_dump(mode="json"))))
        selected = ordered[query.offset:query.offset + query.limit]
        digests = {c.receipt_sha256 for c in selected}
        return RegistryHistory(source_revision=self.revision, at=query.at, entity=self._summary(identifier, query.at),
                               total=len(ordered), offset=query.offset,
                               next_offset=query.offset + query.limit if query.offset + query.limit < len(ordered) else None,
                               claims=[RegistryClaim(claim_id=claim_identifier(c.model_dump(mode="json")), claim=c,
                                          selected_at=_selected(c, query.at),
                                          conflicting_claim_ids=sorted(conflicts[claim_identifier(c.model_dump(mode="json"))])) for c in selected],
                               sources=[SourceReceipt.model_validate(s) for s in self.sources if s["sha256"] in digests]).model_dump(mode="json")
