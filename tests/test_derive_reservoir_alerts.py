import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from derive_reservoir_alerts import _percentile, build_alerts, merge  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "service_event.schema.json").read_text())

ASSETS = [
    {"asset_id": "USGS_50059000", "asset_name": "Lago Loiza At Damsite", "asset_type": "water",
     "asset_subtype": "reservoir", "municipality": "Trujillo Alto"},
]


def _readings(values, param="72379"):
    rows = []
    for i, v in enumerate(values):
        d = f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
        rows.append({
            "reading_id": f"AYL_RDG_{d.replace('-', '')}_50059000_{param}",
            "asset_id": "USGS_50059000", "site_no": "50059000",
            "metric": "reservoir_elevation", "parameter_code": param,
            "value": float(v), "unit": "ft", "observed_date": d, "provisional": True,
            "source_ref": "USGS NWIS Daily Values, site 50059000 parm 72379",
            "evidence_tier": "T1", "confidence": 75, "review_status": "accepted",
        })
    return rows


def test_percentile_interpolates():
    assert _percentile([0.0, 10.0], 50) == 5.0
    assert _percentile([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 10) == 1.0


def test_no_alert_when_latest_above_threshold():
    # 40 obs rising to a high latest value -> not low -> no alert.
    rows = _readings([100 + i for i in range(40)])
    assert build_alerts(rows, ASSETS, percentile=10, min_obs=30) == []


def test_alert_fires_when_latest_at_or_below_low_percentile():
    # 39 normal-high values + a final crash to the bottom -> alert.
    rows = _readings([130 + (i % 5) for i in range(39)] + [120.0])
    alerts = build_alerts(rows, ASSETS, percentile=10, min_obs=30)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["event_id"] == "AYL_EVT_20260212_50059000_lowlevel"
    assert a["event_type"] == "service_interruption"
    assert a["municipality"] == "Trujillo Alto"
    assert a["linked_asset_ids"] == ["USGS_50059000"]
    assert a["evidence_tier"] == "T2" and a["review_status"] == "needs_review"
    assert "NOT an official AAA operating level" in a["status_text"]


def test_skips_reservoirs_with_insufficient_history():
    rows = _readings([120.0] * 10)  # only 10 obs, min_obs=30
    assert build_alerts(rows, ASSETS, percentile=10, min_obs=30) == []


def test_invalid_values_do_not_count_and_conflicting_latest_ties_fail_closed():
    rows = _readings([130 + (i % 5) for i in range(29)] + [float("nan")])
    assert build_alerts(rows, ASSETS, percentile=10, min_obs=30) == []

    rows = _readings([130 + (i % 5) for i in range(39)] + [120.0])
    conflict = dict(rows[-1], reading_id="AYL_RDG_conflict", value=119.0)
    assert build_alerts(rows + [conflict], ASSETS, percentile=10, min_obs=30) == []


def test_alerts_validate_against_service_event_schema():
    import re

    rows = _readings([130 + (i % 5) for i in range(39)] + [118.0])
    alerts = build_alerts(rows, ASSETS, percentile=10, min_obs=30)
    req = set(SCHEMA["required"])
    allowed = set(SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in SCHEMA["properties"].items() if "enum" in v}
    pat = re.compile(SCHEMA["properties"]["event_id"]["pattern"])
    for a in alerts:
        assert req <= set(a) and set(a) <= allowed
        for k, choices in enums.items():
            if k in a:
                assert a[k] in choices
        assert pat.match(a["event_id"])


def test_merge_replaces_derived_preserves_others():
    existing = [
        {"event_id": "AYL_EVT_20250303_Guaynabo_x", "event_type": "outage",
         "source_ref": "https://github.com/.../outages_by_town.json"},
        {"event_id": "AYL_EVT_20260212_50059000_lowlevel", "event_type": "service_interruption",
         "source_ref": "AYL reservoir-alert p10 over USGS NWIS levels, site 50059000", "confidence": 1},
    ]
    new = build_alerts(_readings([130 + (i % 5) for i in range(39)] + [120.0]), ASSETS, 10, 30)
    out = {e["event_id"]: e for e in merge(existing, new)}
    assert "AYL_EVT_20250303_Guaynabo_x" in out  # non-derived preserved
    assert out["AYL_EVT_20260212_50059000_lowlevel"]["confidence"] == 60  # derived replaced
