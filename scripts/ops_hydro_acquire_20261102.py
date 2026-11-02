#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from pypdf import PdfReader

RUN_UTC = datetime.now(timezone.utc).isoformat()
ROOT = Path(os.environ.get("HYDRO_ACQ_OUT", "hydro-acquisition-out"))
RAW = ROOT / "raw"
TMP = ROOT / "tmp"
RAW.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)

PLANT_IDS = {61225, 61228, 61229, 61230, 61231, 61235, 61236}
EIA860_URLS = {
    "2026-03": "https://www.eia.gov/electricity/data/eia860m/archive/xls/march_generator2026.xlsx",
    "2026-04": "https://www.eia.gov/electricity/data/eia860m/archive/xls/april_generator2026.xlsx",
    "2026-05": "https://www.eia.gov/electricity/data/eia860m/archive/xls/may_generator2026.xlsx",
    "2026-06": "https://www.eia.gov/electricity/data/eia860m/archive/xls/june_generator2026.xlsx",
    "2026-07": "https://www.eia.gov/electricity/data/eia860m/archive/xls/july_generator2026.xlsx",
}
EIA923_URL = "https://www.eia.gov/electricity/data/eia923/xls/f923_2026.zip"
LUMA_INDEX = "https://lumapr.com/monitoreo-de-bps/"
LUMA_GUESSED = {
    "2026-08-28": "https://lumapr.com/wp-content/uploads/2026/08/20260828-Daily-Availability-Report.pdf",
    "2026-08-30": "https://lumapr.com/wp-content/uploads/2026/08/20260830-Daily-Availability-Report.pdf",
}
UA = "AguaYLuz-HydroEvidence/1.0 (+https://github.com/jotaele44/aguayluz-pr)"

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def norm(v: Any) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\n", " ").strip()).lower()

def safe_json(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    return str(v)

class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlparse(req.full_url)
        new = urllib.parse.urlparse(newurl)
        if old.scheme != "https" or new.scheme != "https" or old.hostname != new.hostname:
            raise urllib.error.HTTPError(req.full_url, code, "cross-host/non-https redirect rejected", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

OPENER = urllib.request.build_opener(SameHostRedirect())

def fetch(url: str, max_bytes: int = 250 * 1024 * 1024) -> tuple[bytes, dict[str, Any]]:
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("unsafe URL")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.8",
    })
    with OPENER.open(req, timeout=120) as r:
        final_url = r.geturl()
        fp = urllib.parse.urlparse(final_url)
        if fp.scheme != "https" or fp.hostname != p.hostname:
            raise ValueError("unexpected final URL")
        length = r.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError(f"payload too large: {length}")
        data = r.read(max_bytes + 1)
        if not data or len(data) > max_bytes:
            raise ValueError("empty or oversized payload")
        meta = {
            "requested_url": url,
            "final_url": final_url,
            "content_type": r.headers.get("Content-Type"),
            "content_length_header": length,
            "etag": r.headers.get("ETag"),
            "last_modified": r.headers.get("Last-Modified"),
            "retrieved_utc": RUN_UTC,
        }
        return data, meta

def freeze(source_id: str, label: str, url: str, suffix: str) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "source_id": source_id,
        "label": label,
        "url": url,
        "retrieved_utc": RUN_UTC,
        "state": "QUARANTINED_NOT_PROMOTED",
    }
    try:
        data, meta = fetch(url)
        digest = sha256_bytes(data)
        target = RAW / f"{label}{suffix}"
        target.write_bytes(data)
        rec.update(meta)
        rec.update({
            "state": "RAW_FROZEN_NOT_PARSED",
            "sha256": digest,
            "byte_count": len(data),
            "path": str(target),
        })
    except Exception as e:
        rec["failure_type"] = type(e).__name__
        rec["failure"] = str(e)[:1000]
        code = getattr(e, "code", None)
        if code in (401, 403):
            rec["failure_class"] = "ACCESS_DENIED"
        elif code == 404:
            rec["failure_class"] = "NOT_FOUND_AT_URL"
        elif code == 429 or (isinstance(code, int) and code >= 500):
            rec["failure_class"] = "RETRYABLE_HTTP"
        elif isinstance(e, (TimeoutError, OSError, urllib.error.URLError)):
            rec["failure_class"] = "RETRYABLE_TRANSPORT"
        else:
            rec["failure_class"] = "UNCLASSIFIED_FAILURE"
    return rec

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []

def discover_luma_urls() -> tuple[dict[str, str], dict[str, Any]]:
    found: dict[str, str] = {}
    meta: dict[str, Any] = {"state": "UNRESOLVED"}
    try:
        html, hmeta = fetch(LUMA_INDEX, max_bytes=20 * 1024 * 1024)
        p = LinkParser()
        p.feed(html.decode("utf-8", errors="replace"))
        for href, text in p.links:
            full = urllib.parse.urljoin(LUMA_INDEX, href)
            blob = (href + " " + text).lower()
            if "8/28/2026" in blob or "20260828" in blob or "2026-08-28" in blob:
                found["2026-08-28"] = full
            if "8/30/2026" in blob or "20260830" in blob or "2026-08-30" in blob:
                found["2026-08-30"] = full
        meta = {"state": "DISCOVERED", "index_meta": hmeta, "candidate_count": len(found)}
    except Exception as e:
        meta = {"state": "INDEX_ACCESS_FAILED", "failure_type": type(e).__name__, "failure": str(e)[:1000], "code": getattr(e, "code", None)}
    return found, meta

def dedupe_headers(values: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, v in enumerate(values):
        base = str(v).strip() if v is not None and str(v).strip() else f"__blank_{i+1}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}__{seen[base]}")
    return out

def find_header(ws, require: list[str], scan_rows: int = 25) -> tuple[int, list[str]] | None:
    for r in range(1, scan_rows + 1):
        vals = [c.value for c in ws[r]]
        n = [norm(v) for v in vals]
        if all(any(req in cell for cell in n) for req in require):
            return r, dedupe_headers(vals)
    return None

def col_index(headers: list[str], predicates: list[tuple[str, ...]]) -> int | None:
    nh = [norm(h) for h in headers]
    for pred in predicates:
        for i, h in enumerate(nh):
            if all(token in h for token in pred):
                return i
    return None

def to_int(v: Any) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except Exception:
        return None

def to_float(v: Any) -> float | None:
    if v is None or str(v).strip() in ("", ".", "NA", "N/A"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None

def parse_860(path: Path, period: str) -> tuple[list[dict], list[dict], dict]:
    wb = load_workbook(path, read_only=True, data_only=True)
    candidates = []
    for ws in wb.worksheets:
        h = find_header(ws, ["plant id", "generator id"])
        if h:
            candidates.append((ws, h))
    if not candidates:
        return [], [], {"period": period, "state": "HEADER_NOT_FOUND", "sheets": wb.sheetnames}
    candidates.sort(key=lambda item: (0 if "operat" in item[0].title.lower() else 1, item[0].title))
    ws, (hr, headers) = candidates[0]
    idx_pid = col_index(headers, [("plant","id")])
    idx_gid = col_index(headers, [("generator","id")])
    idx_pname = col_index(headers, [("plant","name")])
    idx_status = col_index(headers, [("status",)])
    idx_np = col_index(headers, [("nameplate","capacity"), ("nameplate",)])
    idx_sum = col_index(headers, [("net","summer","capacity"), ("summer","capacity")])
    idx_win = col_index(headers, [("net","winter","capacity"), ("winter","capacity")])
    idx_pm = col_index(headers, [("prime","mover")])
    idx_es = col_index(headers, [("energy","source","1"), ("energy","source","code","1")])
    source_rows, canonical = [], []
    for rownum, row in enumerate(ws.iter_rows(min_row=hr+1, values_only=True), start=hr+1):
        pid = to_int(row[idx_pid]) if idx_pid is not None and idx_pid < len(row) else None
        if pid not in PLANT_IDS:
            continue
        raw = {headers[i]: safe_json(row[i]) for i in range(min(len(headers), len(row)))}
        source_rows.append({"period": period, "source_file": path.name, "sheet": ws.title, "header_row": hr, "row_number": rownum, "raw": raw})
        canonical.append({
            "period": period,
            "plant_id": pid,
            "plant_name": row[idx_pname] if idx_pname is not None and idx_pname < len(row) else None,
            "generator_id": str(row[idx_gid]).strip() if idx_gid is not None and idx_gid < len(row) and row[idx_gid] is not None else None,
            "status": row[idx_status] if idx_status is not None and idx_status < len(row) else None,
            "nameplate_mw": to_float(row[idx_np]) if idx_np is not None and idx_np < len(row) else None,
            "net_summer_mw": to_float(row[idx_sum]) if idx_sum is not None and idx_sum < len(row) else None,
            "net_winter_mw": to_float(row[idx_win]) if idx_win is not None and idx_win < len(row) else None,
            "prime_mover": row[idx_pm] if idx_pm is not None and idx_pm < len(row) else None,
            "energy_source_1": row[idx_es] if idx_es is not None and idx_es < len(row) else None,
            "source_row_number": rownum,
        })
    keys = [(x["plant_id"], x["generator_id"]) for x in canonical]
    meta = {
        "period": period,
        "state": "PARSED",
        "sheet": ws.title,
        "header_row": hr,
        "source_rows": len(source_rows),
        "canonical_rows": len(canonical),
        "unique_generator_keys": len(set(keys)),
        "duplicate_generator_keys": len(keys) - len(set(keys)),
        "plant_ids": sorted(set(x["plant_id"] for x in canonical)),
        "nameplate_mw_sum": sum(x["nameplate_mw"] for x in canonical if x["nameplate_mw"] is not None),
        "net_summer_mw_sum": sum(x["net_summer_mw"] for x in canonical if x["net_summer_mw"] is not None),
        "net_winter_mw_sum": sum(x["net_winter_mw"] for x in canonical if x["net_winter_mw"] is not None),
        "null_nameplate": sum(x["nameplate_mw"] is None for x in canonical),
        "null_summer": sum(x["net_summer_mw"] is None for x in canonical),
        "null_winter": sum(x["net_winter_mw"] is None for x in canonical),
    }
    return source_rows, canonical, meta

MONTH_TOKENS = {
    "01": ("january", "jan"),
    "02": ("february", "feb"),
    "03": ("march", "mar"),
    "04": ("april", "apr"),
    "05": ("may",),
    "06": ("june", "jun"),
}

def find_month_col(headers: list[str], month: str) -> int | None:
    nh = [norm(h) for h in headers]
    for i, h in enumerate(nh):
        if ("netgen" in h or ("net" in h and "generation" in h)) and any(tok in h for tok in MONTH_TOKENS[month]):
            return i
    return None

def parse_923_zip(path: Path) -> tuple[list[dict], list[dict], dict]:
    extract = TMP / "eia923"
    if extract.exists():
        shutil.rmtree(extract)
    extract.mkdir(parents=True)
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith((".xlsx", ".xlsm")) and not m.startswith("__MACOSX/")]
        for m in members:
            zf.extract(m, extract)
    candidates = []
    for m in members:
        p = extract / m
        try:
            wb = load_workbook(p, read_only=True, data_only=True)
        except Exception:
            continue
        for ws in wb.worksheets:
            h = find_header(ws, ["plant id"], 30)
            if not h:
                continue
            hr, headers = h
            month_cols = {mo: find_month_col(headers, mo) for mo in MONTH_TOKENS}
            if sum(v is not None for v in month_cols.values()) < 6:
                continue
            idx_pid = col_index(headers, [("plant","id")])
            if idx_pid is None:
                continue
            count = 0
            for row in ws.iter_rows(min_row=hr+1, values_only=True):
                pid = to_int(row[idx_pid]) if idx_pid < len(row) else None
                if pid in PLANT_IDS:
                    count += 1
            if count:
                candidates.append((count, m, ws.title, hr, headers, month_cols))
    if not candidates:
        return [], [], {"state": "NO_MATCHING_923_SHEET", "members": members}
    candidates.sort(reverse=True, key=lambda x: (x[0], len(x[4])))
    count, member, sheet_name, hr, headers, month_cols = candidates[0]
    wb = load_workbook(extract / member, read_only=True, data_only=True)
    ws = wb[sheet_name]
    idx_pid = col_index(headers, [("plant","id")])
    idx_pname = col_index(headers, [("plant","name")])
    idx_pm = col_index(headers, [("prime","mover")])
    idx_fuel = col_index(headers, [("aer","fuel","type"), ("reported","fuel"), ("energy","source")])
    source_rows = []
    plant_month = defaultdict(lambda: {"sum": 0.0, "numeric_rows": 0, "null_rows": 0})
    for rownum, row in enumerate(ws.iter_rows(min_row=hr+1, values_only=True), start=hr+1):
        pid = to_int(row[idx_pid]) if idx_pid is not None and idx_pid < len(row) else None
        if pid not in PLANT_IDS:
            continue
        raw = {headers[i]: safe_json(row[i]) for i in range(min(len(headers), len(row)))}
        source_rows.append({
            "source_member": member, "sheet": sheet_name, "header_row": hr, "row_number": rownum,
            "plant_id": pid,
            "plant_name": row[idx_pname] if idx_pname is not None and idx_pname < len(row) else None,
            "prime_mover": row[idx_pm] if idx_pm is not None and idx_pm < len(row) else None,
            "fuel_type": row[idx_fuel] if idx_fuel is not None and idx_fuel < len(row) else None,
            "raw": raw,
        })
        for mo, ci in month_cols.items():
            val = to_float(row[ci]) if ci is not None and ci < len(row) else None
            bucket = plant_month[(pid, mo)]
            if val is None:
                bucket["null_rows"] += 1
            else:
                bucket["sum"] += val
                bucket["numeric_rows"] += 1
    canonical = []
    for pid in sorted(PLANT_IDS):
        for mo in sorted(MONTH_TOKENS):
            b = plant_month[(pid, mo)]
            canonical.append({
                "period": f"2026-{mo}",
                "plant_id": pid,
                "generation_mwh": b["sum"] if b["numeric_rows"] else None,
                "numeric_source_rows": b["numeric_rows"],
                "null_source_rows": b["null_rows"],
                "source_member": member,
                "source_sheet": sheet_name,
            })
    meta = {
        "state": "PARSED",
        "selected_member": member,
        "selected_sheet": sheet_name,
        "header_row": hr,
        "target_source_rows": len(source_rows),
        "plant_ids": sorted(set(x["plant_id"] for x in source_rows)),
        "month_columns": month_cols,
        "candidate_sheets": [{"rows": c[0], "member": c[1], "sheet": c[2], "header_row": c[3]} for c in candidates],
    }
    return source_rows, canonical, meta

HYDRO_NAMES = ["caonillas", "dos bocas", "garzas", "patillas", "rio blanco", "río blanco", "toro negro", "yauco"]

def parse_luma_pdf(path: Path, label_date: str) -> tuple[list[dict], dict]:
    reader = PdfReader(str(path))
    pages = []
    hydro_lines = []
    date_hits = []
    for pageno, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(text)
        for m in re.finditer(r"(?<!\d)(?:0?8[/-](?:28|29|30)[/-]2026|2026[/-]0?8[/-](?:28|29|30))(?!\d)", text, flags=re.I):
            date_hits.append({"page": pageno, "text": m.group(0)})
        for lineno, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            if any(name in low for name in HYDRO_NAMES):
                hydro_lines.append({"file": path.name, "label_date": label_date, "page": pageno, "line_number": lineno, "text": line.strip()})
    (ROOT / f"{path.stem}.txt").write_text("\n\n--- PAGE BREAK ---\n\n".join(pages), encoding="utf-8")
    normalized_dates = []
    for hit in date_hits:
        s = hit["text"].replace("-", "/")
        parts = s.split("/")
        if len(parts) == 3 and len(parts[0]) == 4:
            y,m,d = parts
        else:
            m,d,y = parts
        normalized_dates.append(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
    first_page_dates = []
    for hit, nd in zip(date_hits, normalized_dates):
        if hit["page"] == 1:
            first_page_dates.append(nd)
    unique_first = sorted(set(first_page_dates))
    meta = {
        "state": "PARSED_TEXT",
        "label_date": label_date,
        "pages": len(reader.pages),
        "date_hits": date_hits,
        "normalized_first_page_dates": unique_first,
        "hydro_line_count": len(hydro_lines),
    }
    return hydro_lines, meta

def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})

manifest: list[dict] = []

for period, url in EIA860_URLS.items():
    manifest.append(freeze("eia_860m", period, url, ".xlsx"))

manifest.append(freeze("eia_923", "2026-08-release", EIA923_URL, ".zip"))

luma_found, luma_index_meta = discover_luma_urls()
for day in ("2026-08-28", "2026-08-30"):
    url = luma_found.get(day) or LUMA_GUESSED[day]
    rec = freeze("luma_bps_daily", day, url, ".pdf")
    rec["url_discovery"] = "INDEX" if day in luma_found else "GUESSED_PATTERN_AFTER_INDEX_FAILURE_OR_NO_MATCH"
    manifest.append(rec)

(ROOT / "source_manifest.json").write_text(json.dumps({"run_utc": RUN_UTC, "luma_index": luma_index_meta, "artifacts": manifest}, indent=2, sort_keys=True), encoding="utf-8")

eia860_source_rows: list[dict] = []
eia860_canonical: list[dict] = []
eia860_meta: list[dict] = []
for rec in manifest:
    if rec["source_id"] != "eia_860m" or rec["state"] != "RAW_FROZEN_NOT_PARSED":
        continue
    path = Path(rec["path"])
    try:
        sr, can, meta = parse_860(path, rec["label"])
        eia860_source_rows.extend(sr)
        eia860_canonical.extend(can)
        eia860_meta.append(meta)
        rec["parse_state"] = meta["state"]
    except Exception as e:
        rec["parse_state"] = "PARSE_FAILED"
        rec["parse_failure"] = f"{type(e).__name__}: {e}"

with (ROOT / "eia860m_source_rows.jsonl").open("w", encoding="utf-8") as f:
    for x in eia860_source_rows:
        f.write(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n")
write_csv(ROOT / "eia860m_canonical.csv", eia860_canonical,
          ["period","plant_id","plant_name","generator_id","status","nameplate_mw","net_summer_mw","net_winter_mw","prime_mover","energy_source_1","source_row_number"])

eia923_source_rows: list[dict] = []
eia923_canonical: list[dict] = []
eia923_meta: dict[str, Any] = {"state": "NOT_ACQUIRED"}
rec923 = next((r for r in manifest if r["source_id"] == "eia_923"), None)
if rec923 and rec923["state"] == "RAW_FROZEN_NOT_PARSED":
    try:
        eia923_source_rows, eia923_canonical, eia923_meta = parse_923_zip(Path(rec923["path"]))
        rec923["parse_state"] = eia923_meta["state"]
    except Exception as e:
        eia923_meta = {"state": "PARSE_FAILED", "failure": f"{type(e).__name__}: {e}"}
        rec923["parse_state"] = "PARSE_FAILED"

with (ROOT / "eia923_source_rows.jsonl").open("w", encoding="utf-8") as f:
    for x in eia923_source_rows:
        f.write(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n")
write_csv(ROOT / "eia923_plant_month_mwh.csv", eia923_canonical,
          ["period","plant_id","generation_mwh","numeric_source_rows","null_source_rows","source_member","source_sheet"])

luma_lines: list[dict] = []
luma_meta: list[dict] = []
for rec in manifest:
    if rec["source_id"] != "luma_bps_daily" or rec["state"] != "RAW_FROZEN_NOT_PARSED":
        continue
    try:
        lines, meta = parse_luma_pdf(Path(rec["path"]), rec["label"])
        luma_lines.extend(lines)
        luma_meta.append(meta)
        rec["parse_state"] = meta["state"]
    except Exception as e:
        rec["parse_state"] = "PARSE_FAILED"
        rec["parse_failure"] = f"{type(e).__name__}: {e}"
with (ROOT / "luma_hydro_lines.jsonl").open("w", encoding="utf-8") as f:
    for x in luma_lines:
        f.write(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n")

# Adjudicate claim that the 8/30 file contains 8/29 observations.
aug30 = next((m for m in luma_meta if m["label_date"] == "2026-08-30"), None)
if aug30:
    dates = set(aug30["normalized_first_page_dates"])
    if "2026-08-29" in dates and "2026-08-30" not in dates:
        aug29_claim = "SUPPORTED_BY_INTERNAL_FIRST_PAGE_DATE"
    elif "2026-08-30" in dates and "2026-08-29" not in dates:
        aug29_claim = "CONTRADICTED_BY_INTERNAL_FIRST_PAGE_DATE"
    elif "2026-08-29" in dates:
        aug29_claim = "AMBIGUOUS_MULTIPLE_DATES_INCLUDING_2026-08-29"
    else:
        aug29_claim = "UNRESOLVED_NO_EXPLICIT_2026-08-29_FIRST_PAGE_DATE"
else:
    aug29_claim = "BLOCKED_NO_AUG30_BYTES"

# Invariants.
invariants: list[dict] = []
def gate(name: str, passed: bool, evidence: Any, failure: Any = None):
    invariants.append({"gate": name, "state": "PASS" if passed else "FAIL_CLOSED", "evidence": evidence, "failure": failure})

frozen = [r for r in manifest if r["state"] == "RAW_FROZEN_NOT_PARSED"]
gate("PROVENANCE_HASH_EIA860M", sum(r["source_id"]=="eia_860m" for r in frozen) == 5,
     {"frozen": [r.get("label") for r in frozen if r["source_id"]=="eia_860m"]},
     "All five Mar-Jul workbooks must be frozen.")
gate("PROVENANCE_HASH_EIA923", any(r["source_id"]=="eia_923" for r in frozen),
     {"sha256": rec923.get("sha256") if rec923 else None},
     "EIA-923 ZIP bytes required.")
gate("PROVENANCE_HASH_LUMA", sum(r["source_id"]=="luma_bps_daily" for r in frozen) == 2,
     {"frozen": [r.get("label") for r in frozen if r["source_id"]=="luma_bps_daily"]},
     "Both Aug-28 and Aug-30 reports required.")

meta_by_period = {m["period"]: m for m in eia860_meta}
gate("COUNT_CLOSURE_860M", len(meta_by_period) == 5 and all(m["source_rows"] == m["canonical_rows"] and m["canonical_rows"] > 0 for m in meta_by_period.values()),
     meta_by_period, "Each frozen workbook must parse target source rows with one retained canonical row per source row.")
gate("ID_UNIQUENESS_860M", len(meta_by_period) == 5 and all(m["duplicate_generator_keys"] == 0 for m in meta_by_period.values()),
     {p: m.get("duplicate_generator_keys") for p,m in meta_by_period.items()}, "Duplicate plant+generator keys found or month missing.")
gate("MW_CLOSURE_860M", len(meta_by_period) == 5 and all(m["null_nameplate"] == 0 and m["null_summer"] == 0 and m["null_winter"] == 0 for m in meta_by_period.values()),
     {p: {"nameplate":m.get("nameplate_mw_sum"),"summer":m.get("net_summer_mw_sum"),"winter":m.get("net_winter_mw_sum"),"nulls":[m.get("null_nameplate"),m.get("null_summer"),m.get("null_winter")]} for p,m in meta_by_period.items()},
     "Missing capacity value or month.")

mwh_nulls = [r for r in eia923_canonical if r["generation_mwh"] is None]
mwh_plants = sorted(set(r["plant_id"] for r in eia923_canonical if r["generation_mwh"] is not None))
gate("MWH_CLOSURE_923_JAN_JUN", bool(eia923_canonical) and not mwh_nulls and set(mwh_plants) == PLANT_IDS,
     {"rows": len(eia923_canonical), "null_cells": len(mwh_nulls), "plant_ids": mwh_plants, "meta": eia923_meta},
     "All 7 canonical plant IDs x Jan-Jun require explicit numeric source values; no zero imputation.")

luma_acquired = {r["label"] for r in frozen if r["source_id"]=="luma_bps_daily"}
luma_meta_by_day = {m["label_date"]: m for m in luma_meta}
gate("STATUS_DATE_LUMA", luma_acquired == {"2026-08-28","2026-08-30"} and all(luma_meta_by_day.get(d,{}).get("normalized_first_page_dates") for d in luma_acquired),
     {"acquired": sorted(luma_acquired), "meta": luma_meta_by_day, "aug29_claim": aug29_claim},
     "Both PDFs must be frozen and expose explicit report/as-of date evidence.")
gate("LUMA_HYDRO_UNIT_EVIDENCE_PRESENT", len(luma_lines) > 0,
     {"hydro_lines": len(luma_lines)}, "No hydro unit lines were extracted; rendered-cell replay may still be required.")
gate("AUG29_INTERNAL_DATE_ADJUDICATION", aug29_claim.startswith("SUPPORTED_"),
     {"verdict": aug29_claim}, "Do not promote Aug-29 state unless internal source date explicitly supports it.")
gate("NO_NAME_ONLY_MATCH", True, "EIA joins restricted to stable Plant ID / Generator ID; LUMA lines are not bound to EIA generators by name.")
gate("NO_SILENT_NULL", not mwh_nulls and all(m["null_nameplate"]==0 and m["null_summer"]==0 and m["null_winter"]==0 for m in eia860_meta) if eia860_meta else False,
     {"eia923_nulls": len(mwh_nulls), "eia860_months_parsed": len(eia860_meta)}, "Null evidence remains or required source not parsed.")
gate("NO_MN_MULTIPLICATION", all(m["duplicate_generator_keys"]==0 for m in eia860_meta) if eia860_meta else False,
     {"860m_duplicate_keys": {m["period"]:m["duplicate_generator_keys"] for m in eia860_meta}}, "Cannot certify row conservation/uniqueness.")

overall = "PASS" if all(g["state"] == "PASS" for g in invariants) else "WITHHELD_FAIL_CLOSED"
invariant_report = {
    "run_utc": RUN_UTC,
    "operational_wave_state": overall,
    "aug29_internal_date_claim": aug29_claim,
    "eia860m_parse_meta": eia860_meta,
    "eia923_parse_meta": eia923_meta,
    "luma_parse_meta": luma_meta,
    "gates": invariants,
}
(ROOT / "invariants.json").write_text(json.dumps(invariant_report, indent=2, sort_keys=True), encoding="utf-8")

# Refresh manifest with parse states.
(ROOT / "source_manifest.json").write_text(json.dumps({"run_utc": RUN_UTC, "luma_index": luma_index_meta, "artifacts": manifest}, indent=2, sort_keys=True), encoding="utf-8")
(ROOT / "README.txt").write_text(
    "Puerto Rico hydro operational acquisition receipt\n"
    f"run_utc={RUN_UTC}\n"
    f"state={overall}\n"
    f"aug29_claim={aug29_claim}\n"
    "Source existence, raw-byte acquisition, parsing, identity binding and certification are separate states.\n"
    "No missing source or null value is converted to zero. No LUMA name-only row is bound to an EIA generator.\n",
    encoding="utf-8",
)
print(json.dumps(invariant_report, indent=2, sort_keys=True))
