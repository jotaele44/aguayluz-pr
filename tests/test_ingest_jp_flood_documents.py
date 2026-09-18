from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
MODULE_PATH=ROOT/"scripts"/"ingest_jp_flood_documents.py"
spec=importlib.util.spec_from_file_location("jp_flood_consumer",MODULE_PATH)
mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod)

def _manifest():
    docs=[]
    for i in range(76):
        docs.append({"municipality":f"M{i:02d}","document_class":"flood_risk_zone_map","source_series":"JP_SECTORES_EN_ZONA_INUNDABLES","equivalent_series_member":True,"source_url":f"https://example.test/{i}.pdf","source_state":"AVAILABLE"})
    docs.append({"municipality":"Quebradillas","document_class":"flood_risk_zone_map","source_series":"JP_SECTORES_EN_ZONA_INUNDABLES","equivalent_series_member":True,"source_url":"https://example.test/quebradillas-broken.pdf","source_state":"LISTED_BUT_MISSING","fallback_document_class":"hazard_mitigation_plan","fallback_url":"https://example.test/quebradillas-hmp.pdf","fallback_relationship":"authoritative_fallback_not_equivalent"})
    docs.append({"municipality":"Florida","document_class":None,"source_series":"JP_SECTORES_EN_ZONA_INUNDABLES","equivalent_series_member":False,"source_url":None,"source_state":"NOT_LISTED","fallback_document_class":"hazard_mitigation_plan","fallback_url":"https://example.test/florida-hmp.pdf","fallback_relationship":"authoritative_fallback_not_equivalent"})
    return {"manifest_version":"1.1","authority":"Junta de Planificación de Puerto Rico","portal_url":"https://example.test/","documents":docs}

def test_consumer_preserves_source_states_and_fallbacks():
    out=mod.build_lookup(_manifest())
    assert out["counts"]=={"municipalities":78,"available_flood_maps":76,"listed_but_missing":1,"not_listed":1,"authoritative_fallbacks":2,"operational_coverage":78}
    assert out["by_municipality"]["Quebradillas"]["source_state"]=="LISTED_BUT_MISSING"
    assert out["by_municipality"]["Quebradillas"]["operational_document_class"]=="hazard_mitigation_plan"
    assert out["by_municipality"]["Florida"]["source_state"]=="NOT_LISTED"

def test_quebradillas_promotion_fails_closed():
    m=_manifest(); q=m["documents"][-2]; q["source_state"]="AVAILABLE"
    with pytest.raises(ValueError): mod.build_lookup(m)

def test_duplicate_municipality_fails_closed():
    m=_manifest(); m["documents"][1]["municipality"]=m["documents"][0]["municipality"]
    with pytest.raises(ValueError): mod.build_lookup(m)
