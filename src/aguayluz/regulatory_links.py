"""Entity-link candidate generation for the regulatory ingestion framework.

Turns ``RegulatoryObservation`` rows into ``RegulatoryEntityLink`` candidates
proposing a connection to an already-materialized AguaLuz asset
(``data/utility_assets.jsonl``). Pure functions only — no I/O, no wall-clock, no
promotion. Follows the evidence classes and required contradiction checks in
``docs/regulatory_ingestion_framework_v0_1.md``.

Currently implements the **hard identifier** evidence class for USGS site numbers
only, because USGS is the only live provider (``src/aguayluz/regulatory_adapters/``)
and every USGS-derived ``utility_assets.jsonl`` row already carries its site number
verbatim in its ``asset_id`` (``USGS_<site_no>``, ``USGSGW_<site_no>``,
``USGSWQ_<site_no>``, ``USGSFM_<site_no>`` — see ``scripts/ingest_usgs_*.py``). Other
evidence classes (strong/spatial composite, weak lexical) and other providers are
later increments, once there is real data to match against.

This module **never emits ``decision_state="approved"``** — the design doc is explicit
that adapters/generators must not perform entity promotion. Only a human, through
``POST /regulatory/links/{candidate_id}/decide`` (``server/backend/regulatory_api.py``),
may approve a candidate.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

#: asset_id prefixes this module knows to encode a bare USGS site number as
#: ``f"{prefix}_{usgs_site_no}"``. Mirrors what scripts/ingest_usgs_*.py actually
#: writes into data/utility_assets.jsonl.
USGS_ASSET_PREFIXES: tuple[str, ...] = ("USGS", "USGSGW", "USGSWQ", "USGSFM")


def _geo_key(name: Any) -> str:
    """unaccent + upper. Mirrors aguayluz.water_alerts._geo_key / aguayluz.impact._geo_key."""
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def _county_to_municipio_key(county_name: str) -> str:
    """USGS ``county_name`` carries a trailing 'Municipio' PR municipio names lack."""
    stripped = str(county_name)
    for suffix in (" Municipio", " municipio"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    return _geo_key(stripped)


def build_asset_link_index(
    assets: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Index ``utility_assets.jsonl`` for candidate generation.

    Returns ``(usgs_site_no -> [asset_id, ...], asset_id -> municipality)``. A site
    number can legitimately back more than one asset row (e.g. a well carries both a
    ``USGSGW_`` daily-values asset and a ``USGSFM_`` discrete-measurement asset — see
    ``scripts/ingest_usgs_field_measurements.py``'s docstring), so every matching row
    gets its own candidate rather than being collapsed.
    """
    by_site_no: dict[str, list[str]] = {}
    municipality_by_asset: dict[str, str] = {}
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id:
            continue
        if asset.get("municipality"):
            municipality_by_asset[asset_id] = str(asset["municipality"])
        for prefix in USGS_ASSET_PREFIXES:
            if asset_id.startswith(f"{prefix}_"):
                site_no = asset_id[len(prefix) + 1 :]
                by_site_no.setdefault(site_no, []).append(asset_id)
                break
    return by_site_no, municipality_by_asset


def _candidate_id(observation_id: str, asset_id: str) -> str:
    """Deterministic id from (observation_id, asset_id) only — never from decision
    state or contradictions, so a candidate keeps a stable identity across
    regeneration runs regardless of what a human later decides about it."""
    material = f"{observation_id}\0{asset_id}".encode()
    return f"AYL_REGLINK_{hashlib.sha256(material).hexdigest()[:24]}"


def generate_candidates(
    observation: dict[str, Any],
    site_no_index: dict[str, list[str]],
    municipality_by_asset: dict[str, str],
) -> list[dict[str, Any]]:
    """Propose entity-link candidates for one observation.

    Only ever emits ``decision_state`` in ``{"proposed", "needs_review"}``. A
    municipality mismatch between the observation's own reported county and the
    candidate asset's recorded municipality is the one contradiction check
    implemented so far (the design doc's required list also covers distance, parcel,
    operating-date, legal-entity, duplicate-identifier, and explicit-separation —
    left for when a provider/evidence class that can actually populate them lands);
    when it fires, the candidate starts at ``needs_review`` rather than ``proposed``.
    """
    candidates: list[dict[str, Any]] = []
    identifiers = observation.get("identifiers") or []
    site_nos = [i["value"] for i in identifiers if i.get("scheme") == "usgs_site_no"]
    if not site_nos:
        return candidates

    payload = observation.get("payload") or {}
    raw_county = payload.get("county_name")
    obs_county_key = _county_to_municipio_key(raw_county) if raw_county else None

    for site_no in site_nos:
        for asset_id in site_no_index.get(site_no, []):
            contradictions: list[dict[str, Any]] = []
            asset_municipality = municipality_by_asset.get(asset_id)
            # "unknown" is this corpus's placeholder for missing data (see e.g.
            # scripts/ingest_usgs_water_quality.py), not a genuine municipality claim
            # to disagree with — flagging it would be a false contradiction on every
            # asset the ingest simply never resolved a municipality for.
            if asset_municipality and _geo_key(asset_municipality) == "UNKNOWN":
                asset_municipality = None
            if obs_county_key and asset_municipality and obs_county_key != _geo_key(asset_municipality):
                contradictions.append({
                    "kind": "municipality",
                    "detail": (
                        f"Observation reports county {raw_county!r}; "
                        f"asset {asset_id} is recorded in municipality {asset_municipality!r}."
                    ),
                    "evidence_observation_ids": [observation["observation_id"]],
                })
            candidates.append({
                "candidate_id": _candidate_id(observation["observation_id"], asset_id),
                "observation_id": observation["observation_id"],
                "candidate_asset_id": asset_id,
                "decision_state": "needs_review" if contradictions else "proposed",
                "match_strength": "hard_identifier",
                "score": 1.0,
                "match_features": [{
                    "feature": "provider_identifier",
                    "value": f"usgs_site_no:{site_no}",
                    "source_observation_id": observation["observation_id"],
                }],
                "contradictions": contradictions,
                "created_at": observation["retrieved_at"],
            })
    return candidates


def generate_all_candidates(
    observations: list[dict[str, Any]], assets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Candidates for every observation against the given asset corpus."""
    site_no_index, municipality_by_asset = build_asset_link_index(assets)
    candidates: list[dict[str, Any]] = []
    for observation in observations:
        candidates.extend(generate_candidates(observation, site_no_index, municipality_by_asset))
    return candidates
