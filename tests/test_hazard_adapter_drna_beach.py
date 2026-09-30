from aguayluz.hazard_adapters.drna_beach import (
    ADVISORY_ALL_CLEAR,
    ADVISORY_BAV_EXCEEDANCE,
    ADVISORY_OTHER_WATER_QUALITY,
    canonical_event_id,
    normalize,
    stable_record_id,
)
from aguayluz.hazard_plane import HazardFamily, RecordKind, RecordStatus


def _base_row():
    return {
        "post_id": "notificacion-monitoria-de-playas-999",
        "post_url": "https://www.drna.pr.gov/example",
        "source_record_id": "notificacion-monitoria-de-playas-999:RW-26",
        "station_id": "RW-26",
        "beach_name": "Playita del Condado",
        "municipality_raw": "San Juan",
        "indicator": "Enterococci",
        "bav_value": 70,
        "bav_unit": "colonies/100 mL",
        "sample_date_start": "2026-03-09",
        "sample_date_end": "2026-03-09",
        "published_at": "2026-03-10",
        "advisory_state": ADVISORY_BAV_EXCEEDANCE,
        "advisory_reason_raw": "BAV exceedance",
        "title_raw": "Playita del Condado not suitable for bathers",
        "description_raw": None,
        "source_excerpt": "fixture",
    }


def test_bav_exceedance_normalizes_without_inventing_municipality_identity():
    row = _base_row()
    record = normalize(row, "manifest-drna-1")

    assert record.family == HazardFamily.WATER_HEALTH
    assert record.record_kind == RecordKind.ADVISORY
    assert record.status == RecordStatus.FINAL
    assert record.hazard_type == "BEACH_ENTEROCOCCI_BAV_EXCEEDANCE"
    assert record.municipality_id is None
    assert record.raw_attributes["municipality_raw"] == "San Juan"
    assert record.raw_attributes["station_id"] == "RW-26"
    assert record.geometry_precision == "NONE_UNLESS_INDEPENDENTLY_BOUND"


def test_other_water_quality_advisory_is_not_promoted_to_bav_exceedance():
    row = _base_row()
    row.update(
        {
            "source_record_id": "notificacion-monitoria-de-playas-999:NOTE:fixture",
            "station_id": None,
            "beach_name": "Playa Buyé",
            "municipality_raw": None,
            "indicator": None,
            "bav_value": None,
            "bav_unit": None,
            "advisory_state": ADVISORY_OTHER_WATER_QUALITY,
            "advisory_reason_raw": "Independent water-quality observation",
            "title_raw": "Playa Buyé: primary contact not recommended",
        }
    )
    record = normalize(row, "manifest-drna-2")

    assert record.hazard_type == "BEACH_WATER_QUALITY_ADVISORY_OTHER_OBSERVATION"
    assert record.raw_attributes["bav_value"] is None
    assert record.raw_attributes["advisory_state"] == ADVISORY_OTHER_WATER_QUALITY


def test_all_clear_is_preserved_as_distinct_advisory_state():
    row = _base_row()
    row.update(
        {
            "source_record_id": "notificacion-monitoria-de-playas-999:ALL_MONITORED",
            "station_id": None,
            "beach_name": None,
            "municipality_raw": None,
            "advisory_state": ADVISORY_ALL_CLEAR,
            "title_raw": "All monitored beaches suitable for bathers",
        }
    )
    record = normalize(row, "manifest-drna-3")

    assert record.hazard_type == "BEACH_MONITORING_ALL_CLEAR"
    assert record.raw_attributes["advisory_state"] == ADVISORY_ALL_CLEAR


def test_changed_source_content_keeps_event_identity_but_changes_revision_identity():
    row = _base_row()
    revised = {**row, "title_raw": "Revised source wording"}

    assert canonical_event_id(row) == canonical_event_id(revised)
    assert stable_record_id(row) != stable_record_id(revised)
