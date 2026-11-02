#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, re, urllib.request, urllib.parse, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

RUN_UTC=datetime.now(timezone.utc).isoformat()
ROOT=Path(os.environ.get("G002_OUT","g002-facppac"))
RAW=ROOT/"raw"; DER=ROOT/"derived"; RAW.mkdir(parents=True,exist_ok=True); DER.mkdir(parents=True,exist_ok=True)
UA="AguaYLuz-HydroEvidence/1.1 (+https://github.com/jotaele44/aguayluz-pr)"
URLS={
 "dec25_jan_feb26":"https://energia.pr.gov/wp-content/uploads/sites/7/2026/03/FAC-PPAC-Reconciliation-Dec25-Jan-Feb26_Values.xlsx",
 "mar_apr_may26":"https://energia.pr.gov/wp-content/uploads/sites/7/2026/06/FAC-PPAC-Reconciliation-Mar-Apr-May-2026-06222026_Values.xlsx",
 "jun_jul_aug26":"https://energia.pr.gov/wp-content/uploads/sites/7/2026/09/FAC-PPAC-Reconciliation-Jun-Jul-Aug-2026-919-Genera-Review-Version_Values.xlsx",
}
PLANTS=["caonillas","dos bocas","garzas","patillas","rio blanco","río blanco","toro negro","yauco","hydro","hydroelectric"]
TARGET_NUMS=["1886.90","1886.9","1921.22","1374.84","6038"]
NS={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main","r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

def sha(b): return hashlib.sha256(b).hexdigest()
def norm(v): return re.sub(r"\s+"," ",str(v or "")).strip()
def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=120) as r:
        b=r.read(150*1024*1024+1)
        if not b or len(b)>150*1024*1024: raise ValueError("empty/oversized")
        return b,{"final_url":r.geturl(),"content_type":r.headers.get("Content-Type"),"etag":r.headers.get("ETag"),"last_modified":r.headers.get("Last-Modified")}
def rows(path):
    with zipfile.ZipFile(path) as z:
        ss=[]
        if "xl/sharedStrings.xml" in z.namelist():
            rr=ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in rr.findall("m:si",NS):
                ss.append("".join(t.text or "" for t in si.iterfind(".//m:t",NS)))
        wb=ET.fromstring(z.read("xl/workbook.xml"))
        rel=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap={x.attrib["Id"]:x.attrib["Target"] for x in rel}
        for s in wb.find("m:sheets",NS):
            name=s.attrib.get("name","")
            rid=s.attrib.get("{%s}id"%NS["r"]); target=relmap.get(rid)
            if not target: continue
            if not target.startswith("xl/"): target="xl/"+target.lstrip("/")
            if target not in z.namelist(): continue
            rr=ET.fromstring(z.read(target))
            for row in rr.iterfind(".//m:sheetData/m:row",NS):
                vals=[]
                for c in row.findall("m:c",NS):
                    t=c.attrib.get("t"); v=c.find("m:v",NS); isel=c.find("m:is",NS)
                    val=""
                    if t=="s" and v is not None:
                        try: val=ss[int(v.text)]
                        except: val=v.text or ""
                    elif t=="inlineStr" and isel is not None:
                        val="".join(x.text or "" for x in isel.iterfind(".//m:t",NS))
                    elif v is not None: val=v.text or ""
                    vals.append((c.attrib.get("r",""),norm(val)))
                if vals: yield name,int(row.attrib.get("r","0")),vals

manifest=[]; hits=[]
for label,url in URLS.items():
    rec={"label":label,"url":url,"retrieved_utc":RUN_UTC,"state":"FAILED"}
    try:
        b,meta=fetch(url); p=RAW/f"{label}.xlsx"; p.write_bytes(b)
        rec.update(meta); rec.update({"state":"RAW_FROZEN","sha256":sha(b),"byte_count":len(b),"path":str(p)})
        sheet_rows={}
        for s,r,cells in rows(p):
            txt=" | ".join(f"{a}={v}" for a,v in cells)
            low=txt.lower()
            sheet_rows.setdefault(s,{})[r]=txt
            terms=[x for x in PLANTS if x in low]
            nums=[x for x in TARGET_NUMS if x in low.replace(",","")]
            if terms or nums:
                hits.append({"source":label,"sheet":s,"row":r,"plant_terms":terms,"target_numbers":nums,"row_text":txt})
        # Adjacent context around all hydro hits.
        contexts=[]
        for h in [x for x in hits if x["source"]==label and x["plant_terms"]]:
            d=sheet_rows[h["sheet"]]
            contexts.append({"sheet":h["sheet"],"row":h["row"],"context":[{"row":q,"text":d[q]} for q in range(max(1,h["row"]-3),h["row"]+4) if q in d]})
        rec["hydro_context_count"]=len(contexts)
        (DER/f"{label}_hydro_context.json").write_text(json.dumps(contexts,indent=2,ensure_ascii=False))
    except Exception as e:
        rec["failure"]=f"{type(e).__name__}: {e}"
        rec["code"]=getattr(e,"code",None)
    manifest.append(rec)

# Strong result requires a row/context whose semantics actually indicate hydro generation energy, not merely costs.
strong=[]
for h in hits:
    low=h["row_text"].lower()
    if h["plant_terms"] and any(k in low for k in ["mwh","generation","generated","energy"]) and any(re.search(r"(?<!\d)1?8\d{2}(?:\.\d+)?(?!\d)", low) for _ in [0]):
        strong.append(h)

out={"run_utc":RUN_UTC,"manifest":manifest,"hits":hits,"strong_candidates":strong,
     "rules":["source discovery != acquisition","no zero imputation","hydro cost rows != generation MWh","raw strings preserved"]}
(DER/"g002_facppac_report.json").write_text(json.dumps(out,indent=2,ensure_ascii=False,sort_keys=True))
print(json.dumps({"frozen":sum(x["state"]=="RAW_FROZEN" for x in manifest),"hits":len(hits),"strong_candidates":len(strong)},indent=2))
