#!/usr/bin/env python3
"""Cross-record invariants for the additive infrastructure ontology sidecars.

JSON Schema validates individual records; this module validates references,
cardinality, duplicate relations, self loops, and temporal interval ordering.
It performs no writes and makes no identity decisions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_interval(record: dict[str, Any], start_key: str, end_key: str) -> None:
    start = _parse_datetime(record.get(start_key))
    end = _parse_datetime(record.get(end_key))
    if start is not None and end is not None and end < start:
        raise ValueError(f"invalid temporal interval for {record}: {end_key} < {start_key}")


def validate_object_graph(objects: list[dict[str, Any]], relations: list[dict[str, Any]]) -> None:
    by_id: dict[str, dict[str, Any]] = {}
    for obj in objects:
        object_id = obj["object_id"]
        if object_id in by_id:
            raise ValueError(f"duplicate object_id: {object_id}")
        by_id[object_id] = obj

    for obj in objects:
        parent_id = obj.get("parent_object_id")
        if parent_id is not None:
            if parent_id not in by_id:
                raise ValueError(f"orphan parent_object_id: {parent_id}")
            if obj["feature_kind"] == "component" and by_id[parent_id]["feature_kind"] != "asset":
                raise ValueError("component parent must be an asset")
        site_id = obj.get("site_id")
        if site_id is not None:
            if site_id not in by_id:
                raise ValueError(f"orphan site_id: {site_id}")
            if by_id[site_id]["feature_kind"] != "site":
                raise ValueError("site_id must reference a site object")

    seen_edges: set[tuple[str, str, str, str | None, str | None]] = set()
    for relation in relations:
        from_id = relation["from_object_id"]
        to_id = relation["to_object_id"]
        if from_id not in by_id or to_id not in by_id:
            raise ValueError(f"orphan relation endpoint: {from_id}->{to_id}")
        if from_id == to_id:
            raise ValueError(f"self-loop relation is not allowed: {relation['relation_id']}")
        _validate_interval(relation, "valid_from", "valid_to")
        signature = (
            from_id,
            relation["relation_type"],
            to_id,
            relation.get("valid_from"),
            relation.get("valid_to"),
        )
        if signature in seen_edges:
            raise ValueError(f"duplicate semantic relation: {signature}")
        seen_edges.add(signature)

        if (
            relation["relation_type"] == "component_of"
            and (
                by_id[from_id]["feature_kind"] != "component"
                or by_id[to_id]["feature_kind"] != "asset"
            )
        ):
            raise ValueError("component_of requires component -> asset")
        if relation["relation_type"] == "located_at" and by_id[to_id]["feature_kind"] != "site":
            raise ValueError("located_at target must be a site")


def validate_sidecar_references(
    objects: list[dict[str, Any]],
    *,
    geometries: list[dict[str, Any]] | None = None,
    lifecycle_events: list[dict[str, Any]] | None = None,
    measurements: list[dict[str, Any]] | None = None,
    entity_roles: list[dict[str, Any]] | None = None,
) -> None:
    object_ids = {obj["object_id"] for obj in objects}
    for collection, start_key, end_key in (
        (geometries or [], "valid_from", "valid_to"),
        (lifecycle_events or [], "valid_from", "valid_to"),
        (measurements or [], "effective_at", "effective_at"),
        (entity_roles or [], "valid_from", "valid_to"),
    ):
        for record in collection:
            if record["object_id"] not in object_ids:
                raise ValueError(f"orphan sidecar object_id: {record['object_id']}")
            if start_key != end_key:
                _validate_interval(record, start_key, end_key)
