"""aguayluz.aquifer_bands: parser, classifier and read-side helpers.

Positive inputs are the real capture of the USGS page (tests/fixtures/
prdner_hydro_conditions_selected_wells.html.txt, fetched 2026-11-08, SHA-256 20d8814f...).
The `.txt` suffix is deliberate: the capture is a verbatim third-party page whose exact bytes
are the test oracle, and as `.html` a code scanner treats its inline JavaScript as first-party
source and reports style findings on code this repo does not own and must not edit.
The expected band edges below were extracted independently of the parser and are the
oracle. Drift cases are CONSTRUCTED from that capture by editing it, and say so.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from aguayluz import aquifer_bands as ab

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "prdner_hydro_conditions_selected_wells.html.txt"
PAGE = FIXTURE.read_bytes()
TEXT = PAGE.decode("latin-1")

# site -> (title, edges: land surface, then the deep edge of each of the five bands)
EXPECTED = {
    "175934066364800": ("CONSTANCIA 3 WELL, PONCE", [0, 8.6, 10.49, 12.0, 13.65, 15.0]),
    "180057066311300": ("PIEZOMETER JAC-6, JUANA DIAZ", [0, 18.9, 22.02, 25.38, 26.9, 30.0]),
    "175734066233300": ("ALOMAR OESTE WELL, SANTA ISABEL", [0, 13.2, 15.79, 16.45, 17.4, 20.0]),
    "175947066130601": ("PIEZOMETER AGUIRRE HW 5B, SALINAS", [0, 12.25, 16.54, 21.42, 23.43, 35.0]),
    "175910066155500": ("PIEZOMETER RASA D, SALINAS", [0, 31.6, 38.2, 45.6, 51.55, 60.0]),
}
# Depths measured 2026-11-08 (legacy IV feed, provisional), and the class the page itself shows.
TODAY = {
    "175934066364800": (9.08, "optimum", 4.57),
    "180057066311300": (24.65, "observation", 2.25),
    "175734066233300": (16.09, "observation", 1.31),
    "175947066130601": (29.76, "critical", -6.33),
    "175910066155500": (48.03, "operational_adjustment", 3.52),
}


@pytest.fixture(scope="module")
def page():
    return ab.parse_page(PAGE)


def bands_of(page, site):
    return next(w for w in page.wells if w.site_no == site).bands


# ── the real capture ──────────────────────────────────────────────────────────
def test_real_capture_yields_the_five_wells_in_chart_order(page):
    assert page.parameter_code == "72019"
    assert [w.site_no for w in page.wells] == list(EXPECTED)
    assert [w.chart_id for w in page.wells] == [f"wellBulletChart{i}" for i in range(1, 6)]


@pytest.mark.parametrize("site", list(EXPECTED))
def test_band_edges_match_the_independent_extraction(page, site):
    title, edges = EXPECTED[site]
    well = next(w for w in page.wells if w.site_no == site)
    assert well.title == title
    assert [b.cls for b in well.bands] == list(ab.CLASSES)
    assert [b.shallow_ft for b in well.bands] == edges[:-1]
    assert [b.deep_ft for b in well.bands] == edges[1:]
    assert well.axis_max_ft == edges[-1]
    assert well.reference_url == f"https://groundwaterwatch.usgs.gov/AWLSites.asp?S={site}&ncd="


def test_the_two_known_source_inconsistencies_are_recorded_and_nothing_else(page):
    found = {w.site_no: list(w.discrepancies) for w in page.wells if w.discrepancies}
    assert found == {
        "175947066130601": ["observation: chart range ends 21.42 ft, label ladder 21.43 ft"],
        "175910066155500": ["above_optimum: absent from the label ladder (chart range ends 31.6)"],
    }


# ── classification ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("site", list(TODAY))
def test_todays_depths_land_in_the_class_the_page_shows(page, site):
    depth, cls, margin = TODAY[site]
    bands = bands_of(page, site)
    assert ab.classify(bands, depth) == cls
    assert ab.margin_to_critical_ft(bands, depth) == margin


def test_edges_are_shallow_inclusive_and_deep_exclusive(page):
    bands = bands_of(page, "175947066130601")  # Aguirre HW 5B
    assert ab.classify(bands, 12.25) == "optimum"
    assert ab.classify(bands, 12.2499) == "above_optimum"
    assert ab.classify(bands, 23.43) == "critical"
    assert ab.classify(bands, 23.4299) == "operational_adjustment"


def test_depth_at_or_beyond_the_chart_axis_is_still_critical(page):
    """The page's own label ladders fall through here and leave the well unclassified."""
    bands = bands_of(page, "175947066130601")
    for depth in (35.0, 35.01, 61, 1e9, math.inf):
        assert ab.classify(bands, depth) == "critical"


def test_negative_depth_is_a_flowing_well_not_an_error(page):
    assert ab.classify(bands_of(page, "175947066130601"), -1.5) == "above_optimum"


@pytest.mark.parametrize("bad", [math.nan, None, "12", True, [1.0]])
def test_non_numeric_depth_is_rejected_not_coerced(page, bad):
    with pytest.raises(ValueError):
        ab.classify(bands_of(page, "175947066130601"), bad)


@pytest.mark.parametrize("site", list(EXPECTED))
def test_classification_is_total_monotone_and_reaches_every_class(page, site):
    bands = bands_of(page, site)
    order = {c: i for i, c in enumerate(ab.CLASSES)}
    seen = [order[ab.classify(bands, d / 100)] for d in range(-100, 9000)]
    assert seen == sorted(seen)
    assert set(seen) == set(range(len(ab.CLASSES)))


def test_material_digest_tracks_edges_and_ignores_nothing_it_should_not(page):
    bands = bands_of(page, "175947066130601")
    assert ab.material_digest(bands) == ab.material_digest(bands)
    moved = tuple(
        ab.Band(b.cls, b.shallow_ft, 21.43) if b.cls == "observation"
        else ab.Band(b.cls, 21.43, b.deep_ft) if b.cls == "operational_adjustment" else b
        for b in bands
    )
    assert ab.material_digest(moved) != ab.material_digest(bands)
    assert ab.material_digest(bands, "62610") != ab.material_digest(bands)


# ── drift: the page must fail closed, never be guessed at ─────────────────────
def _replace(old: str, new: str, count: int = -1):
    assert old in TEXT, f"fixture no longer contains {old!r}; update the drift case"
    return TEXT.replace(old, new, count).encode("latin-1")


def _extra_chart() -> bytes:
    # A structurally VALID chart (contiguous, shallow-to-deep classes), so the well count is
    # the only thing wrong with the page. The source lists bands deep to shallow, negated.
    bands = ", ".join(
        f'{{ startValue: {start}, endValue: {end}, color: "{color}", opacity: 0.5 }}'
        for start, end, color in [
            (-6, -5, "#D90000"), (-5, -4, "#FFA64D"), (-4, -3, "#FFFF00"), (-3, -2, "#007FFF"), (-2, 0, "#468C00"),
        ]
    )
    chart6 = f'$("#wellBulletChart6").jqxBulletChart({{ title: "EXTRA", ranges: [{bands}] }});\n'
    return _replace("var xmlhttp = new XMLHttpRequest();", chart6 + "var xmlhttp = new XMLHttpRequest();", 1)


def _drop_optimum_band() -> bytes:
    pattern = re.compile(r"\{[^{}]*#007FFF[^{}]*\},?")
    assert pattern.search(TEXT)
    return pattern.sub("", TEXT, count=1).encode("latin-1")


DRIFT = {
    "sixth chart": (_extra_chart, "expected 5 charts, found 6"),
    "missing band": (_drop_optimum_band, "expected 5 bands"),
    "gap between bands": (lambda: _replace("endValue: -13.65", "endValue: -13.7", 1), "not contiguous"),
    "unknown band colour": (lambda: _replace("#007FFF", "#123456"), "unrecognised band colour"),
    "legend relabelled": (lambda: _replace("Optimum condition", "Optimal condition"), "legend changed"),
    "attribution removed": (
        lambda: _replace("Thresholds established by the Puerto Rico", "Thresholds approved by the Puerto Rico"),
        "attribution is missing",
    ),
    "wrong parameter (62610 inverts direction)": (
        lambda: _replace("parameterCd=72019", "parameterCd=62610"),
        "page reads parameter 62610",
    ),
    "request site list changed": (
        lambda: _replace("sites=175934066364800,", "sites=175934066364801,", 1),
        "site lists disagree",
    ),
    "ladder contradicts chart beyond rounding": (
        lambda: _replace("value < 10.49", "value < 10.60", 1),
        "label ladder says",
    ),
    "reference link off the expected host": (
        lambda: _replace(
            "https://groundwaterwatch.usgs.gov/AWLSites.asp?S=175934066364800",
            "https://evil.example/AWLSites.asp?S=175934066364800",
        ),
        "unexpected reference host",
    ),
    "landing page instead of the document": (
        lambda: b"<html><body><h1>Caribbean-Florida Water Science Center</h1></body></html>",
        "attribution is missing",
    ),
    "cloudfront block page": (
        lambda: b"<HTML><HEAD><TITLE>ERROR: The request could not be satisfied</TITLE></HEAD>"
        b"<BODY><H1>403 ERROR</H1></BODY></HTML>",
        "attribution is missing",
    ),
    "empty body": (lambda: b"", "attribution is missing"),
}


@pytest.mark.parametrize("case", list(DRIFT))
def test_structural_drift_raises_instead_of_being_guessed_at(case):
    build, message = DRIFT[case]
    with pytest.raises(ab.BandPageError, match=re.escape(message)):
        ab.parse_page(build())


@pytest.mark.parametrize("end_tag", ["</script >", "</SCRIPT\n>", "</script foo=bar>"])
def test_an_end_tag_with_whitespace_or_attributes_still_closes_the_script(end_tag):
    """`</script >` is a valid HTML end tag. The first pattern matched only the literal
    `</script>` (CodeQL flagged it as a bad tag filter), so a harmless markup change would have
    failed the parse or merged two scripts. CONSTRUCTED from the capture: every end tag rewritten."""
    assert "</script>" in TEXT
    variant = TEXT.replace("</script>", end_tag).encode("latin-1")
    assert ab.parse_page(variant) == ab.parse_page(PAGE)


def test_two_chart_scripts_are_ambiguous_and_rejected():
    doubled = TEXT.replace("</body>", '<script>$("#wellBulletChart9").jqxBulletChart({ ranges: [] });</script></body>', 1)
    with pytest.raises(ab.BandPageError, match="expected one inline chart script"):
        ab.parse_page(doubled.encode("latin-1"))


# ── registry, freshness and readings ─────────────────────────────────────────
def test_current_registry_is_the_highest_revision_per_site():
    rows = [
        {"site_no": "1", "revision": 1, "registry_id": "a"},
        {"site_no": "1", "revision": 3, "registry_id": "c"},
        {"site_no": "1", "revision": 2, "registry_id": "b"},
        {"site_no": "2", "revision": 1, "registry_id": "d"},
    ]
    assert {k: v["registry_id"] for k, v in ab.current_registry(rows).items()} == {"1": "c", "2": "d"}


NOW = datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)


def _receipt(status, success_at):
    return {"last_status": status, "last_success_utc": success_at}


def test_freshness_matches_the_hydromet_plane_semantics():
    fresh = (NOW - timedelta(days=3)).isoformat()
    boundary = (NOW - timedelta(seconds=ab.MAX_AGE_SECONDS)).isoformat()
    old = (NOW - timedelta(seconds=ab.MAX_AGE_SECONDS + 1)).isoformat()
    assert ab.freshness(None, NOW)["state"] == "NEVER"
    assert ab.freshness(_receipt("PASS", None), NOW)["state"] == "NEVER"
    assert ab.freshness(_receipt("PASS", fresh), NOW)["state"] == "FRESH"
    assert ab.freshness(_receipt("PASS", boundary), NOW)["state"] == "FRESH"
    assert ab.freshness(_receipt("PASS", old), NOW)["state"] == "STALE"
    failed = ab.freshness(_receipt("FAIL", fresh), NOW)
    assert failed["state"] == "FAILED" and failed["age_seconds"] == pytest.approx(3 * 86400)


def _reading(site, value, day, *, rid=None, param="72019", unit="ft", prov=True, metric="groundwater_level"):
    return {
        "reading_id": rid or f"AYL_RDG_{day.replace('-', '')}_{site}_gw",
        "site_no": site, "metric": metric, "parameter_code": param, "value": value,
        "unit": unit, "observed_date": day, "provisional": prov, "source_ref": "t",
    }


def _write(path: Path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


SITE = "175947066130601"


def test_latest_reading_prefers_the_newest_and_the_continuous_value_on_a_tie(tmp_path):
    cont = lambda tok, v: _reading(  # noqa: E731
        SITE, v, "2026-11-08", rid=f"AYL_RDG_20261108_usgscv_{SITE}_72019_{tok}")
    _write(tmp_path / "groundwater_levels.jsonl", [
        _reading(SITE, 28.0, "2026-11-07"), _reading(SITE, 29.0, "2026-11-08"),
    ])
    _write(tmp_path / "usgs_continuous_readings.jsonl", [
        cont("20261108101500", 29.74), cont("20261108144500", 29.77), cont("20261108121500", 29.75),
    ])
    assert ab.latest_readings([SITE], tmp_path)[SITE]["value"] == 29.77
    # A newer calendar day in the daily file wins over an older continuous day.
    _write(tmp_path / "groundwater_levels.jsonl", [_reading(SITE, 30.1, "2026-11-09")])
    assert ab.latest_readings([SITE], tmp_path)[SITE]["value"] == 30.1


def test_latest_reading_never_lets_a_62610_or_wrong_unit_or_junk_row_become_a_class(tmp_path):
    """62610 (level ABOVE datum) runs opposite to 72019; admitting it would invert every class."""
    rows = [
        _reading(SITE, 5.0, "2026-11-09", param="62610"),
        _reading(SITE, 5.0, "2026-11-09", param=None),
        _reading(SITE, 5.0, "2026-11-09", unit="m"),
        _reading(SITE, 5.0, "2026-11-09", metric="streamflow"),
        _reading(SITE, "29.7", "2026-11-09"),
        _reading(SITE, True, "2026-11-09"),
        _reading(SITE, float("nan"), "2026-11-09"),
        _reading(SITE, 29.0, "2026-11-08"),
        _reading("999999999999999", 1.0, "2026-11-09"),
    ]
    _write(tmp_path / "groundwater_levels.jsonl", rows)
    got = ab.latest_readings([SITE], tmp_path)
    assert set(got) == {SITE} and got[SITE]["value"] == 29.0


def test_latest_reading_with_no_files_is_empty(tmp_path):
    assert ab.latest_readings([SITE], tmp_path) == {}


def _registry_row(page):
    well = next(w for w in page.wells if w.site_no == SITE)
    return {
        "site_no": SITE, "asset_id": f"USGSGW_{SITE}", "site_name_source": well.title, "revision": 1,
        "bands": [b.to_json() for b in well.bands], "reference_url": well.reference_url,
    }


def test_well_view_for_the_critical_well(page):
    view = ab.well_view(_registry_row(page), _reading(SITE, 29.76, "2026-11-08"), date(2026, 11, 8))
    assert view["class"] == "critical" and view["class_label"] == "Critical"
    assert view["margin_to_critical_ft"] == -6.33 and view["critical_onset_ft"] == 23.43
    assert view["reading"]["provisional"] is True and view["reading"]["stale"] is False
    assert view["axis_max_ft"] == 35.0 and len(view["bands"]) == 5


def test_well_view_marks_an_old_reading_stale_but_still_classifies(page):
    view = ab.well_view(_registry_row(page), _reading(SITE, 29.76, "2026-11-05"), date(2026, 11, 8))
    assert view["reading"]["stale"] is True and view["class"] == "critical"
    fresh_edge = ab.well_view(_registry_row(page), _reading(SITE, 29.76, "2026-11-06"), date(2026, 11, 8))
    assert fresh_edge["reading"]["stale"] is False  # two days old is the last fresh day


def test_well_view_without_a_reading_keeps_the_bands_and_claims_no_class(page):
    view = ab.well_view(_registry_row(page), None, date(2026, 11, 8))
    assert view["reading"] is None and view["class"] is None and view["margin_to_critical_ft"] is None
    assert len(view["bands"]) == 5
