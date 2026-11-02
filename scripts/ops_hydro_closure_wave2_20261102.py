#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, html, json, os, re, sys, urllib.parse, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

RUN_UTC = datetime.now(timezone.utc).isoformat()
ROOT = Path(os.environ.get("HYDRO_CLOSURE_OUT", "hydro-closure-wave2"))
RAW = ROOT/"raw"; RAW.mkdir(parents=True, exist_ok=True)
OUT = ROOT/"derived"; OUT.mkdir(parents=True, exist_ok=True)
UA = "AguaYLuz-HydroClosure/1.0 (+https://github.com/jotaele44/aguayluz-pr)"
MAX_BYTES = 120*1024*1024
TARGET_NUMBERS = ["1886.90","1,886.90","1921.22","1,921.22","1374.84","1,374.84","6038","6,038"]
TARGET_TERMS = ["hydro","hydroelectric","mwh","generation","generacion","generación","actual","forecast",
                "caonillas","dos bocas","garzas","patillas","rio blanco","río blanco","toro negro","yauco"]
DOCKETS = [
    "https://energia.pr.gov/en/dockets/?docket=nepr-mi-2021-0004",
    "https://energia.pr.gov/expedientes/?docket=nepr-mi-2024-0001",
    "https://energia.pr.gov/en/dockets/?docket=nepr-mi-2024-0005",
]
SEED_URLS = [
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/05/20260515-MI20210004-Exhibit-I-Q3-FY2026-Schedules-Motion-to-Submit-Quarterly-Report-for-the-Third-Quarter-of-Fiscal-Year-2026.xlsx",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/05/20260515-MI20210004-Exhibit-II-FOMB_B2A_FY26-Motion-to-Submit-Quarterly-Report-for-the-Third-Quarter-of-Fiscal-Year-2026.pdf.xlsx",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/07/20260716-MI20210004-Anejo-Motion-to-Submit-the-May-2026-B2A-Report.xlsx",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/06/20260615-MI20210004-PREPA-B2A-April_vF.xlsx",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/07/20260630-MI20210004-Federal-Funding-Grid-Modernization-June-2026-Vf.xlsx",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/10/20260930-MI20210004-PREPA-Federal-Funding-Grid-Modernization-September-2026.xlsx",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/10/20261028-MI20210004-LUMA-FY2026-Schedules.xlsx",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/05/20260514-MI20240001-Motion-to-Submit-Third-Quarter-Progress-Report-for-Fiscal-Year-2026.pdf",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/10/20261015-MI20210004-PREPAs-Motion-to-Submit-the-August-2026-B2A-Report.pdf",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/09/20260915-MI20210004-Motion-to-Submit-the-June-2026-B2A-Report.pdf",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/08/20260818-MI20210004-Motion-to-Submit-the-June-2026-B2A-Report.pdf",
    "https://energia.pr.gov/wp-content/uploads/sites/7/2026/07/20260716-MI20210004-Motion-to-Submit-the-May-2026-B2A-Report.pdf",
]
LUMA_INDEX = "https://lumapr.com/monitoreo-de-bps/"

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.items=[]; self._href=None; self._txt=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="a":
            self._href=dict(attrs).get("href"); self._txt=[]
    def handle_data(self, data):
        if self._href is not None: self._txt.append(data)
    def handle_endtag(self, tag):
        if tag.lower()=="a" and self._href is not None:
            self.items.append((self._href," ".join(self._txt).strip()))
            self._href=None; self._txt=[]

def sha(b): return hashlib.sha256(b).hexdigest()
def norm(s): return re.sub(r"\s+"," ",html.unescape(str(s or "")).strip())
def fetch(url, max_bytes=MAX_BYTES):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=90) as r:
        data=r.read(max_bytes+1)
        if not data or len(data)>max_bytes: raise ValueError("empty/oversized")
        return data, {"final_url":r.geturl(),"content_type":r.headers.get("Content-Type"),
                      "last_modified":r.headers.get("Last-Modified"),"etag":r.headers.get("ETag"),
                      "retrieved_utc":RUN_UTC}
def freeze(url, label):
    rec={"url":url,"label":label,"state":"FAILED"}
    try:
        b,m=fetch(url); ext=Path(urllib.parse.urlparse(m["final_url"]).path).suffix or ".bin"
        name=f"{len(manifest):03d}_{re.sub(r'[^A-Za-z0-9_.-]+','_',label)[:80]}{ext}"
        p=RAW/name; p.write_bytes(b)
        rec.update(m); rec.update({"state":"RAW_FROZEN","sha256":sha(b),"byte_count":len(b),"path":str(p)})
    except Exception as e:
        rec.update({"failure_type":type(e).__name__,"failure":str(e)[:800],"code":getattr(e,"code",None)})
    manifest.append(rec); return rec

def discover_docket(url):
    out=[]
    try:
        b,m=fetch(url,20*1024*1024); txt=b.decode("utf-8","replace"); p=Links(); p.feed(txt)
        for href,label in p.items:
            u=urllib.parse.urljoin(url,href)
            low=(u+" "+label).lower()
            if "2026" not in low: continue
            if not any(x in low for x in [".xlsx",".xls",".pdf"]): continue
            if any(k in low for k in ["b2a","quarter","annual","hydro","generation","progress","schedule","collaborative","grid-modernization","federal-funding"]):
                out.append((u,norm(label)))
        return out
    except Exception as e:
        docket_failures.append({"url":url,"failure":f"{type(e).__name__}: {e}"})
        return []

# Native XLSX reader using OOXML only.
NS={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr":"http://schemas.openxmlformats.org/package/2006/relationships"}
def xlsx_rows(path):
    with zipfile.ZipFile(path) as z:
        shared=[]
        if "xl/sharedStrings.xml" in z.namelist():
            root=ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si",NS):
                shared.append("".join(t.text or "" for t in si.iterfind(".//m:t",NS)))
        wb=ET.fromstring(z.read("xl/workbook.xml"))
        rel=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap={x.attrib["Id"]:x.attrib["Target"] for x in rel}
        sheets=[]
        for s in wb.find("m:sheets",NS):
            rid=s.attrib.get("{%s}id"%NS["r"]); target=relmap.get(rid)
            if target:
                if not target.startswith("xl/"): target="xl/"+target.lstrip("/")
                sheets.append((s.attrib.get("name",""),target))
        for sname,target in sheets:
            if target not in z.namelist(): continue
            root=ET.fromstring(z.read(target))
            for row in root.iterfind(".//m:sheetData/m:row",NS):
                vals=[]
                for c in row.findall("m:c",NS):
                    t=c.attrib.get("t"); v=c.find("m:v",NS); isel=c.find("m:is",NS)
                    val=""
                    if t=="s" and v is not None:
                        try: val=shared[int(v.text)]
                        except: val=v.text or ""
                    elif t=="inlineStr" and isel is not None:
                        val="".join(x.text or "" for x in isel.iterfind(".//m:t",NS))
                    elif v is not None: val=v.text or ""
                    vals.append((c.attrib.get("r",""),norm(val)))
                if vals: yield sname,int(row.attrib.get("r","0")),vals

def scan_xlsx(rec):
    hits=[]; counts=defaultdict(int)
    try:
        for sname,rnum,cells in xlsx_rows(rec["path"]):
            rowtxt=" | ".join(f"{a}={v}" for a,v in cells)
            low=rowtxt.lower()
            matched=[t for t in TARGET_TERMS if t in low] + [n for n in TARGET_NUMBERS if n.replace(",","") in low.replace(",","")]
            if matched:
                hits.append({"sheet":sname,"row":rnum,"matches":sorted(set(matched)),"row_text":rowtxt[:5000]})
                for m in matched: counts[m]+=1
        return {"state":"SCANNED","hits":hits,"match_counts":dict(counts)}
    except Exception as e:
        return {"state":"SCAN_FAILED","failure":f"{type(e).__name__}: {e}"}

def scan_pdf(rec):
    # PDF text via pypdf; no OCR.
    try:
        from pypdf import PdfReader
        reader=PdfReader(rec["path"]); hits=[]
        for pi,p in enumerate(reader.pages,1):
            txt=p.extract_text() or ""; low=txt.lower()
            matched=[t for t in TARGET_TERMS if t in low] + [n for n in TARGET_NUMBERS if n.replace(",","") in low.replace(",","")]
            if matched:
                lines=[norm(x) for x in txt.splitlines() if any(t in x.lower() for t in TARGET_TERMS) or any(n.replace(",","") in x.replace(",","") for n in TARGET_NUMBERS)]
                hits.append({"page":pi,"matches":sorted(set(matched)),"lines":lines[:80]})
        return {"state":"SCANNED","pages":len(reader.pages),"hits":hits}
    except Exception as e:
        return {"state":"SCAN_FAILED","failure":f"{type(e).__name__}: {e}"}

def luma_discovery():
    result={"index_url":LUMA_INDEX,"state":"FAILED","links":[],"api_like":[],"date_829":[]}
    try:
        b,m=fetch(LUMA_INDEX,25*1024*1024); txt=b.decode("utf-8","replace"); p=Links(); p.feed(txt)
        result["state"]="SCANNED"; result["sha256"]=sha(b); result["byte_count"]=len(b); result["meta"]=m
        for href,label in p.items:
            u=urllib.parse.urljoin(LUMA_INDEX,href); blob=(u+" "+label)
            if any(x in u.lower() for x in [".csv",".xlsx",".xls",".json","api","download","export"]):
                result["api_like"].append({"url":u,"label":norm(label)})
            if any(d in blob.lower() for d in ["8/29/2026","20260829","2026-08-29","08-29-2026"]):
                result["date_829"].append({"url":u,"label":norm(label)})
            if "8/28/2026" in blob or "8/30/2026" in blob:
                result["links"].append({"url":u,"label":norm(label)})
        # Search raw HTML/JS references for machine-readable endpoints.
        refs=sorted(set(re.findall(r'https?://[^"\\'<>\\s]+|/[A-Za-z0-9_./?=&%-]+',txt)))
        for ref in refs:
            low=ref.lower()
            if any(x in low for x in [".csv",".xlsx",".xls",".json","api/","wp-json","export","download"]):
                u=urllib.parse.urljoin(LUMA_INDEX,ref)
                if {"url":u,"label":"RAW_HTML_REFERENCE"} not in result["api_like"]:
                    result["api_like"].append({"url":u,"label":"RAW_HTML_REFERENCE"})
        (OUT/"luma_index.html").write_bytes(b)
    except Exception as e:
        result["failure"]=f"{type(e).__name__}: {e}"
    return result

manifest=[]; docket_failures=[]
candidates={}
for u in SEED_URLS: candidates[u]="seed"
for d in DOCKETS:
    for u,label in discover_docket(d): candidates.setdefault(u,label or "docket")
# Bounded: keep unique candidates, prioritize xlsx and likely generation/reporting docs.
scored=[]
for u,label in candidates.items():
    low=(u+" "+label).lower(); score=0
    for k,w in [(".xlsx",5),("hydro",7),("generation",6),("quarter",4),("annual",4),("b2a",3),("schedule",3),("progress",2),("collaborative",2)]:
        if k in low: score+=w
    scored.append((score,u,label))
scored.sort(reverse=True)
# Cap to avoid uncontrolled corpus expansion.
selected=scored[:40]
for score,u,label in selected:
    rec=freeze(u,label or Path(urllib.parse.urlparse(u).path).name)
    if rec["state"]=="RAW_FROZEN":
        ext=Path(rec["path"]).suffix.lower()
        rec["scan"]=scan_xlsx(rec) if ext in [".xlsx",".xlsm"] else scan_pdf(rec) if ext==".pdf" else {"state":"UNSUPPORTED"}

luma=luma_discovery()
# Candidate endpoint probes are discovery-only and bounded to same host.
endpoint_probes=[]
for item in luma.get("api_like",[])[:50]:
    u=item["url"]
    if urllib.parse.urlparse(u).hostname not in {"lumapr.com","www.lumapr.com"}: continue
    try:
        b,m=fetch(u,10*1024*1024)
        endpoint_probes.append({"url":u,"state":"FETCHED","sha256":sha(b),"byte_count":len(b),"content_type":m.get("content_type"),"prefix":b[:500].decode("utf-8","replace")})
    except Exception as e:
        endpoint_probes.append({"url":u,"state":"FAILED","code":getattr(e,"code",None),"failure":str(e)[:500]})

# Consolidate exact numeric/hydro matches.
responsive=[]
for rec in manifest:
    scan=rec.get("scan",{})
    hits=scan.get("hits",[])
    num_hits=[]
    for h in hits:
        if any(n in h.get("matches",[]) for n in TARGET_NUMBERS) or ("hydro" in h.get("matches",[]) and ("mwh" in h.get("matches",[]) or "generation" in h.get("matches",[]))):
            num_hits.append(h)
    if num_hits:
        responsive.append({"label":rec["label"],"url":rec["url"],"sha256":rec.get("sha256"),"path":rec.get("path"),"hits":num_hits[:100]})

report={
    "run_utc":RUN_UTC,
    "selected_candidate_count":len(selected),
    "frozen_count":sum(r["state"]=="RAW_FROZEN" for r in manifest),
    "manifest":manifest,
    "responsive_candidates":responsive,
    "luma_discovery":luma,
    "luma_endpoint_probes":endpoint_probes,
    "docket_failures":docket_failures,
}
(OUT/"closure_search_report.json").write_text(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False))
with (OUT/"responsive_hits.json").open("w") as f: json.dump(responsive,f,indent=2,ensure_ascii=False)
with (OUT/"manifest.csv").open("w",newline="") as f:
    w=csv.writer(f); w.writerow(["label","url","state","sha256","byte_count","content_type","path"])
    for r in manifest: w.writerow([r.get("label"),r.get("url"),r.get("state"),r.get("sha256"),r.get("byte_count"),r.get("content_type"),r.get("path")])
print(json.dumps({"run_utc":RUN_UTC,"selected":len(selected),"frozen":report["frozen_count"],
                  "responsive":len(responsive),"luma_api_like":len(luma.get("api_like",[])),
                  "luma_829_links":len(luma.get("date_829",[]))},indent=2))
