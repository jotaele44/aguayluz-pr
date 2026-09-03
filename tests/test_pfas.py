from aguayluz.environmental_exposure import _PFAS


def _measurement(**overrides):
    row = {
        "analyte": "PFOS",
        "evidence_state": "MEASURED",
        "source_record_id": "EPA_UCMR5_FINAL_202608",
        "sample_date": "2023-09-20",
        "result_sign": "=",
        "result_value": 0.0467,
        "result_unit": "ug/L",
    }
    row.update(overrides)
    return row


def _rule(**overrides):
    row = {
        "rule_id": "EPA_NPDWR_2024_PFOS_MCL",
        "analyte": "PFOS",
        "value": 4.0,
        "unit": "ng/L",
        "rule_type": "MCL",
        "legal_state": "IN_FORCE",
        "effective_from": "2024-06-25",
        "compliance_from": "2029-04-26",
        "source_record_id": "epa",
    }
    row.update(overrides)
    return row


def test_unit_normalization():
    assert _PFAS.normalize_ng_l(0.0467, "ug/L") == 46.7
    assert _PFAS.normalize_ng_l(4.0, "ng/L") == 4.0


def test_nondetect_must_not_synthesize_value():
    row = _measurement(result_sign="<", result_value=0.001)
    try:
        _PFAS.validate_measurement(row)
    except ValueError as exc:
        assert "must not synthesize" in str(exc)
    else:
        raise AssertionError("non-detect synthetic value was accepted")


def test_discovery_only_cannot_promote_attribution():
    row = {
        "evidence_state": "ATTRIBUTED",
        "identity_cardinality": "1:1",
        "spatial_state": "FULLY_WITHIN",
        "evidence_classes": ["PROXIMITY_ONLY"],
        "source_record_ids": ["candidate"],
        "contradictions": [],
    }
    try:
        _PFAS.validate_binding(row)
    except ValueError as exc:
        assert "discovery-only" in str(exc)
    else:
        raise AssertionError("proximity-only attribution was accepted")


def test_proposed_rescission_does_not_erase_current_rule():
    rule = _rule(
        rule_id="EPA_NPDWR_2024_PFHXS_MCL",
        analyte="PFHxS",
        value=10.0,
        legal_state="IN_FORCE_PROPOSED_RESCISSION",
    )
    assert _PFAS.current_rule([rule], "PFHxS", "2026-09-03") == rule


def test_occurrence_measurement_never_becomes_compliance_finding():
    rule = _rule()
    result = _PFAS.compare_measurement_to_rule(
        _measurement(), rule, as_of="2026-09-03"
    )
    assert result["state"] == "ABOVE_REFERENCE"
    assert result["observed_ng_l"] == 46.7
    assert result["compliance_finding"] is False


def test_missing_source_hash_keeps_certification_open():
    result = _PFAS.certification_report(
        source_manifestations=[{
            "source_record_id": "s1",
            "url": "https://example.test/source",
            "retrieved_utc": "2026-09-03T17:00:00Z",
            "byte_sha256": None,
        }],
        measurements=[_measurement(source_record_id="s1")],
        bindings=[],
        unresolved_material=[],
    )
    assert result["structural_state"] == "PASS"
    assert result["certification_state"] == "OPEN"
    assert result["unresolved_material_count"] == 1
