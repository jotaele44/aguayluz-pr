#!/usr/bin/env python3
"""PRDNER aquifer condition bands for the five south-coast USGS observation wells.

Source: the USGS Caribbean-Florida Water Science Center page "Groundwater Levels at
Selected Observation Wells in the South Coast of Puerto Rico"
(``pr.water.usgs.gov/drought/hydro_conditions_selected_wells.html``). Its inline
JavaScript carries, per well, four depth-to-water bands -- Optimum, Observation,
Operational Adjustment, Critical -- that the page attributes to PRDNER. No other
channel publishes them. Evidence tier T2: operational documentation, no effective date.

Per run:

1. ``GET`` the ``.html`` URL with redirects **off**. The extensionless URL 301s to a generic
   landing page; following it would freeze the wrong document and then fail to parse.
2. SHA-256 the exact response bytes and keep them under
   ``data/aquifer_band_snapshots/<sha>.html`` (gitignored) *before* parsing, so a page that
   no longer parses is still preserved as evidence.
3. Parse (``aguayluz.aquifer_bands.parse_page``) -- fail-closed on any structural drift.
4. Bind each well to its ``USGSGW_<site>`` asset by stable id; the page's title only
   corroborates. Arithmetic: SOURCE = RETAINED + EXCLUDED + UNRESOLVED, and any unresolved
   well fails the run (a registry that silently covers four wells of five would mislead).
5. Append a registry revision for a well only when its bands materially changed.
6. Write ``data/aquifer_band_receipt.json``. A failed run keeps the previous success.

Outputs (both committed -- the registry is the revision base the next run diffs against):

  * ``data/aquifer_band_registry.jsonl``  append-only revisions, one per material change
  * ``data/aquifer_band_receipt.json``    latest attempt and latest success

Nothing here reads or alerts on a depth: classification happens at read time from the
registry plus the latest local reading (``aguayluz.aquifer_bands.well_view``). The
``groundwaterwatch.usgs.gov`` "Map and Info" links are recorded, never fetched.

    python scripts/ingest_prdner_well_bands.py                  # live
    python scripts/ingest_prdner_well_bands.py --dry-run        # live fetch, write nothing
    python scripts/ingest_prdner_well_bands.py --src page.html  # offline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz import aquifer_bands as ab  # noqa: E402
from aguayluz.hydromet import USER_AGENT  # noqa: E402

ASSET_PREFIX = "USGSGW_"


class AcquisitionError(RuntimeError):
    """The source did not return the document we asked for."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_clock(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", name.upper()).strip()


# ── acquisition ───────────────────────────────────────────────────────────────
def fetch_page(url: str = ab.PAGE_URL) -> bytes:
    """The page's bytes, or :class:`AcquisitionError` for anything but a plain 200 HTML body."""
    import httpx

    from aguayluz.http_retry import get_with_retry

    # The client is built here, not by get_with_retry, because only a caller-built client can
    # turn redirects off: get_with_retry's own follow_redirects applies to the client it makes.
    with httpx.Client(timeout=60, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        response = get_with_retry(url, client=client)
    if 300 <= response.status_code < 400:
        raise AcquisitionError(
            f"{url} redirected (HTTP {response.status_code}) to {response.headers.get('location')!r}; "
            "refusing to follow, because the redirect target is not this document"
        )
    if response.status_code != 200:
        raise AcquisitionError(f"HTTP {response.status_code} from {url}")
    if "html" not in response.headers.get("content-type", "").lower():
        raise AcquisitionError(f"unexpected content-type {response.headers.get('content-type')!r}")
    return response.content


def load_assets(path: Path) -> dict[str, dict[str, Any]]:
    """Groundwater-well assets by id. Streams the file: it is large and only one prefix matters."""
    assets: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return assets
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if f'"{ASSET_PREFIX}' not in line:
                continue
            row = json.loads(line)
            if str(row.get("asset_id", "")).startswith(ASSET_PREFIX):
                assets[row["asset_id"]] = row
    return assets


# ── binding + revisions ───────────────────────────────────────────────────────
def bind(
    page: ab.ParsedPage, assets: dict[str, dict[str, Any]]
) -> tuple[list[tuple[ab.ParsedWell, dict[str, Any]]], list[str]]:
    """Split the page's wells into bound (stable id AND corroborating title) and unresolved."""
    bound: list[tuple[ab.ParsedWell, dict[str, Any]]] = []
    unresolved: list[str] = []
    for well in page.wells:
        asset = assets.get(f"{ASSET_PREFIX}{well.site_no}")
        if asset is None:
            unresolved.append(f"{well.site_no}: no {ASSET_PREFIX}{well.site_no} asset")
        elif not _norm(str(asset.get("asset_name", ""))).startswith(_norm(well.title)):
            unresolved.append(
                f"{well.site_no}: page title {well.title!r} does not corroborate asset {asset.get('asset_name')!r}"
            )
        else:
            bound.append((well, asset))
    return bound, unresolved


def build_revisions(
    bound: list[tuple[ab.ParsedWell, dict[str, Any]]],
    current: dict[str, dict[str, Any]],
    *,
    source_sha256: str,
    observed_at: datetime,
) -> list[dict[str, Any]]:
    """Registry rows for wells whose material digest differs from their latest revision."""
    rows: list[dict[str, Any]] = []
    for well, asset in bound:
        digest = ab.material_digest(well.bands)
        previous = current.get(well.site_no)
        if previous and previous.get("material_digest") == digest:
            continue
        revision = int(previous["revision"]) + 1 if previous else 1
        rows.append({
            "registry_id": f"AQBAND:{well.site_no}:r{revision}",
            "revision": revision,
            "supersedes": previous["registry_id"] if previous else None,
            "asset_id": asset["asset_id"],
            "site_no": well.site_no,
            "site_name_source": well.title,
            "municipality": str(asset.get("municipality") or "unknown"),
            "parameter_code": ab.PARAMETER_CODE,
            "depth_convention": ab.DEPTH_CONVENTION,
            "bands": [b.to_json() for b in well.bands],
            "axis_max_ft": well.axis_max_ft,
            "material_digest": digest,
            "authority_claim": ab.AUTHORITY_CLAIM,
            "evidence_tier": ab.EVIDENCE_TIER,
            "effective_date": None,
            "effective_date_status": ab.EFFECTIVE_DATE_STATUS,
            "source_url": ab.PAGE_URL,
            "reference_url": well.reference_url,
            "source_byte_sha256": source_sha256,
            "first_observed_utc": _iso(observed_at),
            "ladder_discrepancies": list(well.discrepancies),
        })
    return rows


def arithmetic(source: int, retained: int, excluded: int, unresolved: int) -> dict[str, Any]:
    accounted = retained + excluded + unresolved
    return {
        "source": source, "retained": retained, "excluded": excluded, "unresolved": unresolved,
        "accounted": accounted, "delta": source - accounted,
        "state": "PASS" if source == accounted else "FAIL",
    }


def receipt_entry(
    previous: dict[str, Any] | None, *, status: str, attempted_at: datetime,
    error: str | None, success: dict[str, Any] | None,
) -> dict[str, Any]:
    """A failure keeps the previous success, so an outage never erases what was last verified."""
    entry = {
        "schema_version": ab.RECEIPT_SCHEMA,
        "source_id": ab.SOURCE_ID,
        "last_attempt_utc": _iso(attempted_at),
        "last_status": status,
        "last_error": error if status == "FAIL" else None,
        "last_success_utc": (previous or {}).get("last_success_utc"),
        "last_success": (previous or {}).get("last_success"),
    }
    if status == "PASS":
        entry["last_success_utc"] = _iso(attempted_at)
        entry["last_success"] = success
    return entry


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", type=Path, help="offline copy of the page (no network at all)")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--assets", type=Path, default=None, help="default <data-dir>/utility_assets.jsonl")
    ap.add_argument("--now", help="override the run clock (ISO 8601), for reproducible tests")
    ap.add_argument("--dry-run", action="store_true", help="fetch and build; write nothing")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    now = _parse_clock(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print("--now is not a valid ISO 8601 timestamp", file=sys.stderr)
        return 2
    data_dir: Path = args.data_dir
    registry_path = data_dir / ab.REGISTRY_FILE
    receipt_path = data_dir / ab.RECEIPT_FILE
    assets_path = args.assets or data_dir / "utility_assets.jsonl"
    previous_receipt = ab.load_receipt(data_dir)

    def fail(message: str) -> int:
        print(f"ingest_prdner_well_bands: FAIL — {message}", file=sys.stderr)
        if not args.dry_run:
            entry = receipt_entry(previous_receipt, status="FAIL", attempted_at=now, error=message, success=None)
            ab.atomic_write(receipt_path, json.dumps(entry, indent=2, sort_keys=True) + "\n")
        return 1

    try:
        payload = args.src.read_bytes() if args.src else fetch_page()
    except Exception as exc:  # noqa: BLE001 - any acquisition failure is a FAIL receipt
        return fail(f"could not acquire the page: {exc}")

    digest = hashlib.sha256(payload).hexdigest()
    if not args.dry_run:
        snapshot = data_dir / ab.SNAPSHOT_DIRNAME / f"{digest}.html"
        if not snapshot.exists():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(payload)

    try:
        page = ab.parse_page(payload)
    except ab.BandPageError as exc:
        return fail(f"the page no longer parses ({digest[:12]}): {exc}")

    bound, unresolved = bind(page, load_assets(assets_path))
    counts = arithmetic(len(page.wells), len(bound), 0, len(unresolved))
    if counts["state"] != "PASS" or unresolved:
        return fail(f"binding did not close ({counts}); " + "; ".join(unresolved))

    existing_text = registry_path.read_text(encoding="utf-8") if registry_path.is_file() else ""
    current = ab.current_registry(ab.read_jsonl(registry_path))
    new_rows = build_revisions(bound, current, source_sha256=digest, observed_at=now)

    summary = {
        "byte_sha256": digest,
        "source_url": ab.PAGE_URL,
        "retrieved_utc": _iso(now),
        "arithmetic": counts,
        "revisions_appended": len(new_rows),
        "wells": [w.site_no for w, _ in bound],
        "ladder_discrepancies": {w.site_no: list(w.discrepancies) for w, _ in bound if w.discrepancies},
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, **summary}, indent=2, sort_keys=True))
        return 0

    if new_rows:
        # Append to the existing bytes rather than re-serialising them, so history is never rewritten.
        appended = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in new_rows)
        ab.atomic_write(registry_path, existing_text + appended)
    entry = receipt_entry(previous_receipt, status="PASS", attempted_at=now, error=None, success=summary)
    ab.atomic_write(receipt_path, json.dumps(entry, indent=2, sort_keys=True) + "\n")
    print(
        f"ingest_prdner_well_bands: PASS — {len(page.wells)} wells bound, "
        f"{len(new_rows)} revision(s) appended, bytes {digest[:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
