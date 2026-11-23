#!/usr/bin/env python3
"""Build the Puerto Rico hydrologic feature inventory from its committed claims.

Offline and deterministic: it reads ``data/hydro/claims_*.jsonl``,
``data/geo/pr_aquifers.geojson``, ``data/utility_assets.jsonl`` (to attach existing asset ids
by USGS site number) and the two ingest receipts, and writes

  * ``data/hydro/features.jsonl``   one row per feature
  * ``data/hydro/links.jsonl``      well-in-aquifer, aquifer hierarchy, candidates
  * ``data/hydro/conflicts.jsonl``  source disagreements, shown and not resolved
  * ``data/hydro/inventory_receipt.json``  coverage range, per-source ledgers, phase scope

``--check`` rebuilds in memory and fails if any committed output differs, so CI can prove
the committed inventory is exactly what its claims produce.

    python scripts/build_hydro_inventory.py
    python scripts/build_hydro_inventory.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import CONFIG_DIR, DATA_DIR  # noqa: E402
from aguayluz import hydro_inventory as hi  # noqa: E402

ASSET_PREFIXES = ("USGSGW_", "USGSFM_", "USGSWQ_")
STAGES = {"aquifers": "ingest_aquifers_receipt.json", "sites": "ingest_sites_receipt.json",
          "names": "ingest_names_receipt.json", "surface": "ingest_surface_receipt.json",
          "infrastructure": "ingest_infrastructure_receipt.json", "wetlands": "ingest_wetlands_receipt.json"}


def asset_ids_by_site(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if '"groundwater_well"' not in line:
                continue
            row = json.loads(line)
            asset = str(row.get("asset_id", ""))
            if row.get("asset_subtype") == "groundwater_well" and asset.startswith(ASSET_PREFIXES):
                out.setdefault(asset.split("_", 1)[1], []).append(asset)
    return {k: sorted(v) for k, v in out.items()}


def build(data_dir: Path, config_dir: Path) -> dict[str, Any]:
    hydro = data_dir / hi.HYDRO_DIR
    claims = []
    for path in sorted(hydro.glob("claims_*.jsonl")):
        claims += hi.read_claims(path)
    stages = {}
    for stage, name in STAGES.items():
        path = hydro / name
        if not path.is_file():
            raise SystemExit(f"build_hydro_inventory: missing {path}; run the ingests first")
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("status") != "PASS":
            raise SystemExit(f"build_hydro_inventory: {name} is not a PASS receipt")
        stages[stage] = receipt
    config = json.loads((config_dir / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    geo = json.loads((data_dir / "geo" / hi.AQUIFER_GEOJSON).read_text(encoding="utf-8"))
    waterbodies = json.loads((data_dir / "geo" / "pr_waterbodies.geojson").read_text(encoding="utf-8"))
    watersheds = json.loads((data_dir / "geo" / "pr_watersheds.geojson").read_text(encoding="utf-8"))
    generated = max(r["run_utc"] for r in stages.values())
    return hi.build_inventory(claims=claims, aquifer_geojson=geo,
                              asset_ids_by_site=asset_ids_by_site(data_dir / "utility_assets.jsonl"),
                              equivalences=config["analyst_name_equivalences"]["pairs"], stage_receipts=stages,
                              now=generated, waterbody_geojson=waterbodies, watershed_geojson=watersheds)


def render(result: dict[str, Any]) -> dict[str, str]:
    def jsonl(rows: list[dict[str, Any]]) -> str:
        return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for r in rows)

    by_type: dict[str, list[dict[str, Any]]] = {t: [] for t in hi.FEATURE_TYPES if t != "stream"}
    for f in result["features"]:
        # 15,881 reaches would not fit one file under the commit limit, so streams go one file per HUC8
        key = f"stream_{f.get('huc8') or 'unknown'}" if f["feature_type"] == "stream" else f["feature_type"]
        by_type.setdefault(key, []).append(f)
    return {**{hi.FEATURES_FILE.format(t): jsonl(rows) for t, rows in by_type.items()},
            hi.LINKS_FILE: jsonl(result["links"]),
            hi.CONFLICTS_FILE: jsonl(result["conflicts"]),
            hi.RECEIPT_FILE: json.dumps(result["receipt"], indent=2, sort_keys=True, ensure_ascii=False) + "\n"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--check", action="store_true", help="fail if the committed outputs differ from a rebuild")
    args = ap.parse_args(argv)
    outputs = render(build(args.data_dir, args.config_dir))
    hydro = args.data_dir / hi.HYDRO_DIR
    if args.check:
        stale = [name for name, text in outputs.items()
                 if not (hydro / name).is_file() or (hydro / name).read_text(encoding="utf-8") != text]
        stale += [p.name for p in hydro.glob(hi.FEATURES_FILE.format("*")) if p.name not in outputs]
        if stale:
            print(f"build_hydro_inventory: committed outputs differ from a rebuild: {', '.join(stale)}", file=sys.stderr)
            return 1
        print("build_hydro_inventory: committed outputs match a rebuild")
        return 0
    for stale in hydro.glob(hi.FEATURES_FILE.format("*")):
        if stale.name not in outputs:
            stale.unlink()
    for name, text in outputs.items():
        hi.atomic_write(hydro / name, text)
    (hydro / "features.jsonl").unlink(missing_ok=True)  # the single-file layout used before per-type files
    receipt = json.loads(outputs[hi.RECEIPT_FILE])
    cov = receipt["coverage"]
    parts = [f"{t} {c['features_lower']}–{c['features_upper']}" if c["features_lower"] != c["features_upper"]
             else f"{t} {c['features_upper']}" for t, c in cov.items()]
    print(f"build_hydro_inventory: {', '.join(parts)}; {receipt['conflicts']} conflicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
