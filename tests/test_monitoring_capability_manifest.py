import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "monitoring_capabilities.json"
MONITORING_JS = ROOT / "dashboard" / "src" / "lib" / "monitoring.js"
CHART_JSX = ROOT / "dashboard" / "src" / "components" / "MonitoringCharts.jsx"
BACKEND = ROOT / "server" / "backend" / "app.py"

EXPECTED = {
    "reservoir_elevation": ("reservoir_elevation", "ft"),
    "reservoir_storage_pct": ("reservoir_storage_pct", "%"),
    "streamflow": ("streamflow", "ft3/s"),
    "gage_height": ("gage_height", "ft"),
    "groundwater_level": ("groundwater_level", "ft"),
    "coastal_water_level": ("coastal_water_level", "ft"),
}


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_declares_every_phase_zero_series_once():
    rows = _manifest()["series"]
    by_key = {row["key"]: row for row in rows}
    assert len(by_key) == len(rows)
    assert set(by_key) == set(EXPECTED)
    for key, (metric, unit) in EXPECTED.items():
        assert by_key[key]["metric"] == metric
        assert by_key[key]["unit"] == unit
        assert by_key[key]["api"].endswith(f"metric={metric}")


def test_manifest_fail_closed_policy_is_explicit():
    policy = _manifest()["policy"]
    assert policy["mixed_metric_charts"] == "prohibited"
    assert policy["mixed_unit_statistics"] == "prohibited"
    assert policy["unknown_series"] == "reject"
    assert policy["unknown_kind"] == "http_400"
    assert policy["unknown_metric"] == "http_400"
    assert policy["multi_metric_kind_requires_metric"] is True
    assert policy["series_identity"] == ["site_no", "metric", "parameter_code", "unit"]


def test_backend_contract_is_machine_readable():
    contract = _manifest()["api_contract"]
    assert contract["endpoint"] == "/readings"
    assert contract["implementation"] == "server/backend/app.py"
    assert set(contract["filters"]) == {"kind", "metric", "parameter_code", "site_no", "since", "until"}
    assert {"record_count", "site_count", "units", "parameter_codes", "mixed_units"} <= set(contract["response_metadata"])


def test_frontend_taxonomy_matches_manifest():
    source = MONITORING_JS.read_text(encoding="utf-8")
    for key, (metric, _unit) in EXPECTED.items():
        assert f"key: '{key}'" in source
        assert f"metric: '{metric}'" in source
    assert "Unsupported monitoring series" in source
    assert "reading.metric !== series.metric" in source


def test_chart_prohibits_cross_identity_statistics():
    source = CHART_JSX.read_text(encoding="utf-8")
    assert "mixedIdentity" in source
    assert "seriesIdentity" in source
    assert "if (mixedIdentity || chart.length < 5)" in source
    assert "No readings available for this exact metric and unit." in source


def test_backend_fails_closed_on_unknown_or_ambiguous_series():
    source = BACKEND.read_text(encoding="utf-8")
    assert '"unknown_reading_kind"' in source
    assert '"unknown_reading_metric"' in source
    assert '"metric_required"' in source
    assert '"mixed_units": len(units) > 1' in source
