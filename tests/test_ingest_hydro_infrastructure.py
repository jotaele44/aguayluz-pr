"""scripts/ingest_hydro_infrastructure.py offline, on rows copied from the real PRASA, NID, ECHO,
SDWIS and FEMA responses (``tests/fixtures/hydro_inventory/infra``)."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from aguayluz import hydro_inventory as hi

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "hydro_inventory" / "infra"

_SPEC = importlib.util.spec_from_file_location("ingest_hydro_infrastructure", REPO / "scripts" / "ingest_hydro_infrastructure.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def config_dir(tmp_path: Path, **minimums: int) -> Path:
    """The real config with row minimums lowered to fit the fixtures (the guards themselves are tested below)."""
    out = tmp_path / "config"
    out.mkdir(exist_ok=True)
    cfg = json.loads((REPO / "config" / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    for s in cfg["live_sources"]:
        for key in ("min_rows", "min_potw"):
            if key in s:
                s[key] = minimums.get(s["source_key"], 1)
    (out / hi.SOURCES_CONFIG).write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return out


def run(tmp_path: Path, src: Path = FIXTURES, **minimums: int) -> tuple[int, Path]:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    code = ingest.main(["--src-dir", str(src), "--data-dir", str(data), "--config-dir", str(config_dir(tmp_path, **minimums)),
                        "--now", "2026-11-15T14:00:00Z"])
    return code, data / hi.HYDRO_DIR


def claims(hydro: Path, name: str) -> list[dict]:
    return hi.read_claims(hydro / name)


def test_prasa_facilities_are_typed_by_the_configured_map_and_offices_are_excluded(tmp_path):
    code, hydro = run(tmp_path)
    assert code == 0
    rows = claims(hydro, "claims_prasa_facilities.jsonl")
    kinds = {c["attributes"]["tipo"]: c["feature_type"] for c in rows}
    assert kinds["Pozo"] == "well" and kinds["Toma"] == "intake" and kinds["Embalse"] == "reservoir"
    assert kinds["Planta Filtración"] == "treatment_plant" and kinds["Planta Tratamiento Sanitario"] == "wastewater_plant"
    assert kinds["Estación Bomas Potable"] == kinds["Estación Bomas Sanitaria"] == "pump_station"
    assert "Oficina" not in kinds and all(c["lat"] is not None for c in rows)
    ledger = json.loads((hydro / "ingest_infrastructure_receipt.json").read_text())["ledgers"]["prasa_facilities"]
    assert ledger["excluded_by_reason"] == {"administrative office, not a water facility": 2}
    assert ledger["source"] == ledger["retained"] + ledger["excluded"]


def test_an_unknown_prasa_type_fails_closed(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    page = json.loads((src / "prasa" / "page_000.json").read_text())
    page["features"][0]["attributes"]["Tipo"] = "Algo Nuevo"
    (src / "prasa" / "page_000.json").write_text(json.dumps(page))
    code, hydro = run(tmp_path, src)
    assert code == 1
    receipt = json.loads((hydro / "ingest_infrastructure_receipt.json").read_text())
    assert receipt["last_status"] == "FAIL" and "Algo Nuevo" in receipt["last_error"]


def test_nid_reads_past_its_preamble_keeps_only_puerto_rico_and_repairs_double_encoded_spaces(tmp_path):
    code, hydro = run(tmp_path)
    assert code == 0
    dams = claims(hydro, "claims_nid_dams.jsonl")
    assert {c["feature_type"] for c in dams} == {"dam"} and len(dams) == 4
    by_id = {c["source_feature_id"]: c for c in dams}
    assert by_id["PR00003"]["attributes"]["name_clean"] == "Lucchetti Dam"
    ana = [c for c in dams if c["name_raw"].startswith("Ana Maria")]
    assert ana and all("\xa0" in c["name_raw"] for c in ana)  # the claim keeps the source's bytes
    assert {c["attributes"]["name_clean"] for c in ana} == {"Ana Maria V Dam", "Ana Maria Ii Dam"}
    assert all(c["attributes"]["nid_data_updated"] for c in dams)


def test_echo_keeps_publicly_owned_treatment_works_and_counts_every_other_permittee(tmp_path):
    code, hydro = run(tmp_path)
    assert code == 0
    potw = claims(hydro, "claims_echo_potw.jsonl")
    assert len(potw) == 3 and all(c["feature_type"] == "wastewater_plant" and c["lat"] is not None for c in potw)
    ledger = json.loads((hydro / "ingest_infrastructure_receipt.json").read_text())["ledgers"]["epa_echo_potw"]
    assert ledger["source"] == 5 and ledger["excluded"] == 2


def test_echo_pages_that_do_not_add_up_to_the_query_fail_closed(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    top = json.loads((src / "echo" / "facilities.json").read_text())
    top["Results"]["QueryRows"] = "6"
    (src / "echo" / "facilities.json").write_text(json.dumps(top))
    assert run(tmp_path, src)[0] == 1


def test_sdwis_facilities_are_listed_and_never_placed(tmp_path):
    code, hydro = run(tmp_path)
    assert code == 0
    rows = claims(hydro, "claims_sdwis_facilities.jsonl")
    assert {c["feature_type"] for c in rows} == {"treatment_plant", "spring", "tank"}
    assert all(c["lat"] is None and c["attributes"]["location"] == "not published by SDWIS" for c in rows)


def test_fema_sites_are_keyed_by_pwsid_and_unkeyed_rows_are_excluded_by_reason(tmp_path):
    code, hydro = run(tmp_path)
    assert code == 0
    rows = claims(hydro, "claims_fema_nonprasa.jsonl")
    assert len(rows) == 3 and all(c["attributes"]["pwsid"].startswith("PR") for c in rows)
    ledger = json.loads((hydro / "ingest_infrastructure_receipt.json").read_text())["ledgers"]["fema_nonprasa_sites"]
    assert ledger["excluded_by_reason"] == {"no site id or PWSID in the source row": 1}


def test_row_minimums_stop_a_truncated_download(tmp_path):
    code, hydro = run(tmp_path, prasa_facilities=4000)
    assert code == 1
    assert "fewer than 4000" in json.loads((hydro / "ingest_infrastructure_receipt.json").read_text())["last_error"]


def test_the_receipt_names_the_sources_that_could_not_be_used():
    receipt = json.loads((REPO / "data" / hi.HYDRO_DIR / "ingest_infrastructure_receipt.json").read_text())
    states = {r["state"] for r in receipt["residue_sources"]}
    assert states == {"UNREACHABLE_FROM_ENVIRONMENT", "EXCLUDED_BY_SOURCE_STATEMENT", "NOT_OFFICIAL"}
    pseudo = [r for r in receipt["residue_sources"] if "Pseudo" in r["source"]]
    assert pseudo and "DO NOT represent actual" in pseudo[0]["detail"]
