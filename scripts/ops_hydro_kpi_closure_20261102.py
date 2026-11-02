#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, json, os, re, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from openpyxl import load_workbook

RUN_UTC = datetime.now(timezone.utc).isoformat()
ROOT = Path(os.environ.get("HYDRO_KPI_OUT", "hydro-kpi-closure"))
RAW = ROOT / "raw"; RAW.mkdir(parents=True, exist_ok=True)
DER = ROOT / "derived"; DER.mkdir(parents=True, exist_ok=True)
UA = "AguaYLuz-HydroKPIClosure/1.0 (+https://github.com/jotaele44/aguayluz-pr)"

SOURCES = [
    ("jan20_performance_metrics","https://energia.pr.gov/wp-content/uploads/sites/7/2026/03/20260120-MI20190007-EXHIBIT-1-Performance-Metrics.xlsx"),
    ("mar20_kpis_fy25_26","https://energia.pr.gov/wp-content/uploads/sites/7/2026/03/Attachment-B.4-KPIs_FY-25-26-RFI-PREB_03032026.xlsx"),
    ("apr02_genera_metricas","https://energia.pr.gov/wp-content/uploads/sites/7/2026/04/20260402-MI20190007-Genera-Resumen-Metricas-Master_March2026-.xlsx"),
    ("apr20_exhibit1","https://energia.pr.gov/wp-content/uploads/sites/7/2026/04/Exhibit-1.xlsx"),
    ("jul20_exhibit1","https://energia.pr.gov/wp-content/uploads/sites/7/2026/07/20260720-MI20190007-Exhibit-1-Motion-to-Submit-Quarterly-Report-and-to-Comply-with-Resolution-and-Orders-Issued-on-March-16-2026-and-April-2-2026.xlsx"),
    ("sep29_q4_resumen","https://energia.pr.gov/wp-content/uploads/sites/7/2026/09/20260929-MI20190007-Exhibit-1_Q4-FY2026-Quaterly-Report-Resumen-Metricas.xlsx"),
    ("oct07_q4_resumen_corrected","https://energia.pr.gov/wp-content/uploads/sites/7/2026/10/20261007-MI2019007-Exhibit-1-Q4-FY2026-Quarterly-Report-Resumen-Metricas.xlsx"),
]
TERMS = [
    "hydro","hydroelectric","hydroco","plant availability","forced outage","forced outages",
    "cost of generation","mwh","generation","caonillas","dos bocas","garzas","patillas",
    "rio blanco","río blanco","toro negro","yauco"
]
TARGET_VALUES = ["1886.90","1921.22","1374.84","6038","1886.9"]

def sha256_file(p: Path):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def fetch(url: str, dest: Path):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=120) as r:
        data=r.read()
        dest.write_bytes(data)
        return {
            "url":url,"final_url":r.geturl(),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "content_type":r.headers.get("Content-Type"),"last_modified":r.headers.get("Last-Modified"),
            "etag":r.headers.get("ETag"),"retrieved_utc":RUN_UTC
        }

def clean(v):
    if v is None: return ""
    return re.sub(r"\s+"," ",str(v)).strip()

def row_matches(values):
    txt=" | ".join(clean(v) for v in values)
    low=txt.lower()
    hits=[t for t in TERMS if t in low]
    nums=[n for n in TARGET_VALUES if n in txt.replace(",","")]
    return txt,hits,nums

manifest=[]
hits=[]
sheet_inventory=[]
for label,url in SOURCES:
    path=RAW/f"{label}.xlsx"
    rec={"label":label,"url":url,"state":"FAILED"}
    try:
        rec.update(fetch(url,path)); rec["state"]="RAW_FROZEN"
        wb=load_workbook(path,read_only=False,data_only=False)
        rec["sheet_count"]=len(wb.sheetnames)
        for ws in wb.worksheets:
            maxr,maxc=ws.max_row,ws.max_column
            sheet_inventory.append({"source":label,"sheet":ws.title,"max_row":maxr,"max_col":maxc})
            for r in range(1,maxr+1):
                vals=[ws.cell(r,c).value for c in range(1,maxc+1)]
                txt,th,nh=row_matches(vals)
                if th or nh:
                    hits.append({
                        "source":label,"sheet":ws.title,"row":r,
                        "term_hits":th,"numeric_hits":nh,"row_text":txt[:12000]
                    })
        rec["parse_state"]="PARSED"
    except Exception as e:
        rec["failure"]=f"{type(e).__name__}: {e}"
        rec["parse_state"]="FAILED"
    manifest.append(rec)

# Targeted semantic extraction: candidate rows mentioning hydro + availability/outage/generation.
semantic=[]
for h in hits:
    low=h["row_text"].lower()
    cls=[]
    if "hydro" in low: cls.append("HYDRO")
    if "plant availability" in low or "availability" in low: cls.append("AVAILABILITY")
    if "forced outage" in low: cls.append("FORCED_OUTAGE")
    if "mwh" in low or "generation" in low: cls.append("GENERATION")
    if any(x in low for x in ["caonillas","dos bocas","garzas","patillas","rio blanco","río blanco","toro negro","yauco"]): cls.append("PLANT_NAME")
    if cls:
        semantic.append({**h,"classes":cls})

# Invariants / adjudication.
hydro_rows=[x for x in semantic if "HYDRO" in x["classes"] or "PLANT_NAME" in x["classes"]]
availability_rows=[x for x in semantic if "AVAILABILITY" in x["classes"]]
forced_rows=[x for x in semantic if "FORCED_OUTAGE" in x["classes"]]
generation_rows=[x for x in semantic if "GENERATION" in x["classes"]]
target_value_rows=[x for x in hits if x["numeric_hits"]]

summary={
    "run_utc":RUN_UTC,
    "source_count":len(SOURCES),
    "frozen_count":sum(r["state"]=="RAW_FROZEN" for r in manifest),
    "manifest":manifest,
    "sheet_inventory":sheet_inventory,
    "counts":{
        "all_hits":len(hits),
        "semantic_hits":len(semantic),
        "hydro_or_plant_rows":len(hydro_rows),
        "availability_rows":len(availability_rows),
        "forced_outage_rows":len(forced_rows),
        "generation_rows":len(generation_rows),
        "target_value_rows":len(target_value_rows),
    },
    "gates":{
        "RAW_FREEZE_ALL":"PASS" if all(r["state"]=="RAW_FROZEN" for r in manifest) else "FAIL_CLOSED",
        "TARGET_VALUE_RECOVERY":"PASS" if target_value_rows else "FAIL_CLOSED",
        "HYDRO_ROW_RECOVERY":"PASS" if hydro_rows else "FAIL_CLOSED",
    }
}
(DER/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True))
(DER/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
with (DER/"hits.jsonl").open("w",encoding="utf-8") as f:
    for x in hits: f.write(json.dumps(x,ensure_ascii=False)+"\n")
with (DER/"semantic_hits.jsonl").open("w",encoding="utf-8") as f:
    for x in semantic: f.write(json.dumps(x,ensure_ascii=False)+"\n")
with (DER/"sheet_inventory.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["source","sheet","max_row","max_col"]); w.writeheader(); w.writerows(sheet_inventory)

# Compact human-readable adjudication.
lines=[]
for x in semantic[:500]:
    lines.append(f'{x["source"]}\t{x["sheet"]}\t{x["row"]}\t{";".join(x["classes"])}\t{x["row_text"]}')
(DER/"semantic_hits.tsv").write_text("\n".join(lines),encoding="utf-8")

print(json.dumps({
    "run_utc":RUN_UTC,
    "frozen_count":summary["frozen_count"],
    "source_count":len(SOURCES),
    "counts":summary["counts"],
    "gates":summary["gates"]
},indent=2))
