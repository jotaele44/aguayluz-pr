"""Asset identity, pressure-zone, and hydraulic-topology projection."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .contracts import HYDRAULIC_EDGE_TYPES, SCHEMA_GRAPH, stable_id, unique
from .operational_adapter_contracts import OperationalAdapterError, _required_text


class OperationalGraphMixin:
    def _materialize_graph(
        self,
        records: list[dict[str, Any]],
        bundle: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        assets_by_id: dict[str, dict[str, Any]] = {}
        asset_aliases: dict[str, str] = {}
        conflicts: set[str] = set()
        blockers: list[str] = []

        identity_records = [item for item in records if item["input_kind"] == "asset_identity"]
        for record in identity_records:
            payload = record["payload"]
            try:
                asset = self._adapt_asset(record)
            except OperationalAdapterError as exc:
                blockers.append(f"asset_identity_rejected:{record['input_id']}:{exc}")
                continue
            source_ref = _required_text(payload, "source_asset_id")
            canonical_id = asset["asset_id"]
            prior_alias = asset_aliases.get(source_ref)
            if prior_alias and prior_alias != canonical_id:
                conflicts.update({source_ref, prior_alias, canonical_id})
                blockers.append(f"source_identifier_conflict:{source_ref}")
                continue
            prior_asset = assets_by_id.get(canonical_id)
            if prior_asset and self._asset_signature(prior_asset) != self._asset_signature(asset):
                conflicts.update({source_ref, canonical_id})
                blockers.append(f"canonical_asset_conflict:{canonical_id}")
                continue
            asset_aliases[source_ref] = canonical_id
            asset_aliases[canonical_id] = canonical_id
            assets_by_id[canonical_id] = asset

        if conflicts:
            conflicted_ids = {asset_aliases.get(value, value) for value in conflicts}
            assets_by_id = {
                key: value for key, value in assets_by_id.items() if key not in conflicted_ids
            }
            asset_aliases = {
                key: value
                for key, value in asset_aliases.items()
                if key not in conflicts and value not in conflicted_ids
            }

        membership_records = [
            item for item in records if item["input_kind"] == "pressure_zone_membership"
        ]
        for record in membership_records:
            payload = record["payload"]
            asset_id = asset_aliases.get(str(payload.get("asset_ref")))
            zone_id = asset_aliases.get(str(payload.get("pressure_zone_ref")))
            service_id = asset_aliases.get(str(payload.get("service_area_ref")))
            if not asset_id or not zone_id:
                blockers.append(f"pressure_zone_membership_unresolved:{record['input_id']}")
                continue
            if assets_by_id[zone_id]["asset_type"] != "pressure_zone":
                blockers.append(f"pressure_zone_reference_not_zone:{record['input_id']}")
                continue
            assets_by_id[asset_id]["pressure_zone_id"] = zone_id
            if service_id:
                assets_by_id[asset_id]["service_area_id"] = service_id

        edges_by_id: dict[str, dict[str, Any]] = {}
        edge_aliases: dict[str, str] = {}
        topology_records = [
            item for item in records if item["input_kind"] == "hydraulic_topology"
        ]
        for record in topology_records:
            payload = record["payload"]
            source_edge_id = str(payload.get("source_edge_id") or record["input_id"])
            from_id = asset_aliases.get(str(payload.get("from_asset_ref")))
            to_id = asset_aliases.get(str(payload.get("to_asset_ref")))
            if not from_id or not to_id:
                blockers.append(f"topology_endpoint_unresolved:{record['input_id']}")
                continue
            try:
                edge = self._adapt_edge(record, from_id, to_id)
            except OperationalAdapterError as exc:
                blockers.append(f"topology_rejected:{record['input_id']}:{exc}")
                continue
            prior_edge = edges_by_id.get(edge["edge_id"])
            if prior_edge and prior_edge != edge:
                blockers.append(f"canonical_edge_conflict:{edge['edge_id']}")
                continue
            edge_aliases[source_edge_id] = edge["edge_id"]
            edge_aliases[edge["edge_id"]] = edge["edge_id"]
            edges_by_id[edge["edge_id"]] = edge

        if not assets_by_id:
            return {
                "graph": None,
                "asset_aliases": asset_aliases,
                "edge_aliases": edge_aliases,
                "blockers": unique(blockers or ["no_admissible_assets"]),
            }

        eligible_hydraulic_edges = [
            edge
            for edge in edges_by_id.values()
            if edge["edge_type"] in HYDRAULIC_EDGE_TYPES
            and edge["topology_state"] != "unresolved"
        ]
        if not eligible_hydraulic_edges:
            blockers.append("hydraulic_topology_absent")

        graph = {
            "schema_version": SCHEMA_GRAPH,
            "graph_id": stable_id(
                "AYL_FLG",
                {
                    "bundle_id": bundle["bundle_id"],
                    "assets": sorted(assets_by_id),
                    "edges": sorted(edges_by_id),
                },
            ),
            "effective_at": as_of.isoformat(),
            "assets": sorted(assets_by_id.values(), key=lambda item: item["asset_id"]),
            "edges": sorted(edges_by_id.values(), key=lambda item: item["edge_id"]),
        }
        return {
            "graph": graph,
            "asset_aliases": asset_aliases,
            "edge_aliases": edge_aliases,
            "blockers": unique(blockers),
        }

    def _adapt_asset(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = record["payload"]
        source_asset_id = _required_text(payload, "source_asset_id")
        canonical = payload.get("canonical_asset_id")
        asset_id = str(canonical) if canonical else stable_id(
            "AYL_OPASSET",
            [record["source_id"], source_asset_id],
        ).upper()
        asset_type = _required_text(payload, "asset_type")
        return {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "name": str(payload.get("name") or source_asset_id),
            "system_id": payload.get("system_id"),
            "pressure_zone_id": payload.get("pressure_zone_id"),
            "service_area_id": payload.get("service_area_id"),
            "disclosure": record["disclosure"],
            "attributes": {
                **dict(payload.get("attributes") or {}),
                "source_asset_id": source_asset_id,
                "source_id": record["source_id"],
                "authority": record["authority"],
                "evidence_tier": record["evidence_tier"],
                "synthetic_fixture": record["authority"] == "synthetic_fixture",
            },
        }

    @staticmethod
    def _asset_signature(asset: dict[str, Any]) -> tuple[Any, ...]:
        return (
            asset["asset_type"],
            asset["name"],
            asset.get("system_id"),
            asset.get("disclosure"),
        )

    def _adapt_edge(
        self,
        record: dict[str, Any],
        from_asset_id: str,
        to_asset_id: str,
    ) -> dict[str, Any]:
        payload = record["payload"]
        edge_type = _required_text(payload, "edge_type")
        if edge_type not in HYDRAULIC_EDGE_TYPES:
            raise OperationalAdapterError("operational_topology_must_be_hydraulic")
        topology_state = str(payload.get("topology_state") or "unresolved")
        if topology_state not in {
            "operator_declared",
            "public_authoritative",
            "inferred",
            "unresolved",
        }:
            raise OperationalAdapterError("invalid_operational_topology_state")
        source_edge_id = str(payload.get("source_edge_id") or record["input_id"])
        canonical = payload.get("canonical_edge_id")
        edge_id = str(canonical) if canonical else stable_id(
            "AYL_EDGE_OP",
            [record["source_id"], source_edge_id, from_asset_id, to_asset_id, edge_type],
        ).upper()
        return {
            "edge_id": edge_id,
            "from_asset_id": from_asset_id,
            "to_asset_id": to_asset_id,
            "edge_type": edge_type,
            "topology_state": topology_state,
            "attributes": {
                **dict(payload.get("attributes") or {}),
                "source_edge_id": source_edge_id,
                "source_id": record["source_id"],
                "authority": record["authority"],
                "synthetic_fixture": record["authority"] == "synthetic_fixture",
            },
        }
