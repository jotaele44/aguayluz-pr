#!/usr/bin/env python3
"""USGS water-use estimates for Puerto Rico: public supply by source, 2010 / 2015 / 2020.

Sources (``config/usgs_water_use_sources.v1.json``), all U.S. Geological Survey:

  * 2020  data release 10.5066/P9HWON2W, Table 1 (xlsx)          tier T1
  * 2015  data release 10.5066/P9POVNC6, Tables 4, 6, 9, 14 (xlsx) tier T1
  * 2010  Open-File Report 2014-1117 (PDF only)                    tier T2, manual transcription

These are static publications, so this producer runs on demand and is not part of
``scripts/refresh.py``. Per run:

1. Read each xlsx -- offline from ``--src-dir`` (default: the byte-identical copies under
   ``tests/fixtures/usgs_water_use/``), or live from ScienceBase with ``--fetch``.
2. SHA-256 the bytes and compare with the pin in the config. A mismatch stops the run: the
   release changed, and a person has to look before new numbers are accepted
   (``--accept-new-bytes`` records the new hash in the receipt; the pin still has to be
   edited by hand). ``--fetch`` also checks ScienceBase's own MD5, and re-downloads the
   2010 PDF to check its hash. The PDF is never parsed.
3. Parse (``aguayluz.water_use``) -- fail-closed on any structural drift.
4. Arithmetic per source: SOURCE rows = RETAINED + EXCLUDED + UNRESOLVED. A municipality
   name that is not in ``data/geo/pr_municipios.json`` is unresolved and fails the run. A
   figure two tables both publish must agree exactly, or the run fails.
5. Rewrite ``data/water_use_estimates.jsonl`` (sorted, deterministic) and write
   ``data/water_use_receipt.json``. A failed run keeps the previous success.

    python scripts/ingest_usgs_water_use.py                 # offline, from the fixtures
    python scripts/ingest_usgs_water_use.py --dry-run       # write nothing
    python scripts/ingest_usgs_water_use.py --fetch         # live, verify MD5 and SHA-256
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import CONFIG_DIR, DATA_DIR  # noqa: E402
from aguayluz import water_use as wu  # noqa: E402

DEFAULT_SRC_DIR = REPO / "tests" / "fixtures" / "usgs_water_use"
MUNICIPIOS = REPO / "data" / "geo" / "pr_municipios.json"
SCIENCEBASE_ITEM = "https://www.sciencebase.gov/catalog/item/{item}?format=json"


class AcquisitionError(RuntimeError):
    """The source did not return the file we asked for."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_clock(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── acquisition ───────────────────────────────────────────────────────────────
def _get(url: str) -> bytes:
    import httpx

    from aguayluz.http_retry import get_with_retry
    from aguayluz.hydromet import USER_AGENT

    with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        response = get_with_retry(url, client=client)
    if response.status_code != 200:
        raise AcquisitionError(f"HTTP {response.status_code} from {url}")
    return response.content


def fetch_xlsx(source: dict[str, Any]) -> bytes:
    """One release file. The download URL is resolved from the item's metadata by file name,

    because ScienceBase's ``__disk__`` URLs are storage addresses, not stable identifiers.
    """
    item = json.loads(_get(SCIENCEBASE_ITEM.format(item=source["sciencebase_item_id"])))
    matches = [f for f in item.get("files", []) if f.get("name") == source["file_name"]]
    if len(matches) != 1:
        raise AcquisitionError(
            f"ScienceBase item {source['sciencebase_item_id']} has {len(matches)} files named {source['file_name']!r}"
        )
    payload = _get(matches[0]["url"])
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    published = (matches[0].get("checksum") or {}).get("value")
    if md5 != published or md5 != source["expected_md5"]:
        raise AcquisitionError(
            f"{source['file_name']}: MD5 {md5} does not match ScienceBase ({published}) and the config "
            f"({source['expected_md5']})"
        )
    return payload


def arithmetic(table: wu.ParsedTable) -> dict[str, Any]:
    excluded = sum(table.excluded.values())
    accounted = table.retained_rows + excluded + len(table.unresolved)
    return {
        "source": table.source_rows, "retained": table.retained_rows, "excluded": excluded,
        "unresolved": len(table.unresolved), "accounted": accounted, "delta": table.source_rows - accounted,
        "state": "PASS" if table.source_rows == accounted and not table.unresolved else "FAIL",
    }


def receipt_entry(
    previous: dict[str, Any] | None, *, status: str, attempted_at: datetime,
    error: str | None, success: dict[str, Any] | None,
) -> dict[str, Any]:
    """A failure keeps the previous success, so a bad run never erases what was last verified."""
    entry = {
        "schema_version": wu.RECEIPT_SCHEMA,
        "source_id": wu.SOURCE_ID,
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


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["year"], row["category"], row["scope"] != "island", row["municipality"] or "", row["record_id"])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-dir", type=Path, default=DEFAULT_SRC_DIR,
                    help="directory holding <source_key>.xlsx (offline; default: the committed fixtures)")
    ap.add_argument("--fetch", action="store_true", help="download from ScienceBase and pubs.usgs.gov instead")
    ap.add_argument("--accept-new-bytes", action="store_true",
                    help="do not fail when a file's SHA-256 differs from the pin (the receipt records the new hash)")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--municipios", type=Path, default=MUNICIPIOS)
    ap.add_argument("--now", help="override the run clock (ISO 8601), for reproducible tests")
    ap.add_argument("--dry-run", action="store_true", help="read and build; write nothing")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    now = _parse_clock(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print("--now is not a valid ISO 8601 timestamp", file=sys.stderr)
        return 2
    data_dir: Path = args.data_dir
    receipt_path = data_dir / wu.RECEIPT_FILE
    previous_receipt = wu.load_receipt(data_dir)

    def fail(message: str) -> int:
        print(f"ingest_usgs_water_use: FAIL — {message}", file=sys.stderr)
        if not args.dry_run:
            entry = receipt_entry(previous_receipt, status="FAIL", attempted_at=now, error=message, success=None)
            wu.atomic_write(receipt_path, json.dumps(entry, indent=2, sort_keys=True) + "\n")
        return 1

    try:
        config = wu.load_sources(args.config_dir)
        municipios = wu.load_municipios(args.municipios)
    except (OSError, ValueError, KeyError) as exc:
        return fail(f"could not load the source registry or the municipality list: {exc}")

    records: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for source in config["sources"]:
        key = source["source_key"]
        try:
            payload = fetch_xlsx(source) if args.fetch else (args.src_dir / f"{key}.xlsx").read_bytes()
        except Exception as exc:  # noqa: BLE001 - any acquisition failure is a FAIL receipt
            return fail(f"could not acquire {key}: {exc}")
        digest = hashlib.sha256(payload).hexdigest()
        if not args.dry_run:
            snapshot = data_dir / wu.SNAPSHOT_DIRNAME / f"{digest}.xlsx"
            if not snapshot.exists():
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(payload)
        pin_matches = digest == source["pinned_sha256"]
        if not pin_matches and not args.accept_new_bytes:
            return fail(f"{key}: SHA-256 {digest} differs from the pin {source['pinned_sha256']}; the release changed")
        try:
            table = wu.parse_source(payload, source, municipios, digest)
        except wu.WaterUseSourceError as exc:
            return fail(f"{key} no longer parses ({digest[:12]}): {exc}")
        counts = arithmetic(table)
        if counts["state"] != "PASS":
            return fail(f"{key}: rows did not close ({counts}); " + "; ".join(table.unresolved))
        records.extend(table.records)
        receipts.append({
            "source_key": key, "byte_sha256": digest, "pin_matches": pin_matches, "md5_verified": bool(args.fetch),
            "arithmetic": counts, "excluded_by_reason": dict(sorted(table.excluded.items())),
            "records": len(table.records),
        })

    block = config["transcription_2010"]
    pdf_digest = block["pinned_sha256"]
    pdf_verified = False
    if args.fetch:
        try:
            pdf_digest = hashlib.sha256(_get(block["download_url"])).hexdigest()
        except Exception as exc:  # noqa: BLE001
            return fail(f"could not acquire {block['source_key']}: {exc}")
        if pdf_digest != block["pinned_sha256"]:
            return fail(
                f"{block['source_key']}: SHA-256 {pdf_digest} differs from the pin; the transcription is bound "
                "to the pinned PDF and must be re-read by a person"
            )
        pdf_verified = True
    table = wu.transcription_records(block, block["pinned_sha256"])
    counts = arithmetic(table)
    if counts["state"] != "PASS":
        return fail(f"{block['source_key']}: rows did not close ({counts}); " + "; ".join(table.unresolved))
    records.extend(table.records)
    receipts.append({
        "source_key": block["source_key"], "byte_sha256": block["pinned_sha256"], "pin_matches": True,
        "md5_verified": False, "pdf_hash_verified_this_run": pdf_verified, "arithmetic": counts,
        "excluded_by_reason": {}, "records": len(table.records),
    })

    # Two tables can publish the same figure (2015 public supply is in Tables 4 and 6). They must
    # agree exactly; the first source in config order is kept and the agreement is recorded.
    unique: dict[str, dict[str, Any]] = {}
    agreements: list[dict[str, str]] = []
    for row in records:
        kept = unique.setdefault(row["record_id"], row)
        if kept is row:
            continue
        fields = ("surface_water_mgd", "groundwater_mgd", "total_mgd")
        if any(kept[f] != row[f] for f in fields):
            return fail(
                f"{row['record_id']}: {kept['source_key']} and {row['source_key']} publish different values "
                f"({[kept[f] for f in fields]} vs {[row[f] for f in fields]})"
            )
        agreements.append({"record_id": row["record_id"], "kept": kept["source_key"], "agrees": row["source_key"]})
    records = list(unique.values())
    records.sort(key=_sort_key)

    summary = {
        "mode": "fetch" if args.fetch else "offline",
        "sources": receipts,
        "records_written": len(records),
        "cross_source_agreements": agreements,
        "years": sorted({r["year"] for r in records}),
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, **summary}, indent=2, sort_keys=True))
        return 0

    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
    wu.atomic_write(data_dir / wu.ESTIMATES_FILE, text)
    entry = receipt_entry(previous_receipt, status="PASS", attempted_at=now, error=None, success=summary)
    wu.atomic_write(receipt_path, json.dumps(entry, indent=2, sort_keys=True) + "\n")
    print(f"ingest_usgs_water_use: PASS — {len(records)} records from {len(receipts)} sources, years {summary['years']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
