"""Tests for the alert, coverage, and system read endpoints.

The alert layer (docs/ALERT_SYSTEM.md) is exported to the Hub but had no read path
of its own; these endpoints are that path. Coverage matters as much as the list:
the corpus is dominated by one module and by geometry-less assets, and the UI is
only honest if those show up as numbers. Skipped when fastapi/httpx aren't installed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.main as backend  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

ALERTS = [
    {
        "alert_id": "AYL_ALR_20260101_sdwis_a", "module_id": "CONTAMINATION",
        "status": "active", "review_status": "needs_review", "evidence_tier": "T1",
        "severity": 2, "start_at": "2026-01-01T00:00:00Z", "gap_status": "none",
        "source_title": "Health-based violation @ PONCE", "asset_name": "PONCE PWS",
        "municipalities": ["Ponce"], "latitude": 18.01, "longitude": -66.61,
    },
    {
        "alert_id": "AYL_ALR_20260202_seismic_b", "module_id": "SEISMIC_GEO",
        "status": "active", "review_status": "accepted", "evidence_tier": "T1",
        "severity": 4, "start_at": "2026-02-02T00:00:00Z", "gap_status": "none",
        "source_title": "M5.1 earthquake SW of Guánica", "asset_name": None,
        "municipalities": ["Guánica"], "latitude": 17.9, "longitude": -66.9,
    },
    {
        "alert_id": "AYL_ALR_20260303_weather_c", "module_id": "WEATHER_HAZARD",
        "status": "closed", "review_status": "accepted", "evidence_tier": "T2",
        "severity": 4, "start_at": "2026-03-03T00:00:00Z", "gap_status": "minor",
        "source_title": "Flood warning — Río Grande de Loíza", "asset_name": None,
        "municipalities": ["Loíza"],  # no coordinates -> not a map feature
    },
    {
        # A `draft` severity-4 alert. The exporter ships this to the Hub as critical
        # (its rule is "not closed/rejected"), so the read layer must agree — an
        # allowlist of active/validated here would under-report it.
        "alert_id": "AYL_ALR_20260404_dam_d", "module_id": "DAM_SAFETY",
        "status": "draft", "review_status": "needs_review", "evidence_tier": "T4",
        "severity": 4, "start_at": "2026-04-04T00:00:00Z", "gap_status": "blocking",
        "source_title": "Draft dam-safety advisory", "asset_name": "Carraízo",
        "municipalities": ["Trujillo Alto"],
    },
]

ASSETS = [
    {"asset_id": "A1", "asset_type": "water", "asset_subtype": "reservoir",
     "municipality": "Ponce", "review_status": "accepted", "evidence_tier": "T1",
     "lat": 18.0, "lon": -66.6},
    {"asset_id": "A2", "asset_type": "water", "asset_subtype": "canal_feature",
     "municipality": "Puerto Rico", "review_status": "needs_review", "evidence_tier": "T2"},
    {"asset_id": "A3", "asset_type": "power", "asset_subtype": "Substation",
     "municipality": "unknown", "review_status": "accepted", "evidence_tier": "T1",
     "lat": 18.4, "lon": -66.1},
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(backend, "_alerts", ALERTS)
    monkeypatch.setattr(backend, "_assets", ASSETS)
    monkeypatch.setattr(backend, "_alert_edges", [
        {"edge_id": "E1", "alert_id": "AYL_ALR_20260101_sdwis_a",
         "from_asset_id": "A1", "to_asset_id": "A3"},
    ])
    monkeypatch.setattr(backend, "_alert_gaps", [{"gap_id": "GAP-003"}])
    with TestClient(backend.app) as c:
        yield c


# ── /alerts ──────────────────────────────────────────────────────────────────

def test_alerts_are_paged_and_recent_first(client):
    body = client.get("/alerts").json()
    assert body["total"] == 4
    assert [a["alert_id"] for a in body["items"]] == [
        "AYL_ALR_20260404_dam_d",
        "AYL_ALR_20260303_weather_c",
        "AYL_ALR_20260202_seismic_b",
        "AYL_ALR_20260101_sdwis_a",
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("module_id=SEISMIC_GEO", ["AYL_ALR_20260202_seismic_b"]),
        ("status=closed", ["AYL_ALR_20260303_weather_c"]),
        ("status=draft", ["AYL_ALR_20260404_dam_d"]),
        ("review_status=needs_review", ["AYL_ALR_20260404_dam_d", "AYL_ALR_20260101_sdwis_a"]),
        ("tier=T2", ["AYL_ALR_20260303_weather_c"]),
        ("municipio=ponce", ["AYL_ALR_20260101_sdwis_a"]),
        ("q=earthquake", ["AYL_ALR_20260202_seismic_b"]),
    ],
)
def test_alert_filters(client, query, expected):
    body = client.get(f"/alerts?{query}").json()
    assert [a["alert_id"] for a in body["items"]] == expected


def test_severity_min_and_critical_only_differ(client):
    """severity>=4 includes the closed alert; critical drops it but keeps the draft.

    The exporter's rule is a blocklist ("not closed/rejected"), so a draft alert over
    the threshold is critical. Matching it is what keeps this count equal to the Hub's.
    """
    by_severity = client.get("/alerts?severity_min=4").json()
    assert by_severity["total"] == 3

    critical = client.get("/alerts?critical_only=true").json()
    assert [a["alert_id"] for a in critical["items"]] == [
        "AYL_ALR_20260404_dam_d",      # draft, severity 4 -> still actionable
        "AYL_ALR_20260202_seismic_b",
    ]


def test_explicit_limit_and_offset(client):
    body = client.get("/alerts?limit=1&offset=1").json()
    assert body["total"] == 4
    assert body["offset"] == 1
    assert [a["alert_id"] for a in body["items"]] == ["AYL_ALR_20260303_weather_c"]


def test_alert_detail_and_missing(client):
    body = client.get("/alerts/AYL_ALR_20260202_seismic_b").json()
    assert body["module_id"] == "SEISMIC_GEO"
    assert body["is_critical"] is True
    assert client.get("/alerts/NOPE").status_code == 404


def test_static_alert_routes_are_not_shadowed_by_the_id_route(client):
    """/alerts/facets, /dependencies and /gaps must not resolve as an alert_id."""
    assert client.get("/alerts/facets").status_code == 200
    assert client.get("/alerts/dependencies").status_code == 200
    assert client.get("/alerts/gaps").status_code == 200


# ── facets / geojson / sidecars ──────────────────────────────────────────────

def test_facets_are_derived_from_the_corpus(client):
    f = client.get("/alerts/facets").json()
    assert f["total"] == 4
    assert f["active"] == 3          # everything except the closed one
    assert f["critical"] == 2        # the seismic alert and the severity-4 draft
    assert f["mapped"] == 2
    assert f["module_id"] == {
        "CONTAMINATION": 1, "SEISMIC_GEO": 1, "WEATHER_HAZARD": 1, "DAM_SAFETY": 1,
    }
    assert f["evidence_tier"] == {"T1": 2, "T2": 1, "T4": 1}


def test_geojson_skips_coordinate_less_alerts(client):
    body = client.get("/alerts.geojson").json()
    assert len(body["features"]) == 2
    assert body["features"][0]["geometry"]["coordinates"] == [-66.61, 18.01]

    critical = client.get("/alerts.geojson?critical_only=true").json()
    assert [f["properties"]["alert_id"] for f in critical["features"]] == [
        "AYL_ALR_20260202_seismic_b"
    ]


def test_dependency_edges_scope_by_alert_and_asset(client):
    assert len(client.get("/alerts/dependencies").json()) == 1
    assert client.get("/alerts/dependencies?alert_id=AYL_ALR_20260101_sdwis_a").json()
    assert client.get("/alerts/dependencies?alert_id=missing").json() == []
    assert client.get("/alerts/dependencies?asset_id=A3").json()


def test_health_reports_alert_counts(client):
    counts = client.get("/health").json()["counts"]
    assert counts["alerts"] == 4
    assert counts["alerts_active"] == 3
    assert counts["alerts_critical"] == 2


# ── coverage ─────────────────────────────────────────────────────────────────

def test_coverage_counts_unmapped_and_unjoined_assets(client):
    cov = client.get("/summary/coverage").json()["assets"]
    assert cov["total"] == 3
    assert cov["mapped"] == 2
    assert cov["unmapped"] == 1
    # "Puerto Rico" and "unknown" are placeholders, not municipality joins.
    assert cov["municipio_joined"] == 1
    assert cov["municipio_unjoined"] == 2


def test_coverage_exposes_subtype_facets(client):
    cov = client.get("/summary/coverage").json()
    assert cov["asset_subtype"] == {"reservoir": 1, "canal_feature": 1, "Substation": 1}
    assert cov["unmapped_by_subtype"] == {"canal_feature": 1}
    assert cov["review_status"] == {"accepted": 2, "needs_review": 1}


# ── system status ────────────────────────────────────────────────────────────

def test_system_status_supersets_auth_status(client, monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    body = client.get("/system/status").json()
    auth = client.get("/auth/status").json()

    assert auth.items() <= body.items()
    assert body["slack_configured"] is False
    assert "utility_assets" in body["corpora"]
    assert "federation_manifest" in body["artifacts"]


def test_email_configuration_requires_smtp_host(client, monkeypatch):
    monkeypatch.setenv("NOTIFY_EMAIL_FROM", "alerts@example.test")
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "operator@example.test")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert client.get("/auth/status").json()["email_configured"] is False

    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    assert client.get("/auth/status").json()["email_configured"] is True


def test_notify_reports_confirmed_full_success(client, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.test/slack")
    monkeypatch.setenv("NTFY_TOPIC", "operator-topic")
    monkeypatch.delenv("NOTIFY_EMAIL_FROM", raising=False)
    monkeypatch.setattr(backend, "_send_slack", lambda *_: None)
    monkeypatch.setattr(backend, "_send_ntfy", lambda *_: None)

    body = client.post("/notify", json={"title": "Status", "message": "All clear"}).json()

    assert body == {
        "ok": True,
        "channels_active": True,
        "errors": [],
        "attempted_channels": ["slack", "ntfy"],
        "succeeded_channels": ["slack", "ntfy"],
        "failed_channels": [],
    }


def test_notify_reports_partial_delivery(client, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.test/slack")
    monkeypatch.setenv("NTFY_TOPIC", "operator-topic")
    monkeypatch.delenv("NOTIFY_EMAIL_FROM", raising=False)
    monkeypatch.setattr(backend, "_send_slack", lambda *_: None)

    def fail_ntfy(*_):
        raise RuntimeError("push rejected with secret transport details")

    monkeypatch.setattr(backend, "_send_ntfy", fail_ntfy)
    body = client.post("/notify", json={"message": "Check system"}).json()

    assert body["ok"] is False
    assert body["attempted_channels"] == ["slack", "ntfy"]
    assert body["succeeded_channels"] == ["slack"]
    assert body["failed_channels"] == [{"channel": "ntfy", "error": "delivery failed"}]
    assert body["errors"] == ["ntfy: delivery failed"]
    assert "secret transport details" not in str(body)


def test_notify_reports_failed_only_delivery(client, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.test/slack")
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.delenv("NOTIFY_EMAIL_FROM", raising=False)

    def fail_slack(*_):
        raise RuntimeError("webhook unavailable at internal.example.test")

    monkeypatch.setattr(backend, "_send_slack", fail_slack)
    body = client.post("/notify", json={"message": "Check system"}).json()

    assert body["ok"] is False
    assert body["channels_active"] is True
    assert body["attempted_channels"] == ["slack"]
    assert body["succeeded_channels"] == []
    assert body["failed_channels"] == [{"channel": "slack", "error": "delivery failed"}]
    assert "internal.example.test" not in str(body)


def test_system_status_reports_missing_artifacts_without_failing(client):
    artifacts = client.get("/system/status").json()["artifacts"]
    for entry in artifacts.values():
        assert "present" in entry
        assert entry["path"]  # repo-relative, never absolute
        if entry["present"]:
            assert entry["modified_at"]


def test_readings_kinds_match_registered_producers(client, tmp_path, monkeypatch):
    """A kind with no file yields an empty series; an unregistered kind yields []."""
    assert set(backend.READINGS_FILES) == {
        "reservoir", "groundwater", "coastal", "neon",
        "usgs_field_measurements", "usgs_peaks", "drought", "precipitation",
    }
    # Point at a path that doesn't exist rather than relying on the checkout's real
    # data/coastal_levels.jsonl happening to be empty — scripts/ingest_noaa_tides.py
    # populates that file locally (it's gitignored, so this is a real, expected dev
    # state, not something the test should assume away).
    monkeypatch.setitem(backend.READINGS_FILES, "coastal", tmp_path / "no_such_coastal_file.jsonl")
    assert client.get("/readings?kind=coastal").json() == []
    assert client.get("/readings?kind=generation").json() == []


def test_readings_since_filter_reads_observed_date(client, tmp_path, monkeypatch):
    """`since` must parse the field the producers actually write.

    Every reading ingest emits `observed_date`; filtering only on
    timestamp/date/time parsed nothing, so the 7d/30d/90d ranges silently returned an
    empty series for all three feeds while `all` looked fine.
    """
    series = tmp_path / "coastal_levels.jsonl"
    series.write_text(
        '{"site_no": "9755371", "metric": "coastal_water_level", "value": 1.1,'
        ' "observed_date": "2026-01-01"}\n'
        '{"site_no": "9755371", "metric": "coastal_water_level", "value": 1.4,'
        ' "observed_date": "2026-06-01"}\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(backend.READINGS_FILES, "coastal", series)

    assert len(client.get("/readings?kind=coastal").json()) == 2
    recent = client.get("/readings?kind=coastal&since=2026-03-01T00:00:00Z").json()
    assert [r["observed_date"] for r in recent] == ["2026-06-01"]


@pytest.mark.parametrize(
    "value",
    ["2026-03-01T00:00:00Z", "2026-03-01T00:00:00z", "2026-03-01T00:00:00+00:00"],
)
def test_parse_dt_accepts_zulu_timestamps(value):
    """`Z` must parse on every supported Python, not just 3.11+.

    datetime.fromisoformat only learned the trailing `Z` in 3.11. On 3.10 it raised,
    _parse_dt returned None, and every caller reads None as "no bound" — so `?since=`
    was silently ignored and the dashboard's 7d/30d/90d ranges returned everything.
    The dashboard sends this exact shape via `new Date().toISOString()`.
    """
    parsed = backend._parse_dt(value)
    assert parsed is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.year == 2026 and parsed.month == 3 and parsed.day == 1
