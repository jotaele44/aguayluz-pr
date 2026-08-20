#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

SIGE_LAYER = "https://sige.pr.gov/server/rest/services/MIPR/CalidadAmbiente/MapServer/5"
AAA_2015_ZIP = "https://gis.otg.pr.gov/Downloads/AAA/GDB_NAD83_2011.gdb.zip"
USER_AGENT = "AguaYLuz-PR/EBAS-authoritative-enumerator-audit"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": path.as_posix(), "size": len(data), "sha256": sha256_bytes(data)}


def request_bytes(url: str, *, attempts: int = 4, timeout: int = 60) -> tuple[bytes, dict[str, Any]]:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read()
                return data, {
                    "url": response.geturl(),
                    "status": getattr(response, "status", None),
                    "content_type": response.headers.get("Content-Type"),
                    "content_length_header": response.headers.get("Content-Length"),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "attempt": attempt,
                }
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"request failed after {attempts} attempts: {url}: {last!r}")


def json_request(base: str, params: dict[str, Any], raw_path: Path) -> tuple[Any, dict[str, Any]]:
    url = base + "?" + urllib.parse.urlencode(params, doseq=True)
    data, receipt = request_bytes(url)
    file_meta = write_bytes(raw_path, data)
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"non-JSON response from {url}: {exc}") from exc
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"ArcGIS error from {url}: {payload['error']!r}")
    receipt.update(file_meta)
    return payload, receipt


def acquire_sige(out: Path) -> dict[str, Any]:
    raw = out / "sige_raw"
    result: dict[str, Any] = {
        "source": "SIGE Estaciones de Bomba de Aguas Usadas",
        "layer_url": SIGE_LAYER,
        "state": "BLOCKED",
        "complete": False,
        "receipts": [],
    }
    try:
        metadata, receipt = json_request(SIGE_LAYER, {"f": "pjson"}, raw / "metadata.json")
        result["receipts"].append(receipt)
        query = SIGE_LAYER + "/query"
        count_payload, receipt = json_request(
            query,
            {"where": "1=1", "returnCountOnly": "true", "f": "json"},
            raw / "count.json",
        )
        result["receipts"].append(receipt)
        ids_payload, receipt = json_request(
            query,
            {"where": "1=1", "returnIdsOnly": "true", "f": "json"},
            raw / "ids.json",
        )
        result["receipts"].append(receipt)
        count = int(count_payload["count"])
        object_id_field = ids_payload.get("objectIdFieldName") or metadata.get("objectIdField") or "OBJECTID"
        object_ids = [int(x) for x in ids_payload.get("objectIds", [])]
        if len(object_ids) != len(set(object_ids)):
            raise RuntimeError("returnIdsOnly contains duplicate object IDs")
        if count != len(object_ids):
            raise RuntimeError(f"count/ID mismatch: count={count} ids={len(object_ids)}")

        max_record_count = int(metadata.get("maxRecordCount") or 2000)
        batch_size = max(1, min(max_record_count, 1000))
        features: list[dict[str, Any]] = []
        seen: set[int] = set()
        page_receipts: list[dict[str, Any]] = []
        for page_no, start in enumerate(range(0, len(object_ids), batch_size), start=1):
            batch = object_ids[start : start + batch_size]
            payload, receipt = json_request(
                query,
                {
                    "objectIds": ",".join(str(x) for x in batch),
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "f": "json",
                },
                raw / f"features_{page_no:04d}.json",
            )
            page_receipts.append(receipt)
            rows = payload.get("features", [])
            for feature in rows:
                attrs = feature.get("attributes") or {}
                oid = attrs.get(object_id_field)
                if oid is None:
                    raise RuntimeError(f"feature missing {object_id_field}")
                oid = int(oid)
                if oid in seen:
                    raise RuntimeError(f"duplicate feature object ID {oid}")
                seen.add(oid)
                features.append(feature)
        result["receipts"].extend(page_receipts)
        if seen != set(object_ids):
            missing = sorted(set(object_ids) - seen)[:20]
            extra = sorted(seen - set(object_ids))[:20]
            raise RuntimeError(f"feature/ID conservation failed: missing={missing} extra={extra}")
        if len(features) != count:
            raise RuntimeError(f"feature/count mismatch: features={len(features)} count={count}")

        feature_path = out / "sige_ebas_features.jsonl"
        with feature_path.open("w", encoding="utf-8") as handle:
            for feature in sorted(features, key=lambda f: int((f.get("attributes") or {})[object_id_field])):
                handle.write(json.dumps(feature, ensure_ascii=False, sort_keys=True) + "\n")
        result.update(
            {
                "state": "RETRIEVED_COMPLETE",
                "complete": True,
                "count": count,
                "object_id_field": object_id_field,
                "object_id_count": len(object_ids),
                "feature_count": len(features),
                "max_record_count": max_record_count,
                "batch_size": batch_size,
                "page_count": len(page_receipts),
                "spatial_reference": metadata.get("extent", {}).get("spatialReference"),
                "fields": metadata.get("fields", []),
                "advanced_query_capabilities": metadata.get("advancedQueryCapabilities", {}),
                "feature_file": {
                    "path": feature_path.as_posix(),
                    "size": feature_path.stat().st_size,
                    "sha256": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
                },
            }
        )
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def inspect_gdb(zip_path: Path, out: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"state": "ARCHIVE_RETRIEVED_LAYER_INSPECTION_BLOCKED", "layers": []}
    extract_dir = out / "aaa_2015_gdb_extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.testzip()
            members = archive.namelist()
            result["zip_member_count"] = len(members)
            result["zip_members_sha256"] = sha256_bytes("\n".join(members).encode("utf-8"))
            archive.extractall(extract_dir)
        gdb_dirs = sorted(p for p in extract_dir.rglob("*.gdb") if p.is_dir())
        result["gdb_directories"] = [p.relative_to(out).as_posix() for p in gdb_dirs]
        if not gdb_dirs:
            result["error"] = "no .gdb directory found after extraction"
            return result
        try:
            import fiona  # type: ignore
        except Exception as exc:
            result["error"] = f"fiona unavailable: {exc!r}"
            return result
        layers: list[dict[str, Any]] = []
        for gdb in gdb_dirs:
            for layer_name in fiona.listlayers(gdb):
                with fiona.open(gdb, layer=layer_name) as src:
                    entry = {
                        "gdb": gdb.relative_to(out).as_posix(),
                        "name": layer_name,
                        "feature_count": len(src),
                        "geometry": src.schema.get("geometry"),
                        "properties": dict(src.schema.get("properties") or {}),
                        "crs": src.crs.to_string() if getattr(src, "crs", None) else None,
                    }
                    layers.append(entry)
        result["layers"] = layers
        result["state"] = "ARCHIVE_RETRIEVED_LAYERS_ENUMERATED"
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def acquire_aaa_2015(out: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": "Official Puerto Rico GIS 2015 AAA file geodatabase",
        "url": AAA_2015_ZIP,
        "state": "BLOCKED",
        "complete": False,
    }
    try:
        data, receipt = request_bytes(AAA_2015_ZIP, attempts=5, timeout=120)
        zip_path = out / "GDB_NAD83_2011.gdb.zip"
        file_meta = write_bytes(zip_path, data)
        receipt.update(file_meta)
        result["receipt"] = receipt
        result["archive"] = file_meta
        inspection = inspect_gdb(zip_path, out)
        result["inspection"] = inspection
        result["state"] = inspection["state"]
        result["complete"] = inspection["state"] == "ARCHIVE_RETRIEVED_LAYERS_ENUMERATED"
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sige = acquire_sige(args.out)
    aaa = acquire_aaa_2015(args.out)
    report = {
        "schema_version": "aguayluz.ebas-authoritative-acquisition/v0.1",
        "identity_effect": "none",
        "physical_asset_count_claimed": False,
        "current_denominator_claimed": False,
        "pr_wide_denominator_claimed": False,
        "sige": sige,
        "aaa_2015": aaa,
    }
    report_path = args.out / "ebas_authoritative_acquisition.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "sige_state": sige["state"],
        "sige_count": sige.get("count"),
        "aaa_2015_state": aaa["state"],
        "aaa_2015_archive_sha256": (aaa.get("archive") or {}).get("sha256"),
        "aaa_2015_layer_count": len((aaa.get("inspection") or {}).get("layers", [])),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
