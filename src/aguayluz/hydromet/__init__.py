"""NWS hydromet plane: Puerto Rico hydrometeorological observations and outlooks.

The plane reuses the hazard-plane models (:mod:`aguayluz.hazard_plane`) under the
``HYDROMETEOROLOGY`` family, but keeps its rows in dedicated, committed files so the
dashboard, the desktop app and the alert promoters all see the same state:

* ``data/hydromet_records.jsonl``        — HazardRecord revisions
* ``data/hydromet_relationships.jsonl``  — evidence-classed bindings to assets/municipios
* ``data/hydromet_manifestations.jsonl`` — frozen source responses (byte SHA-256)
* ``data/hydromet_receipts.json``        — per-source run receipts (freshness/failure)
* ``data/nwps_gauge_state.jsonl``        — current per-gauge NWPS snapshot

Raw response bytes go under ``data/hydromet_snapshots/<source_id>/`` (gitignored).

This package module holds constants only. :mod:`aguayluz.hydromet.store` is
stdlib + pydantic so the backend can import it; :mod:`aguayluz.hydromet.spatial`
needs shapely and is imported only by the ingest scripts.
"""
from __future__ import annotations

#: canonical_event_id prefix → owning source. Each ingest only rewrites its own prefix.
SOURCE_PREFIXES: dict[str, str] = {
    "nwps_gauges": "NWPS_GAUGE:",
    "stage_iv_pr": "STAGEIV_QPE:",
}

#: Puerto Rico query envelope (lon/lat, EPSG:4326) shared by every hydromet source.
PR_ENVELOPE: tuple[float, float, float, float] = (-67.95, 17.85, -65.2, 18.55)

#: House User-Agent, matching the NWS/NHC ingesters.
USER_AGENT = "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"

__all__ = ["SOURCE_PREFIXES", "PR_ENVELOPE", "USER_AGENT"]
