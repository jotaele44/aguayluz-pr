from __future__ import annotations

import math

import pytest

from research.mycelial.foundation import (
    FungalOccurrenceRecord,
    append_fungal_occurrence,
    append_source,
    initialize_database,
    validate_fungal_occurrence,
)


def _record(**overrides) -> FungalOccurrenceRecord:
    values = {
        "occurrence_id": "finite-occurrence",
        "source_id": "finite-source",
        "source_record_id": "finite-row",
        "observed_at": "2026-08-03",
        "taxon_name": "Fungi",
        "latitude": 18.2,
        "longitude": -66.5,
        "evidence_tier": "T3",
        "review_status": "needs_review",
        "coordinate_confidence": "approximate",
        "coordinate_uncertainty_m": 25.0,
        "coordinate_datum": "WGS84",
        "coordinate_method": "reported",
        "taxonomic_confidence": "reported",
        "temporal_precision": "day",
        "evidence_refs": ("photo:sha256:finite",),
    }
    values.update(overrides)
    return FungalOccurrenceRecord(**values)


def _database(tmp_path):
    conn = initialize_database(tmp_path / "finite-values.sqlite")
    append_source(
        conn,
        source_id="finite-source",
        title="finite-number fixture",
        source_type="fixture",
        input_sha256="f" * 64,
    )
    return conn


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", math.nan),
        ("latitude", math.inf),
        ("latitude", -math.inf),
        ("longitude", math.nan),
        ("longitude", math.inf),
        ("longitude", -math.inf),
        ("coordinate_uncertainty_m", math.nan),
        ("coordinate_uncertainty_m", math.inf),
        ("coordinate_uncertainty_m", -math.inf),
    ],
)
def test_non_finite_coordinate_values_cannot_be_persisted(
    tmp_path,
    field,
    value,
):
    conn = _database(tmp_path)
    item = _record(**{field: value})

    violations = validate_fungal_occurrence(item)
    assert any("finite" in violation for violation in violations)

    with pytest.raises(ValueError, match="invalid_fungal_occurrence"):
        append_fungal_occurrence(conn, item)

    assert conn.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 0
