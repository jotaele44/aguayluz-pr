"""Enforcement context for the solid-waste registry: EPA ECHO cases and facility reports.

Fixtures under tests/fixtures/solid_waste_* are real rows from the EPA ECHO services, selected
and not edited. The committed-data tests pin what the frozen 2026-11-13 pull produced.

Rules under test (ADR-0004): case-to-site links are candidates, never identity; a name match is
never promoted to an id match; a leak of the case service's silent filter-ignoring fails closed;
no entity, geometry or event is created from an enforcement case.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aguayluz import environmental_exposure_db as db
from aguayluz import solid_waste as sw

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
FIX = REPO / "tests" / "fixtures"
GEO = DATA / "geo" / "pr_municipios.json"

CASES = {
    c["CaseNumber"]: c
    for c in json.loads((FIX / "solid_waste_enforcement_cases_sample.json").read_text(encoding="utf-8"))["cases"]
}
TOA_ALTA_ECHO_ID = "110040514397"
TOA_ALTA_DFR = json.loads((FIX / "solid_waste_dfr_toa_alta_trimmed.json").read_text(encoding="utf-8"))["report"]

ENTITIES = db.load("environmental_entity", DATA / "environmental_entities.jsonl")
LMOP = [e for e in ENTITIES if e["authority"] == sw.LMOP_AUTHORITY]
ECHO = [e for e in ENTITIES if e["authority"] == sw.ECHO_AUTHORITY]
RECEIPTS = json.loads((DATA / "solid_waste_receipts.json").read_text(encoding="utf-8"))
RAW = [json.loads(line) for line in (DATA / "solid_waste_source_rows.jsonl").read_text().splitlines()]


def lmop_candidate(municipality: str) -> sw.Candidate:
    e = next(x for x in LMOP if x["municipality"] == municipality)
    return sw.Candidate(e["entity_id"], sw.LMOP_AUTHORITY, e["name_raw"], e["municipality"], None, None)


def case_number(binding: dict) -> str:
    return binding["right_id"].rsplit(":", 1)[1]


def context_cases() -> list[dict]:
    return sw.build_case_rows(list(CASES.values()))[0]


# ---------------------------------------------------------------------------
# The state filter must be proven to work
# ---------------------------------------------------------------------------


def test_case_control_returns_the_evidence_for_the_real_numbers():
    assert sw.case_service_control(3788, 0, 313712) == {
        "filtered_rows": 3788, "nonsense_state_rows": 0, "unfiltered_total": 313712, "effective": True,
    }


@pytest.mark.parametrize(
    "args",
    [
        (0, 0, 313712),  # an empty denominator
        (3788, 5, 313712),  # a nonsense state still returned rows: the filter is not a filter
        (313712, 0, 313712),  # filtered equals unfiltered: ignored
        (400000, 0, 313712),
    ],
)
def test_case_control_fails_closed_when_the_state_filter_did_nothing(args):
    with pytest.raises(sw.FilterIgnoredError):
        sw.case_service_control(*args)


# ---------------------------------------------------------------------------
# Which cases are landfill context, and how a name matches a municipality
# ---------------------------------------------------------------------------


def test_landfill_context_rule_on_real_rows():
    ctx = {n: sw.is_landfill_context_case(c) for n, c in CASES.items()}
    assert ctx["02-2016-7303"] is True  # the name says Landfill; the row has no NAICS code
    assert ctx["02-2018-0013"] is True  # "Municipality of Toa Alta": only NAICS 562212 says landfill
    assert ctx["PR000A200142975"] is True  # no name at all, NAICS 562212
    assert ctx["02-2000-3104"] is False  # a sanitary sewer system
    assert ctx["02-2010-1011"] is False  # NAICS 562213 is a combustor, not a landfill


@pytest.mark.parametrize(
    "haystack, needle, expected",
    [
        ("Municipality of Toa Alta et al. - Toa Alta Municipal Landfill", "Toa Baja", False),
        ("Toa Baja Municipal Solid Waste Landfill", "Toa Baja", True),
        ("Municipality of Vega Alta", "Vega Baja", False),
        ("Penuelas Valley Landfill", "Peñuelas", True),  # accent-blind
        ("BARCELONETTA LANDFILL", "Barceloneta", False),  # a different spelling is not a match
        ("Municipality of Juncosa", "Juncos", False),  # a longer word is not the municipality
        ("Municipality of Arroyo", "", False),  # an empty needle matches nothing
        ("Municipality of Arroyo", None, False),
    ],
)
def test_phrase_match_is_whole_word_and_accent_blind(haystack, needle, expected):
    assert sw._has_phrase(haystack, needle) is expected


def test_case_rows_keep_only_landfill_context_as_raw_only():
    context, rows = sw.build_case_rows(list(CASES.values()))
    assert {c["CaseNumber"] for c in context} == set(CASES) - {"02-2000-3104", "02-2010-1011"}
    assert [r["source_record_id"] for r in rows] == [sw.case_ref(c) for c in context]
    assert {r["source"] for r in rows} == {sw.CASES_SOURCE} and {r["disposition"] for r in rows} == {"RAW_ONLY"}
    assert all(r["row_sha256"] == sw.canonical_sha256(r["raw"]) for r in rows)


def test_case_rows_reject_duplicate_or_missing_case_numbers():
    arroyo = CASES["02-2016-7303"]
    with pytest.raises(ValueError):
        sw.build_case_rows([arroyo, arroyo])
    with pytest.raises(ValueError):
        sw.build_case_rows([{**arroyo, "CaseNumber": ""}])


# ---------------------------------------------------------------------------
# Bindings: candidates only, and a name is never promoted to an id
# ---------------------------------------------------------------------------


def test_arroyo_case_binds_to_the_arroyo_site_only_by_name_as_a_candidate():
    arroyo = lmop_candidate("Arroyo")
    (binding,) = sw.case_bindings([arroyo], context_cases(), [])
    assert case_number(binding) == "02-2016-7303"
    assert binding["left_id"] == arroyo.ref_id and binding["evidence_classes"] == ["NAME_ONLY"]
    assert binding["binding_type"] == sw.CASE_BINDING_TYPE
    assert binding["adjudication_state"] == "CANDIDATE_NOT_IDENTITY"


def test_toa_alta_and_toa_baja_cases_never_cross_bind():
    alta, baja = lmop_candidate("Toa Alta"), lmop_candidate("Toa Baja")
    by_site: dict[str, set[str]] = {}
    for b in sw.case_bindings([alta, baja], context_cases(), []):
        by_site.setdefault(b["left_id"], set()).add(case_number(b))
    assert by_site[alta.ref_id] == {"02-2017-7303", "02-2018-0013"}
    assert by_site[baja.ref_id] == {"02-2008-7301", "PR000A0000721370006800013"}


def test_an_id_in_an_echo_report_is_its_own_evidence_and_name_bindings_are_not_promoted():
    summary = sw.summarize_dfr(TOA_ALTA_ECHO_ID, TOA_ALTA_DFR)
    bindings = sw.case_bindings([lmop_candidate("Toa Alta")], context_cases(), [summary])
    by_id = [b for b in bindings if sw.ID_EVIDENCE in b["evidence_classes"]]
    by_name = [b for b in bindings if b["evidence_classes"] == ["NAME_ONLY"]]
    assert {case_number(b) for b in by_id} == {"02-2017-7303", "02-2018-0013"}
    # the id link is to the ECHO record, on EPA's own say-so ...
    assert {(b["left_id"], b["left_authority"]) for b in by_id} == {
        (sw.echo_entity_id(TOA_ALTA_ECHO_ID), sw.ECHO_AUTHORITY)
    }
    # ... and the LMOP link to the same cases stays a name match
    assert by_name and all(b["left_authority"] == sw.LMOP_AUTHORITY for b in by_name)
    assert {b["adjudication_state"] for b in bindings} == {"CANDIDATE_NOT_IDENTITY"}


# ---------------------------------------------------------------------------
# Facility reports
# ---------------------------------------------------------------------------


def test_dfr_summary_reads_the_real_toa_alta_report():
    summary = sw.summarize_dfr(TOA_ALTA_ECHO_ID, TOA_ALTA_DFR)
    rcra = summary["by_statute"]["RCRA"]
    assert rcra["formal_actions"] == 4 and rcra["penalties_usd"] == 50000.0
    assert {"02-2017-7303", "02-2018-0013"} <= set(rcra["source_ids"])
    assert all(v["formal_actions"] == 0 for k, v in summary["by_statute"].items() if k != "RCRA")
    assert summary["system_extract_dates"] and summary["program_windows"]["RCRA"]["start"]


def test_dfr_summary_rejects_another_facilitys_report_and_failed_messages():
    with pytest.raises(ValueError):
        sw.summarize_dfr("999", TOA_ALTA_DFR)
    with pytest.raises(ValueError):
        sw.summarize_dfr(TOA_ALTA_ECHO_ID, {**TOA_ALTA_DFR, "Message": "Error"})


def test_dfr_reports_must_match_the_echo_records_one_to_one():
    with pytest.raises(ValueError):  # a record without a report
        sw.build_dfr_rows({TOA_ALTA_ECHO_ID: TOA_ALTA_DFR}, [TOA_ALTA_ECHO_ID, "110000000001"])
    with pytest.raises(ValueError):  # a report for a record the registry does not hold
        sw.build_dfr_rows({TOA_ALTA_ECHO_ID: TOA_ALTA_DFR, "1": TOA_ALTA_DFR}, [TOA_ALTA_ECHO_ID])


# ---------------------------------------------------------------------------
# The ledger: every landfill case in exactly one bucket; leads are notes, not entities
# ---------------------------------------------------------------------------


def test_ledger_puts_every_landfill_case_in_one_bucket_and_leads_are_not_entities():
    cands = [lmop_candidate(m) for m in ("Arroyo", "Toa Alta", "Toa Baja")]
    names = [m["name"] for m in json.loads(GEO.read_text(encoding="utf-8"))["municipios"]]
    summary = sw.summarize_dfr(TOA_ALTA_ECHO_ID, TOA_ALTA_DFR)
    context = context_cases()
    bindings = sw.case_bindings(cands, context, [summary])
    ledger, notes = sw.enforcement_ledger(
        cases_pulled=len(CASES), context=context, bindings=bindings, lmop_cands=cands,
        municipalities=names, echo=sw.RegistryRecords(entities=ECHO), dfr_summaries=[summary],
    )
    c = ledger["cases"]
    assert (c["landfill_context"], c["bound_by_name_to_lmop_sites"]) == (8, 5)
    assert (c["named_municipality_without_lmop_site"], c["bound_to_no_municipality"]) == (1, 2)
    assert c["undated"] == 0 and ledger["id_confirmed_links"] == 2
    assert ledger["lmop_sites_with_candidate_case"] == 3 and ledger["lmop_sites_without_candidate_case"] == []
    codes = sorted(n["code"] for n in notes)
    assert codes == ["ENFORCEMENT_CASE_UNBOUND", "ENFORCEMENT_CASE_UNBOUND", "REGISTRY_GAP_LEAD"]
    assert all(n["entity_id"].startswith(sw.CASES_SOURCE) for n in notes)  # a case, never an entity id
    lead = next(n for n in notes if n["code"] == "REGISTRY_GAP_LEAD")
    assert "Santa Isabel" in lead["detail"] and "CALABAZA LANDFILL" in lead["detail"]


# ---------------------------------------------------------------------------
# The committed snapshot: what the frozen 2026-11-13 pull produced
# ---------------------------------------------------------------------------


def test_committed_enforcement_ledger_matches_the_frozen_pull_and_closes():
    ledger = RECEIPTS["coverage_ledger"]
    enf = ledger["enforcement"]
    cases = enf["cases"]
    assert cases == {
        "pulled": 3788, "landfill_context": 51, "bound_by_name_to_lmop_sites": 43,
        "linked_by_id_only_to_echo_record": 0,
        "named_municipality_without_lmop_site": 3, "bound_to_no_municipality": 5, "undated": 0,
    }
    assert cases["landfill_context"] == (
        cases["bound_by_name_to_lmop_sites"]
        + cases["linked_by_id_only_to_echo_record"]
        + cases["named_municipality_without_lmop_site"]
        + cases["bound_to_no_municipality"]
    )
    assert enf["lmop_sites_with_candidate_case"] == 16
    assert enf["lmop_sites_with_candidate_case"] + len(enf["lmop_sites_without_candidate_case"]) == len(LMOP) == 32
    assert enf["id_confirmed_links"] == 2
    assert enf["facility_reports"] == {"reports": 16, "with_formal_action_in_window": 1, "formal_actions_in_window": 4}
    # still bounded and open: enforcement coverage is partial and says so
    assert RECEIPTS["result"] == "OPEN" and ledger["completeness_claimed"] is False
    residue = ledger["open_residue"]
    assert not any("not yet acquired" in r for r in residue)
    assert len(residue) == 4 and "partial" in residue[1]  # only the enforcement line changed ...
    assert residue[0].startswith("Puerto Rico solid-waste authority") and residue[2].startswith("unauthorized dumps")
    assert residue[3].startswith("cross-source identity")  # ... the others kept their place and text


def test_committed_manifestations_pin_the_pull_and_carry_effective_controls():
    m = {x["source_id"]: x for x in RECEIPTS["manifestations"]}
    cases = m[sw.CASES_SOURCE]
    assert cases["row_count"] == 3788 and cases["landfill_context_rows"] == 51 and len(cases["response_sha256"]) == 64
    assert cases["filter_control"] == {
        "filtered_rows": 3788, "nonsense_state_rows": 0, "unfiltered_total": 313712, "effective": True,
    }
    reports = m[sw.DFR_SOURCE]
    assert reports["row_count"] == 16 and len(reports["registry_ids"]) == 16
    assert reports["registry_ids"] == sorted(e["authority_id"] for e in ECHO)
    assert cases["full_response_committed"] is False and reports["full_response_committed"] is False
    assert {x["evidence_tier"] for x in RECEIPTS["manifestations"]} == {"T1"}
    # the receipt never claims to predate its own data
    assert RECEIPTS["generated_at"] >= max(x["retrieved_at"] for x in RECEIPTS["manifestations"])


def test_committed_enforcement_bindings_are_candidates_and_only_two_are_id_evidence():
    enf = [b for b in RECEIPTS["candidate_bindings"] if b["binding_type"] == sw.CASE_BINDING_TYPE]
    assert len(enf) == 45 and {b["adjudication_state"] for b in enf} == {"CANDIDATE_NOT_IDENTITY"}
    by_id = [b for b in enf if sw.ID_EVIDENCE in b["evidence_classes"]]
    assert len(by_id) == 2 and {b["left_id"] for b in by_id} == {sw.echo_entity_id(TOA_ALTA_ECHO_ID)}
    assert all(b["evidence_classes"] == ["NAME_ONLY"] for b in enf if b not in by_id)
    arroyo = next(e for e in LMOP if e["municipality"] == "Arroyo")
    assert any(b["left_id"] == arroyo["entity_id"] and b["right_id"].endswith("02-2016-7303") for b in enf)
    ids = [b["binding_id"] for b in RECEIPTS["candidate_bindings"]]
    assert len(set(ids)) == len(ids)


def test_enforcement_creates_no_entity_geometry_or_event():
    # Scoped to this registry's authorities: other environmental sources may share these files later.
    owned = [e for e in ENTITIES if e["authority"] in (sw.LMOP_AUTHORITY, sw.ECHO_AUTHORITY)]
    owned_ids = {e["entity_id"] for e in owned}
    assert len(owned) == 48
    assert not any(e["authority"] in (sw.CASES_SOURCE, sw.DFR_SOURCE) for e in ENTITIES)
    geometries = db.load("environmental_geometry", DATA / "environmental_geometries.jsonl")
    assert sum(1 for g in geometries if g["entity_id"] in owned_ids) == 48
    events = [e for e in db.load("environmental_exposure_event", DATA / "environmental_exposure_events.jsonl")
              if set(e["entity_ids"]) & owned_ids]
    assert {e["event_type"] for e in events} == {"SHUTDOWN"}
    assert len(events) == RECEIPTS["coverage_ledger"]["lmop"]["shutdown_events"]


def test_committed_raw_rows_hold_51_cases_and_16_reports_with_matching_hashes():
    cases = [r for r in RAW if r["source"] == sw.CASES_SOURCE]
    reports = [r for r in RAW if r["source"] == sw.DFR_SOURCE]
    assert len(cases) == 51 and len(reports) == 16
    assert {r["disposition"] for r in cases} == {"RAW_ONLY"}  # the full case row, as served
    assert {r["disposition"] for r in reports} == {"DERIVED_SUMMARY"}  # a reduction of the report, not the report
    assert all(r["row_sha256"] == sw.canonical_sha256(r["raw"]) for r in RAW)
    assert sum(1 for r in RAW if r["source"] in (sw.LMOP_AUTHORITY, "EPA_ECHO")) == 48  # nothing else moved


def test_committed_registry_gap_leads_are_notes_not_entities():
    leads = [n for n in RECEIPTS["review_notes"] if n["code"] == "REGISTRY_GAP_LEAD"]
    assert len(leads) == 3 and all(n["entity_id"].startswith(sw.CASES_SOURCE) for n in leads)
    # ECHO holds a landfill in Santa Isabel and LMOP does not: the one gap with a candidate record
    assert any("CALABAZA LANDFILL" in n["detail"] for n in leads)
    assert sum(1 for n in RECEIPTS["review_notes"] if n["code"] == "ENFORCEMENT_CASE_UNBOUND") == 5


def test_the_pins_are_recorded_with_the_tier_their_provenance_supports():
    origin = RECEIPTS["seed_candidates"]["spiderweb_pins"]
    assert origin["evidence_tier"] == "T4" and origin["origin_label_tier"] == "T2"
    assert origin["source_package"].startswith("Spiderweb_Package") and "no upstream" in origin["note"]


# ---------------------------------------------------------------------------
# Corrections found by the independent review of this change
# ---------------------------------------------------------------------------


def test_a_case_linked_only_by_id_is_its_own_bucket_never_reported_unbound():
    # a landfill case with no municipality in its name, but listed by an ECHO facility report
    case = CASES["PR000A200142975"]
    report = {**TOA_ALTA_DFR, "InspectionEnforcementSummary": {
        **TOA_ALTA_DFR["InspectionEnforcementSummary"],
        "Source": [{"Statute": "CAA", "SourceID": case["CaseNumber"], "InspectionCount": "0",
                    "FormalEnfActCount": "0", "TotalPenalties": "$0"}],
    }}
    summary = sw.summarize_dfr(TOA_ALTA_ECHO_ID, report)
    names = [m["name"] for m in json.loads(GEO.read_text(encoding="utf-8"))["municipios"]]
    bindings = sw.case_bindings([], [case], [summary])
    assert [sw.ID_EVIDENCE in b["evidence_classes"] for b in bindings] == [True]
    ledger, notes = sw.enforcement_ledger(
        cases_pulled=1, context=[case], bindings=bindings, lmop_cands=[], municipalities=names,
        echo=sw.RegistryRecords(entities=ECHO), dfr_summaries=[summary],
    )
    c = ledger["cases"]
    assert c["linked_by_id_only_to_echo_record"] == 1 and c["bound_to_no_municipality"] == 0
    assert notes == []  # EPA's own report ties it to an ECHO record, so it is not "unbound"
    assert ledger["unbound"]["bound_to_no_municipality"] == []


@pytest.mark.parametrize(
    "text, expected",
    [("$50,000", "50000"), ("$0", "0"), ("$0.10", "0.10"), ("", "0"), (None, "0"),
     ("($500.00)", "-500.00"), ("-$5", "-5"), ("1,234.56", "1234.56")],
)
def test_money_is_parsed_exactly(text, expected):
    from decimal import Decimal

    assert sw._money(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["abc", "$5 USD", "(5", "5)", "$", "N/A"])
def test_money_that_is_not_an_amount_fails_instead_of_reading_as_zero(text):
    with pytest.raises(ValueError):
        sw._money(text)


def test_penalties_sum_exactly_without_float_noise():
    report = {**TOA_ALTA_DFR, "InspectionEnforcementSummary": {
        **TOA_ALTA_DFR["InspectionEnforcementSummary"],
        "Source": [{"Statute": "CWA", "SourceID": f"X{i}", "InspectionCount": "0", "FormalEnfActCount": "1",
                    "TotalPenalties": amount} for i, amount in enumerate(["$0.10", "$0.20", "$1,234.46"])],
    }}
    assert sw.summarize_dfr(TOA_ALTA_ECHO_ID, report)["by_statute"]["CWA"]["penalties_usd"] == 1234.76


def test_a_penalty_that_is_not_an_amount_fails_the_whole_summary():
    report = {**TOA_ALTA_DFR, "InspectionEnforcementSummary": {
        **TOA_ALTA_DFR["InspectionEnforcementSummary"],
        "Source": [{"Statute": "CWA", "SourceID": "X", "InspectionCount": "0", "FormalEnfActCount": "1",
                    "TotalPenalties": "pending"}],
    }}
    with pytest.raises(ValueError):
        sw.summarize_dfr(TOA_ALTA_ECHO_ID, report)


def test_the_latest_stamp_is_compared_as_an_instant_not_as_text():
    # 23:00 at -05:00 is 04:00Z the next day, later than 01:00Z, though it sorts earlier as text
    assert sw.latest_utc(["2026-11-13T23:00:00-05:00", "2026-11-14T01:00:00Z"]) == "2026-11-14T04:00:00Z"
    assert sw.latest_utc(["2026-11-05", "2026-11-05T08:12:36Z"]) == "2026-11-05T08:12:36Z"
    with pytest.raises(ValueError):
        sw.latest_utc(["2026-11-05T08:12:36Z", "last Tuesday"])


def test_generated_at_is_never_earlier_than_the_data_whatever_the_stamp_format():
    manifestations = [{"source_id": "A", "retrieved_at": "2026-11-13T23:00:00-05:00"}]
    receipts = sw.build_receipts(manifestations=manifestations, bindings=[], ledger={}, notes=[],
                                 now="2026-11-14T01:00:00Z")
    assert receipts["generated_at"] == "2026-11-14T04:00:00Z"
    with pytest.raises(ValueError):
        sw.build_receipts(manifestations=[{"source_id": "A", "retrieved_at": "soon"}], bindings=[],
                          ledger={}, notes=[], now="2026-11-14T01:00:00Z")


@pytest.mark.parametrize(
    "naics, expected",
    [("562212", True), ("221320 562212", True), ("221320,562212", True), ("5622129", False),
     ("1562212", False), ("562213", False), ("", False), (None, False)],
)
def test_landfill_naics_matches_whole_codes_not_prefixes(naics, expected):
    assert sw.is_landfill_context_case({"PrimaryNAICSCode": naics, "CaseName": "A Plant"}) is expected


def test_facility_report_rows_are_labelled_as_summaries_and_keep_only_what_was_summarised():
    summaries, rows = sw.build_dfr_rows({TOA_ALTA_ECHO_ID: TOA_ALTA_DFR}, [TOA_ALTA_ECHO_ID])
    (row,) = rows
    assert row["disposition"] == "DERIVED_SUMMARY" and row["raw"] == summaries[0]
    assert "InspectionEnforcementSummary" not in row["raw"]  # the report itself is not stored here
