#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, re, urllib.request, urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from pypdf import PdfReader

RUN_UTC=datetime.now(timezone.utc).isoformat()
ROOT=Path(os.environ.get("HYDRO_LUMA_MONTHLY_OUT","hydro-luma-monthly"))
RAW=ROOT/"raw"; RAW.mkdir(parents=True,exist_ok=True)
DER=ROOT/"derived"; DER.mkdir(parents=True,exist_ok=True)
UA="AguaYLuz-HydroMonthly/1.0 (+https://github.com/jotaele44/aguayluz-pr)"
INDEX="https://lumapr.com/monitoreo-de-bps/"
MONTHS=["January","February","March","April","May","June"]
TARGET_TERMS=["hydro","hydroelectric","prepa","caonillas","dos bocas","garzas","patillas","rio blanco","río blanco","toro negro","yauco"]
MWH_RE=re.compile(r'(?i)\b(?:mwh|gwh)\b')
GEN_RE=re.compile(r'(?i)\b(?:generation|production|generaci[oó]n|producci[oó]n)\b')

class P(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]; self.href=None; self.txt=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="a":
            self.href=dict(attrs).get("href"); self.txt=[]
    def handle_data(self,data):
        if self.href is not None: self.txt.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=="a" and self.href is not None:
            self.links.append((self.href," ".join(self.txt).strip()))
            self.href=None; self.txt=[]

def fetch(url,max_bytes=80*1024*1024):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=120) as r:
        b=r.read(max_bytes+1)
        if not b or len(b)>max_bytes: raise ValueError("empty/oversized")
        return b,{"final_url":r.geturl(),"content_type":r.headers.get("Content-Type"),"last_modified":r.headers.get("Last-Modified"),"etag":r.headers.get("ETag"),"retrieved_utc":RUN_UTC}

def sha(b): return hashlib.sha256(b).hexdigest()

idx,idxmeta=fetch(INDEX,25*1024*1024)
(DER/"bps-index.html").write_bytes(idx)
parser=P(); parser.feed(idx.decode("utf-8","replace"))

monthly={}
for href,label in parser.links:
    blob=(href+" "+label)
    low=blob.lower()
    if "2026" not in low or "monthly generation performance report" not in low:
        continue
    for m in MONTHS:
        if m.lower() in low:
            monthly[m]=urllib.parse.urljoin(INDEX,href)

manifest=[]; page_hits=[]; hydro_hits=[]; context_hits=[]
for m in MONTHS:
    rec={"month":m,"state":"NOT_DISCOVERED","url":monthly.get(m)}
    if not rec["url"]:
        manifest.append(rec); continue
    try:
        b,meta=fetch(rec["url"])
        rec.update(meta); rec["state"]="RAW_FROZEN"; rec["sha256"]=sha(b); rec["bytes"]=len(b)
        p=RAW/f"{m.lower()}_2026.pdf"; p.write_bytes(b); rec["path"]=str(p)
        reader=PdfReader(str(p)); rec["pages"]=len(reader.pages)
        for pi,page in enumerate(reader.pages,1):
            txt=page.extract_text() or ""
            low=txt.lower()
            terms=[t for t in TARGET_TERMS if t in low]
            if terms:
                item={"month":m,"page":pi,"terms":sorted(set(terms)),"text":txt[:20000]}
                hydro_hits.append(item)
            if MWH_RE.search(txt) or GEN_RE.search(txt):
                lines=[]
                for ln in txt.splitlines():
                    ll=ln.lower()
                    if MWH_RE.search(ln) or GEN_RE.search(ln) or any(t in ll for t in TARGET_TERMS):
                        lines.append(ln.strip())
                if lines:
                    context_hits.append({"month":m,"page":pi,"lines":lines[:200]})
        rec["parse_state"]="PARSED"
    except Exception as e:
        rec["state"]="FAILED"; rec["failure"]=f"{type(e).__name__}: {e}"
    manifest.append(rec)

# classify responsiveness
per_month=[]
for m in MONTHS:
    hh=[x for x in hydro_hits if x["month"]==m]
    has_hydro=bool(hh)
    mwh_context=[]
    for x in hh:
        txt=x["text"]
        if MWH_RE.search(txt) or GEN_RE.search(txt):
            mwh_context.append({"page":x["page"],"terms":x["terms"]})
    per_month.append({
        "month":m,
        "frozen":any(r["month"]==m and r["state"]=="RAW_FROZEN" for r in manifest),
        "hydro_term_pages":sorted({x["page"] for x in hh}),
        "hydro_generation_context_pages":mwh_context,
    })

report={
    "run_utc":RUN_UTC,
    "index":{"url":INDEX,"sha256":sha(idx),"bytes":len(idx),"meta":idxmeta},
    "discovered_months":monthly,
    "manifest":manifest,
    "per_month":per_month,
    "hydro_hits":hydro_hits,
    "context_hits":context_hits,
    "gates":{
        "JAN_JUN_DISCOVERY":"PASS" if len(monthly)==6 else "FAIL_CLOSED",
        "JAN_JUN_RAW_FREEZE":"PASS" if sum(r["state"]=="RAW_FROZEN" for r in manifest)==6 else "FAIL_CLOSED",
        "HYDRO_GENERATION_CONTEXT":"PASS" if any(x["hydro_generation_context_pages"] for x in per_month) else "FAIL_CLOSED"
    }
}
(DER/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False))
with (DER/"hydro_hits.jsonl").open("w",encoding="utf-8") as f:
    for x in hydro_hits: f.write(json.dumps(x,ensure_ascii=False)+"\n")
with (DER/"context_hits.jsonl").open("w",encoding="utf-8") as f:
    for x in context_hits: f.write(json.dumps(x,ensure_ascii=False)+"\n")

print(json.dumps({
    "months_discovered":len(monthly),
    "frozen":sum(r["state"]=="RAW_FROZEN" for r in manifest),
    "hydro_hit_pages":len(hydro_hits),
    "gates":report["gates"]
},indent=2))
