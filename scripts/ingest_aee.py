#!/usr/bin/env python3
"""Ingest per-municipality electric breakdowns into aguayluz service_events.jsonl.

This is the modern realization of the AEEIncidents model. The 2019 `mooseburger/
AEEIncidents` project consumed PREPA's (now-defunct) SOAP service, modeling each
electric breakdown as town/area/status/lastUpdate. PREPA's transmission &
distribution passed to LUMA Energy in 2021 and that SOAP endpoint is dead, so we
point the same model at a *modern* per-municipio feed:

    SuperSonicHub1/luma-energy-outages  ->  outages_by_town.json   (CC0)

That payload is ``{ "<MUNICIPIO>": [ {"zone": str, "area": str}, ... ], ... }``
— `{zone, area}` ONLY. It carries no status, no timestamp, and no customer count,
so:
  * the snapshot time comes from --snapshot-ts (the file's git commit time), and
  * we only emit `outage` events (the snapshot lists currently-out zones; deriving
    `restoration` would require diffing successive commits — a future extension).

Each emitted row is a schema-valid service_event (schemas/service_event.schema.json,
additionalProperties=false). Municipio names are resolved to canonical accented
names + centroids via data/geo/pr_municipios.json (Census-derived), so outage
events merge with asset-derived municipality entities in the federation export.

Provenance is honest: evidence_tier=T2, review_status=needs_review (a third-party
snapshot of the utility feed, vs. the T1 government PREPS portal).

Usage:
    curl -fsSL https://raw.githubusercontent.com/SuperSonicHub1/luma-energy-outages/master/outages_by_town.json -o /tmp/outages_by_town.json
    gh api '/repos/SuperSonicHub1/luma-energy-outages/commits?path=outages_by_town.json&per_page=1' --jq '.[0].commit.committer.date'
    python scripts/ingest_aee.py --src /tmp/outages_by_town.json --snapshot-ts <date> --out data/aee_incidents.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT_SRC = "/tmp/outages_by_town.json"
DEFAULT_GEO = "data/geo/pr_municipios.json"
DEFAULT_META = "/tmp/luma_snapshot_manifest.json"
# Pinned to the exact snapshot that produced the committed data/aee_incidents.jsonl.
DEFAULT_SOURCE_REF = (
    "https://github.com/SuperSonicHub1/luma-energy-outages/blob/"
    "e864255cb64712a98260ced8868e40aaa65415d8/outages_by_town.json"
)


def unaccent_upper(name: str) -> str:
    """Fold diacritics + uppercase -> the join key utility feeds use (CATANO)."""
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return " ".join(folded.upper().split())


def load_geo(path: Path) -> dict[str, dict]:
    """Index canonical municipios by their unaccent/upper join key."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {unaccent_upper(m["name"]): m for m in doc["municipios"]}


def _slug(*parts: str, ts: str = "") -> str:
    """Stable [A-Za-z0-9_-] id fragment from a (snapshot_ts, municipio, zone) tuple.

    Including `ts` in the hash distinguishes separate observations of the same zone
    on the same calendar day (different live-fetch runs) while remaining idempotent
    for identical inputs — two calls with the same ts + parts always produce the same
    slug, matching AEEIncidents' dedupe-key intent.
    """
    readable = re.sub(r"[^A-Za-z0-9]+", "_", unaccent_upper(parts[0]).title()).strip("_")
    payload = (ts + "|" if ts else "") + "|".join(p.lower().strip() for p in parts)
    digest = hashlib.sha1(payload.encode()).hexdigest()[:8]
    return f"{readable}_{digest}"


def _event(
    event_id: str,
    affected_area: str,
    municipality: str | None,
    zone: str | None,
    snapshot_ts: str,
    source_ref: str,
    source_hash: str | None = None,
) -> dict:
    """Assemble one schema-valid service_event row (shared by both granularities)."""
    event = {
        "event_id": event_id,
        "event_type": "outage",
        "affected_area": affected_area,
        "municipality": municipality,
        "zone": zone,
        "start_time": snapshot_ts,
        "source_ref": source_ref,
        "evidence_tier": "T2",
        "confidence": 80,
        "review_status": "needs_review",
    }
    if source_hash:
        event["source_hash"] = source_hash
    return event


def build_events(
    doc: dict,
    snapshot_ts: str,
    geo: dict[str, dict],
    source_ref: str,
    granularity: str = "zone",
    source_hash: str | None = None,
) -> list[dict]:
    """Map the LUMA outages-by-town snapshot to service_event rows.

    GRANULARITY (the genuine design choice, now a runtime flag):
      * "zone" (default): ONE event per outage *zone* — the most faithful rendering
        of the AEE town/area model and of the source's grain; preserves sub-municipal
        detail and dedupes via a (municipio, zone) hash.
      * "municipio": ONE aggregated event per affected municipio; the affected zones
        are collapsed into the `zone` field. Coarser, fewer rows, dedupes via a
        (municipio) hash.
    Both modes produce deterministic, unique event_ids so re-runs are idempotent.
    """
    date8 = snapshot_ts[:10].replace("-", "")
    rows: list[dict] = []
    for raw_muni, zones in doc.items():
        if not zones:
            continue  # empty list = municipio currently has no reported outage
        m = geo.get(unaccent_upper(raw_muni))
        canonical = m["name"] if m else str(raw_muni).title()
        municipality = canonical if m else None
        zone_names = [z for z in (str(e.get("zone", "")).strip() for e in zones) if z]

        if granularity == "municipio":
            rows.append(_event(
                event_id=f"AYL_EVT_{date8}_{_slug(raw_muni, ts=snapshot_ts)}",
                affected_area=canonical,
                municipality=municipality,
                zone="; ".join(zone_names) or None,
                snapshot_ts=snapshot_ts, source_ref=source_ref, source_hash=source_hash,
            ))
        else:  # per-zone (default)
            for zone in zone_names or [""]:
                rows.append(_event(
                    event_id=f"AYL_EVT_{date8}_{_slug(raw_muni, zone, ts=snapshot_ts)}",
                    affected_area=f"{canonical} / {zone}" if zone else canonical,
                    municipality=municipality,
                    zone=zone or None,
                    snapshot_ts=snapshot_ts, source_ref=source_ref, source_hash=source_hash,
                ))
    return rows


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_snapshot_provenance(
    src: Path,
    snapshot_ts: str | None,
    source_ref: str | None,
    snapshot_meta: str | None,
) -> tuple[str, str, str | None]:
    """Bind a snapshot to the exact fetch receipt, or require explicit historical provenance."""
    if snapshot_meta:
        meta_path = Path(snapshot_meta)
        if not meta_path.is_file():
            raise ValueError(f"snapshot manifest missing: {meta_path}")
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        entry = doc.get("towns")
        if not isinstance(entry, dict) or entry.get("status") != "PASS":
            raise ValueError("snapshot manifest towns entry is not PASS")
        meta_ts = entry.get("retrieval_utc")
        meta_ref = entry.get("url")
        meta_hash = entry.get("response_sha256")
        if not all(isinstance(v, str) and v for v in (meta_ts, meta_ref, meta_hash)):
            raise ValueError("snapshot manifest towns entry lacks retrieval_utc/url/response_sha256")
        actual_hash = _sha256_path(src)
        if actual_hash != meta_hash:
            raise ValueError(
                f"snapshot byte hash mismatch: manifest={meta_hash} actual={actual_hash}"
            )
        if snapshot_ts is not None and snapshot_ts != meta_ts:
            raise ValueError(
                f"explicit snapshot-ts disagrees with manifest: {snapshot_ts} != {meta_ts}"
            )
        if source_ref is not None and source_ref != meta_ref:
            raise ValueError(
                f"explicit source-ref disagrees with manifest: {source_ref} != {meta_ref}"
            )
        return meta_ts, meta_ref, meta_hash

    if not snapshot_ts:
        raise ValueError("--snapshot-ts is required unless --snapshot-meta is supplied")
    return snapshot_ts, source_ref or DEFAULT_SOURCE_REF, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=DEFAULT_SRC, help="LUMA outages_by_town.json snapshot")
    ap.add_argument("--snapshot-ts", default=None, help="ISO-8601 snapshot time; required without --snapshot-meta")
    ap.add_argument("--geo", default=DEFAULT_GEO)
    ap.add_argument("--source-ref", default=None)
    ap.add_argument("--snapshot-meta", default=None, help="MiLUMA fetch receipt binding exact source bytes")
    ap.add_argument("--granularity", default="zone", choices=["zone", "municipio"],
                    help="one event per outage zone (default) or one aggregated event per municipio")
    ap.add_argument("--out", default="data/aee_incidents.jsonl")
    args = ap.parse_args()

    src = Path(args.src)
    doc = json.loads(src.read_text(encoding="utf-8"))
    geo = load_geo(Path(args.geo))
    try:
        snapshot_ts, source_ref, source_hash = resolve_snapshot_provenance(
            src, args.snapshot_ts, args.source_ref, args.snapshot_meta
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"provenance-invalid: {exc}", file=sys.stderr)
        return 2
    rows = build_events(
        doc,
        snapshot_ts,
        geo,
        source_ref,
        args.granularity,
        source_hash=source_hash,
    )

    unresolved = sorted({r["affected_area"].split(" / ")[0] for r in rows if r["municipality"] is None})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} outage events -> {out}")
    if unresolved:
        print(f"WARNING: {len(unresolved)} municipio name(s) did not resolve to a canonical centroid: {unresolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
