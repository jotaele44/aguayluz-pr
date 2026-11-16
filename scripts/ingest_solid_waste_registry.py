#!/usr/bin/env python3
"""Freeze and ingest the Puerto Rico solid-waste (vertedero/landfill) site registry.

Implements the registry proposed in ``docs/adr/ADR-0004-solid-waste-registry-ownership.md``.
It builds canonical site records from two public federal sources, keeps their RAW rows
apart, and records every cross-source match as a candidate that is never merged:

* **EPA LMOP** Landfill and Landfill Gas Energy Project Database (xlsx): the Puerto Rico rows.
  Tier T1. Carries precise coordinates, owner/operator, years opened/closed, open/closed status.
* **EPA ECHO** facility query with SIC code 4953 (refuse systems) for Puerto Rico. Tier T1.
  Fail-closed control: ECHO silently ignores unknown filters (``p_naics`` returns the whole
  state), so the filtered row count must be below the unfiltered count.

* **EPA ECHO enforcement context** (cases and detailed facility reports). The case service is
  pulled for the whole state and filtered locally; only the landfill-context cases are kept as
  RAW rows and they are linked to sites as candidates (by name, or by id where an ECHO facility
  report lists the case number), never merged. No entity, geometry or event is created from them.
  The facility reports are stored as per-statute summaries labelled ``DERIVED_SUMMARY`` (not raw);
  the full responses are frozen by hash in the manifestations and are not committed.
  Fail-closed controls: the state filter must be shown to work (a nonsense state returns 0 rows
  and the filtered count is below the unfiltered total).

The result is always OPEN, never CERTIFIED: no structured Puerto Rico solid-waste authority
list and no unauthorized-dump source have been acquired, and enforcement coverage is partial.

Run:
    python scripts/ingest_solid_waste_registry.py                    # live fetch, write data/
    python scripts/ingest_solid_waste_registry.py --dry-run          # build and print, write nothing
    python scripts/ingest_solid_waste_registry.py --lmop-src f.xlsx --lmop-url <release url> --echo-src echo.json   # offline
    ... --cases-src cases.json --dfr-src dfr.json   # offline, with the enforcement subscope

The enforcement subscope is built only when both ``--cases-src`` and ``--dfr-src`` are given, or
when nothing is offline (a fully live run). An offline LMOP/ECHO run without them builds the
registry alone and says so; it does not read the network for enforcement.

Writes ``data/environmental_entities.jsonl``, ``environmental_geometries.jsonl``,
``environmental_exposure_events.jsonl`` (via ``aguayluz.environmental_exposure_db``),
``data/solid_waste_source_rows.jsonl`` (RAW rows) and ``data/solid_waste_receipts.json``
(manifestations, candidate bindings, coverage ledger).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz import environmental_exposure_db as db  # noqa: E402
from aguayluz import solid_waste as sw  # noqa: E402

LMOP_URL = "https://www.epa.gov/system/files/documents/2024-09/landfilllmopdata.xlsx"
ECHO_BASE = "https://echodata.epa.gov/echo/echo_rest_services"
CASES_BASE = "https://echodata.epa.gov/echo/case_rest_services"
DFR_URL = "https://echodata.epa.gov/echo/dfr_rest_services.get_dfr"
NONSENSE_STATE = "ZZ"
MAX_CASE_PAGES = 20
USER_AGENT = "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"
OWNED_AUTHORITIES = frozenset({sw.LMOP_AUTHORITY, sw.ECHO_AUTHORITY})
MAX_ECHO_PAGES = 50


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    from aguayluz.http_retry import get_with_retry

    response = get_with_retry(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=120)
    response.raise_for_status()
    return response


def fetch_lmop_bytes(url: str) -> bytes:
    return bytes(_get(url).content)


def fetch_echo() -> dict[str, Any]:
    """Two-step ECHO fetch (QueryID, then paged rows) plus the unfiltered control count."""
    base_params = {"output": "JSON", "p_st": sw.PR_STATE}
    filtered = _get(f"{ECHO_BASE}.get_facilities", {**base_params, "p_sic": sw.ECHO_SIC}).json()["Results"]
    unfiltered = _get(f"{ECHO_BASE}.get_facilities", base_params).json()["Results"]
    expected = int(filtered["QueryRows"])
    facilities: list[dict[str, Any]] = []
    for page in range(1, MAX_ECHO_PAGES + 1):
        result = _get(
            f"{ECHO_BASE}.get_qid",
            {"output": "JSON", "qid": filtered["QueryID"], "pageno": page, "qcolumns": sw.ECHO_QCOLUMNS},
        ).json()["Results"]
        rows = result.get("Facilities") or []
        facilities.extend(rows)
        if not rows or len(facilities) >= expected:
            break
    return {
        "query": {**base_params, "p_sic": sw.ECHO_SIC},
        "qcolumns": sw.ECHO_QCOLUMNS,
        "filtered_rows": expected,
        "unfiltered_rows": int(unfiltered["QueryRows"]),
        "facilities": facilities,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _case_results(path: str, **params: Any) -> dict[str, Any]:
    return dict(_get(f"{CASES_BASE}.{path}", {"output": "JSON", **params}).json()["Results"])


def _unfiltered_case_total(results: dict[str, Any]) -> int:
    """The case service refuses an unfiltered query and states the total in its error message."""
    message = str((results.get("Error") or {}).get("ErrorMessage") or "")
    found = re.search(r"Rows Returned would be (\d+)", message)
    if not found:
        raise ValueError("could not read the unfiltered ECHO case total; refusing to trust the state filter")
    return int(found.group(1))


def fetch_cases(retrieved_at: str) -> dict[str, Any]:
    """Whole-state ECHO case pull plus the controls that show the state filter works.

    ``retrieved_at`` is the run's stamp (``--retrieved-at`` or now), as for the LMOP and ECHO pulls.
    """
    state = _case_results("get_cases", p_state=sw.PR_STATE)
    nonsense = _case_results("get_cases", p_state=NONSENSE_STATE)
    unfiltered = _unfiltered_case_total(_case_results("get_cases"))
    expected = int(state["QueryRows"])
    cases: list[dict[str, Any]] = []
    for page in range(1, MAX_CASE_PAGES + 1):
        rows = _case_results("get_qid", qid=state["QueryID"], pageno=page).get("Cases") or []
        cases.extend(rows)
        if not rows or len(cases) >= expected:
            break
    return {
        "query": {"p_state": sw.PR_STATE},
        "retrieved_at": retrieved_at,
        "filtered_rows": expected,
        # strict: a missing QueryRows must fail the run, never read as "0 rows" and pass the control
        "nonsense_rows": int(nonsense["QueryRows"]),
        "unfiltered_total": unfiltered,
        "cases": cases,
    }


def accepted_registry_ids(echo: dict[str, Any]) -> list[str]:
    """RegistryIDs of the ECHO rows that become registry entities.

    The facility reports must match these one to one, so a row the builder rejects (a duplicate,
    a non-Puerto-Rico state, a blank name) must not have its report fetched.
    """
    records = sw.build_echo_records(list(echo["facilities"]), f"p_sic={sw.ECHO_SIC}")
    return sorted(e["authority_id"] for e in records.entities)


def fetch_dfr(registry_ids: list[str], retrieved_at: str) -> dict[str, Any]:
    """One ECHO detailed facility report per RegistryID."""
    reports = {
        rid: dict(_get(DFR_URL, {"output": "JSON", "p_id": rid}).json()["Results"])
        for rid in sorted(registry_ids)
    }
    return {"retrieved_at": retrieved_at, "reports": reports}


def _committed_enforcement(receipts_path: Path) -> bool:
    """Does the existing receipts file already hold the enforcement subscope?"""
    if not receipts_path.is_file():
        return False
    manifests = json.loads(receipts_path.read_text(encoding="utf-8")).get("manifestations", [])
    return any(m.get("source_id") in (sw.CASES_SOURCE, sw.DFR_SOURCE) for m in manifests)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _usgs_landfill_wells(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        a
        for a in assets
        if str(a.get("asset_id", "")).startswith("USGSWQ_")
        and any(word in str(a.get("asset_name", "")).upper() for word in ("VERTEDERO", "LANDFILL"))
    ]


def build_enforcement(
    *,
    echo_records: sw.RegistryRecords,
    lmop_cands: list[sw.Candidate],
    cases: dict[str, Any],
    dfr: dict[str, Any],
    municipios: list[str],
) -> dict[str, Any]:
    """Case rows, facility-report rows, candidate bindings, ledger and manifestations. Fails closed."""
    control = sw.case_service_control(
        int(cases["filtered_rows"]), int(cases["nonsense_rows"]), int(cases["unfiltered_total"])
    )
    case_list = list(cases["cases"])
    if len(case_list) != int(cases["filtered_rows"]):
        raise ValueError(f"ECHO returned {len(case_list)} cases but the query reported {cases['filtered_rows']}")
    context, case_rows = sw.build_case_rows(case_list)
    expected_ids = sorted(e["authority_id"] for e in echo_records.entities)
    reports = dict(dfr["reports"])
    summaries, dfr_rows = sw.build_dfr_rows(reports, expected_ids)
    bindings = sw.case_bindings(lmop_cands, context, summaries)
    ledger, notes = sw.enforcement_ledger(
        cases_pulled=len(case_list),
        context=context,
        bindings=bindings,
        lmop_cands=lmop_cands,
        municipalities=municipios,
        echo=echo_records,
        dfr_summaries=summaries,
    )
    extract_dates: dict[str, list[str]] = {}
    for s in summaries:
        for system, date in s["system_extract_dates"].items():
            extract_dates.setdefault(system, [])
            if date not in extract_dates[system]:
                extract_dates[system].append(date)
    manifestations = [
        {
            "source_id": sw.CASES_SOURCE,
            "authority": "U.S. EPA Enforcement and Compliance History Online",
            "title": "ECHO enforcement case search, Puerto Rico (p_state=PR), all programs",
            "locator": f"{CASES_BASE}.get_cases",
            "query": cases["query"],
            "retrieved_at": cases["retrieved_at"],
            "response_sha256": sw.canonical_sha256(case_list),
            "row_count": len(case_list),
            "landfill_context_rows": len(context),
            "full_response_committed": False,  # frozen by hash; only the landfill-context rows are stored
            "filter_control": control,
            "evidence_tier": "T1",
        },
        {
            "source_id": sw.DFR_SOURCE,
            "authority": "U.S. EPA Enforcement and Compliance History Online",
            "title": "ECHO detailed facility reports for the ECHO registry records",
            "locator": DFR_URL,
            "registry_ids": expected_ids,
            "retrieved_at": dfr["retrieved_at"],
            "response_sha256": sw.canonical_sha256({rid: reports[rid] for rid in expected_ids}),
            "row_count": len(expected_ids),
            "full_response_committed": False,  # the stored rows are per-statute summaries, not the reports
            "system_extract_dates": {k: sorted(v) for k, v in sorted(extract_dates.items())},
            "evidence_tier": "T1",
        },
    ]
    return {
        "bindings": bindings,
        "ledger": ledger,
        "notes": notes,
        "rows": case_rows + dfr_rows,
        "manifestations": manifestations,
    }


def build(
    lmop_bytes: bytes,
    lmop_url: str,
    echo: dict[str, Any],
    assets: list[dict[str, Any]],
    now: str,
    *,
    cases: dict[str, Any] | None = None,
    dfr: dict[str, Any] | None = None,
    municipios: list[str] | None = None,
) -> dict[str, Any]:
    """Build every record and receipt in memory. Raises (and writes nothing) on any failed control."""
    release = sw.lmop_release_from_url(lmop_url)
    table = sw.read_lmop_workbook(lmop_bytes)
    pr_rows = sw.select_state(table.rows)
    lmop = sw.build_lmop_records(pr_rows, release)

    control = sw.echo_filter_control(int(echo["filtered_rows"]), int(echo["unfiltered_rows"]))
    facilities = list(echo["facilities"])
    if len(facilities) != int(echo["filtered_rows"]):
        raise ValueError(
            f"ECHO returned {len(facilities)} rows but the query reported {echo['filtered_rows']}"
        )
    label = f"p_sic={sw.ECHO_SIC}"
    echo_records = sw.build_echo_records(facilities, label)

    lmop_cands = sw.candidates_from_records(lmop)
    echo_cands = sw.candidates_from_records(echo_records)
    pins, wells = sw.seed_candidates(_usgs_landfill_wells(assets))
    same_echo, unbound_echo = sw.candidate_bindings(lmop_cands, echo_cands, "SAME_SITE_CANDIDATE")
    same_pin, unbound_pin = sw.candidate_bindings(lmop_cands, pins, "SAME_SITE_CANDIDATE")
    related_wells, unbound_wells = sw.candidate_bindings(
        lmop_cands, wells, "RELATED_MONITORING_LOCATION_CANDIDATE"
    )
    enforcement: dict[str, Any] | None = None
    if cases is not None or dfr is not None:
        if cases is None or dfr is None or municipios is None:
            raise ValueError(
                "the enforcement subscope needs the case pull, the facility reports and the "
                "municipality list together"
            )
        enforcement = build_enforcement(
            echo_records=echo_records, lmop_cands=lmop_cands, cases=cases, dfr=dfr, municipios=municipios
        )
    bindings = sorted(
        same_echo + same_pin + related_wells + (enforcement["bindings"] if enforcement else []),
        key=lambda b: b["binding_id"],
    )
    ledger = sw.coverage_ledger(
        lmop_total_rows=len(table.rows),
        lmop_pr_rows=len(pr_rows),
        lmop=lmop,
        echo_rows=len(facilities),
        echo=echo_records,
        bindings=bindings,
        unbound={"lmop_vs_echo": unbound_echo, "lmop_vs_pins": unbound_pin, "lmop_vs_wells": unbound_wells},
        enforcement=enforcement["ledger"] if enforcement else None,
    )
    manifestations = [
        {
            "source_id": "EPA_LMOP",
            "authority": "U.S. EPA Landfill Methane Outreach Program",
            "title": "Landfill and Landfill Gas Energy Project Database",
            "locator": lmop_url,
            "release": release,
            "retrieved_at": now,
            "byte_sha256": hashlib.sha256(lmop_bytes).hexdigest(),
            "byte_count": len(lmop_bytes),
            "sheet": table.sheet,
            "header": list(table.headers),
            "total_rows": len(table.rows),
            "pr_rows": len(pr_rows),
            "evidence_tier": "T1",
        },
        {
            "source_id": "EPA_ECHO",
            "authority": "U.S. EPA Enforcement and Compliance History Online",
            "title": "ECHO facility query, Puerto Rico, SIC 4953 (refuse systems)",
            "locator": f"{ECHO_BASE}.get_facilities",
            "query": echo["query"],
            "qcolumns": echo.get("qcolumns", sw.ECHO_QCOLUMNS),
            "retrieved_at": now,
            "response_sha256": sw.canonical_sha256(facilities),
            "row_count": len(facilities),
            "filter_control": control,
            "evidence_tier": "T1",
        },
    ]
    if enforcement:
        manifestations += enforcement["manifestations"]
    notes = lmop.notes + echo_records.notes + (enforcement["notes"] if enforcement else [])
    return {
        "lmop": lmop,
        "echo": echo_records,
        "enforcement_rows": enforcement["rows"] if enforcement else [],
        "receipts": sw.build_receipts(
            manifestations=manifestations, bindings=bindings, ledger=ledger, notes=notes, now=now
        ),
    }


def write_outputs(built: dict[str, Any], data_dir: Path) -> None:
    lmop, echo_records = built["lmop"], built["echo"]
    entities = lmop.entities + echo_records.entities
    geometries = lmop.geometries + echo_records.geometries
    events = lmop.events + echo_records.events
    paths = {
        "environmental_entity": data_dir / "environmental_entities.jsonl",
        "environmental_geometry": data_dir / "environmental_geometries.jsonl",
        "environmental_exposure_event": data_dir / "environmental_exposure_events.jsonl",
    }
    # Validate every table, existing rows and incoming rows alike, before any file is written.
    # Otherwise a schema failure in the geometry or event table would be found only after the
    # entity file had already been replaced, leaving a mixed snapshot. Raises
    # ``jsonschema.ValidationError``; ``main`` turns that into a fail-closed exit.
    for kind, incoming in (
        ("environmental_entity", entities),
        ("environmental_geometry", geometries),
        ("environmental_exposure_event", events),
    ):
        db.load(kind, paths[kind])
        db.merge(kind, [], incoming)
    owned_ids = {
        e["entity_id"]
        for e in db.load("environmental_entity", paths["environmental_entity"])
        if e["authority"] in OWNED_AUTHORITIES
    } | {e["entity_id"] for e in entities}
    db.replace_where(
        "environmental_entity", entities,
        drop=lambda r: r["authority"] in OWNED_AUTHORITIES, path=paths["environmental_entity"],
    )
    db.replace_where(
        "environmental_geometry", geometries,
        drop=lambda r: r["entity_id"] in owned_ids, path=paths["environmental_geometry"],
    )
    db.replace_where(
        "environmental_exposure_event", events,
        drop=lambda r: bool(owned_ids & set(r["entity_ids"])), path=paths["environmental_exposure_event"],
    )
    raw_rows = sorted(
        lmop.raw_rows + echo_records.raw_rows + built.get("enforcement_rows", []),
        key=lambda r: r["source_record_id"],
    )
    (data_dir / "solid_waste_source_rows.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in raw_rows),
        encoding="utf-8",
    )
    (data_dir / "solid_waste_receipts.json").write_text(
        json.dumps(built["receipts"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lmop-src", help="offline LMOP xlsx file (default: fetch --lmop-url)")
    ap.add_argument(
        "--lmop-url",
        default=None,
        help=f"LMOP workbook URL; the release is read from it (default for a live fetch: {LMOP_URL}). "
        "Required with --lmop-src, so a file is never labelled as a release it is not",
    )
    ap.add_argument("--echo-src", help="offline ECHO JSON ({query, filtered_rows, unfiltered_rows, facilities})")
    ap.add_argument("--cases-src", help="offline ECHO case pull JSON (needs --dfr-src)")
    ap.add_argument("--dfr-src", help="offline ECHO facility reports JSON (needs --cases-src)")
    ap.add_argument(
        "--municipios",
        default=str(DATA_DIR / "geo" / "pr_municipios.json"),
        help="municipality list used to classify landfill cases that name no LMOP municipality",
    )
    ap.add_argument("--assets", default=str(DATA_DIR / "utility_assets.jsonl"))
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--retrieved-at", help="override the retrieval timestamp (reproducible runs)")
    ap.add_argument("--dry-run", action="store_true", help="build and print the ledger; write nothing")
    args = ap.parse_args(argv)

    now = args.retrieved_at or _utc_now()
    if args.lmop_src and not args.lmop_url:
        print(
            "FAIL-CLOSED: --lmop-src needs --lmop-url naming the release that file belongs to; "
            "the default URL would label an unknown workbook as the 2024-09 release",
            file=sys.stderr,
        )
        return 2
    if bool(args.cases_src) != bool(args.dfr_src):
        print("FAIL-CLOSED: --cases-src and --dfr-src go together", file=sys.stderr)
        return 2
    lmop_url = args.lmop_url or LMOP_URL
    # Enforcement runs for a fully live run, or when its inputs are given. An offline LMOP/ECHO
    # run without them builds the registry alone and says so; it never reaches for the network.
    with_enforcement = bool(args.cases_src) or not (args.lmop_src or args.echo_src)
    try:
        lmop_bytes = Path(args.lmop_src).read_bytes() if args.lmop_src else fetch_lmop_bytes(lmop_url)
        echo = json.loads(Path(args.echo_src).read_text(encoding="utf-8")) if args.echo_src else fetch_echo()
        cases = dfr = municipios = None
        if with_enforcement:
            cases = (
                json.loads(Path(args.cases_src).read_text(encoding="utf-8")) if args.cases_src else fetch_cases(now)
            )
            if args.dfr_src:
                dfr = json.loads(Path(args.dfr_src).read_text(encoding="utf-8"))
            else:
                dfr = fetch_dfr(accepted_registry_ids(echo), now)
            municipios = [
                str(m["name"]) for m in json.loads(Path(args.municipios).read_text(encoding="utf-8"))["municipios"]
            ]
        else:
            print("note: enforcement subscope not built (offline run without --cases-src/--dfr-src)")
        built = build(
            lmop_bytes, lmop_url, echo, _load_jsonl(Path(args.assets)), now,
            cases=cases, dfr=dfr, municipios=municipios,
        )
        # The outputs are rewritten whole, so a run without the enforcement inputs would erase
        # the enforcement rows, manifestations, bindings and ledger already committed there.
        if not with_enforcement and not args.dry_run and _committed_enforcement(
            Path(args.data_dir) / "solid_waste_receipts.json"
        ):
            raise ValueError(
                "a registry-only run would drop the enforcement data already in the data directory; "
                "pass --cases-src and --dfr-src, or write to a fresh --data-dir"
            )
    # OSError covers a missing file and every ``requests`` failure (RequestException is an IOError).
    except (sw.FilterIgnoredError, ValueError, KeyError, OSError) as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2

    ledger = built["receipts"]["coverage_ledger"]
    print(json.dumps({"result": built["receipts"]["result"], "coverage_ledger": ledger}, indent=2, sort_keys=True))
    if args.dry_run:
        print("dry-run: nothing written")
        return 0
    try:
        write_outputs(built, Path(args.data_dir))
    except jsonschema.ValidationError as exc:
        print(f"FAIL-CLOSED: schema validation failed before any file was written: {exc.message}", file=sys.stderr)
        return 2
    print(f"wrote {Path(args.data_dir)} (entities, geometries, events, source rows, receipts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
