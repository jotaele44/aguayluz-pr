import importlib.util
import csv
from pathlib import Path

_SCRIPT=Path(__file__).resolve().parent.parent/"scripts"/"adjudicate_ucmr5_pr_subset.py"
_SPEC=importlib.util.spec_from_file_location("adjudicate_ucmr5_pr_subset",_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
adjudicate=_MODULE.adjudicate


def _write(path:Path, rows:list[dict[str,str]], order=None):
    fields=["PWSID","Contaminant","Result"]
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader()
        for i in (order if order is not None else range(len(rows))):
            w.writerow(rows[i])


def test_byte_identical(tmp_path:Path):
    a=tmp_path/"a.tsv"; b=tmp_path/"b.tsv"
    rows=[{"PWSID":"PR1","Contaminant":"A","Result":"1"}]
    _write(a,rows); b.write_bytes(a.read_bytes())
    r=adjudicate(a,b)
    assert r["classification"]=="BYTE_IDENTICAL"
    assert r["row_multiset"]["symmetric_difference"]==0


def test_logically_identical_order_change(tmp_path:Path):
    a=tmp_path/"a.tsv"; b=tmp_path/"b.tsv"
    rows=[{"PWSID":"PR1","Contaminant":"A","Result":"1"},{"PWSID":"PR2","Contaminant":"B","Result":"2"}]
    _write(a,rows); _write(b,rows,[1,0])
    r=adjudicate(a,b)
    assert r["classification"]=="LOGICALLY_IDENTICAL_ROW_MULTISET"
    assert r["pwsid_set"]["symmetric_difference"]==0


def test_distinct_subset_preserves_set_deltas(tmp_path:Path):
    a=tmp_path/"a.tsv"; b=tmp_path/"b.tsv"
    _write(a,[{"PWSID":"PR1","Contaminant":"A","Result":"1"}])
    _write(b,[{"PWSID":"PR2","Contaminant":"A","Result":"1"}])
    r=adjudicate(a,b)
    assert r["classification"]=="DISTINCT_PR_SUBSET"
    assert r["row_multiset"]=={"intersection":0,"old_only":1,"new_only":1,"union":2,"symmetric_difference":2}
    assert r["pwsid_set"]["old_only"]==["PR1"]
    assert r["pwsid_set"]["new_only"]==["PR2"]
