"""Stage IV PR rainfall adapter: event identity, revision chaining and value shaping.

Zone values are the Aguada summary of the real 2026-10-09 1-day grid
(tests/fixtures/stage_iv_pr/); threshold cases are CONSTRUCTED and say so.
"""
from datetime import datetime, timezone

from aguayluz.hazard_adapters import stage_iv_qpe as adapter
from aguayluz.hazard_plane import HazardFamily, RecordKind, RecordStatus

DATA_TIME = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
MAN = "HYDROMET:stage_iv_pr:" + "a" * 32


def aguada_values(**over):
    base = dict(obs_mean=1.0643, obs_max=1.6062, normal_mean=0.2784,
                cell_count=9, normal_cell_count=9)
    base.update(over)
    return adapter.zone_values(**base)


def test_parse_data_time_reads_the_gdal_tag():
    assert adapter.parse_data_time("20261009T12:00:00") == DATA_TIME
    assert adapter.parse_data_time("2026-10-09T12:00:00") == DATA_TIME
    assert adapter.parse_data_time("") is None
    assert adapter.parse_data_time("yesterday") is None


def test_window_bounds_cover_the_named_number_of_12z_days():
    start, end = adapter.window_bounds("last7days", DATA_TIME)
    assert end == DATA_TIME and (end - start).days == 7
    start, _ = adapter.window_bounds("1day", DATA_TIME)
    assert start == datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def test_zone_values_derive_departure_and_percent_of_normal():
    values = aguada_values()
    assert values["obs_mean_in"] == 1.064 and values["obs_max_in"] == 1.606
    assert values["departure_mean_in"] == round(1.0643 - 0.2784, 3)
    assert values["pct_of_normal"] == round(1.0643 / 0.2784 * 100, 1)
    # no normal (ocean-only cells) or no observation → no derived values, never zero
    assert aguada_values(normal_mean=None)["pct_of_normal"] is None
    assert aguada_values(normal_mean=0.0)["departure_mean_in"] is None
    empty = aguada_values(obs_mean=None, obs_max=None, cell_count=0)
    assert empty["obs_mean_in"] is None and empty["pct_of_normal"] is None


def test_normalize_shapes_a_provisional_hydromet_observation():
    record = adapter.normalize(
        aguada_values(), MAN, window="1day", geoid="72003", municipio="Aguada",
        data_time=DATA_TIME, source_file="nws_precip_1day_20261009_pr.tif",
        method="raster_cell_centres_in_polygon",
        source_url="https://water.noaa.gov/resources/downloads/precip/stageIV/2026/10/09/nws_precip_1day_20261009_pr.tif",
    )
    assert record.canonical_event_id == "STAGEIV_QPE:1day:72003:20261009"
    assert record.family == HazardFamily.HYDROMETEOROLOGY
    assert record.record_kind == RecordKind.OBSERVATION
    assert record.status == RecordStatus.PROVISIONAL and record.provisional
    assert record.municipality_id == "72003"
    assert record.source_record_id == "nws_precip_1day_20261009_pr.tif#72003"
    assert record.raw_attributes["url"].endswith("nws_precip_1day_20261009_pr.tif")
    values = record.normalized_values
    assert values["window_days"] == 1 and values["data_date"] == "2026-10-09"
    assert values["values_digest"] == adapter.values_digest(aguada_values())


def test_zone_without_cells_stays_unresolved_and_unbound():
    record = adapter.normalize(
        aguada_values(obs_mean=None, obs_max=None, cell_count=0, normal_cell_count=0), MAN,
        window="1day", geoid="72003", municipio="Aguada", data_time=DATA_TIME,
        source_file="f.tif", method="no_raster_cell",
    )
    assert record.status == RecordStatus.UNRESOLVED
    assert record.municipality_id is None


def test_revision_ids_chain_through_the_superseded_record():
    event = adapter.canonical_event_id("1day", "72003", DATA_TIME.date())
    first = adapter.stable_record_id(event, aguada_values(), None)
    assert first == adapter.stable_record_id(event, aguada_values(), None)
    reprocessed = adapter.stable_record_id(event, aguada_values(obs_mean=1.2), first)
    assert reprocessed != first and reprocessed.startswith(f"{event}:REV:")
    # identical values re-published after a different revision get a new id
    assert adapter.stable_record_id(event, aguada_values(), reprocessed) != first


def test_heavy_rain_severity_thresholds():
    # CONSTRUCTED values around the documented thresholds.
    assert adapter.heavy_rain_severity(aguada_values()) is None
    assert adapter.heavy_rain_severity(aguada_values(obs_mean=3.0, obs_max=4.0)) == 2
    assert adapter.heavy_rain_severity(aguada_values(obs_mean=1.5, obs_max=6.0)) == 3
    assert adapter.heavy_rain_severity(aguada_values(obs_mean=7.0, obs_max=9.0)) == 3
    assert adapter.heavy_rain_severity({"obs_mean_in": None, "obs_max_in": None}) is None
