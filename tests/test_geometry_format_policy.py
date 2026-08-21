from geometry_format_policy import assess_twkb_admission


def base(**overrides):
    values = dict(
        source_frozen=True,
        crs="EPSG:4326",
        coordinate_units="degrees",
        dimension="XYZ",
        xy_precision=6,
        z_precision=2,
        has_z=True,
        roundtrip_ok=True,
        type_conserved=True,
        null_empty_conserved=True,
        validity_conserved=True,
        vertex_count_conserved=True,
        application_tolerance=1e-6,
        observed_max_error=5e-7,
        canonical_copy_retained=True,
    )
    values.update(overrides)
    return values


def test_twkb_admits_only_as_noncanonical_derivative():
    result = assess_twkb_admission(**base())
    assert result.state == "NONCANONICAL"


def test_missing_crs_fails_closed():
    result = assess_twkb_admission(**base(crs=None))
    assert result.state == "BLOCKED"


def test_validity_change_is_hard_failure():
    result = assess_twkb_admission(**base(validity_conserved=False))
    assert result.state == "FAIL"


def test_vertex_count_change_is_hard_failure():
    result = assess_twkb_admission(**base(vertex_count_conserved=False))
    assert result.state == "FAIL"


def test_error_above_tolerance_fails():
    result = assess_twkb_admission(**base(observed_max_error=2e-6))
    assert result.state == "FAIL"
