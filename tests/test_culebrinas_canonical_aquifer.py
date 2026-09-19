from operators.fetch_culebrinas_canonical_aquifer import (
    ANCHOR,
    EXPECTED_DESCRIPTIONS,
    LAYER_ID,
    SOURCE_NATIVE_EPSG,
    freeze_response,
    query_url,
)


def _response(global_id="{11111111-2222-3333-4444-555555555555}", n=1, description="INTERGRANULAR AQUIFERS"):
    features = []
    for i in range(n):
        features.append(
            {
                "attributes": {
                    "OBJECTID": 100 + i,
                    "DESCRIPCIO": description,
                    "GlobalID": global_id,
                },
                "geometry": {
                    "rings": [[[-67.21, 18.37], [-67.18, 18.37], [-67.18, 18.40], [-67.21, 18.37]]]
                },
            }
        )
    return {"features": features}


def test_query_contract_is_fixed_to_authoritative_layer_and_groundwater_anchor():
    url = query_url()
    assert f"/{LAYER_ID}/query?" in url
    assert "geometry=-67.1991533%2C18.3792523" in url
    assert "outFields=OBJECTID%2CDESCRIPCIO%2CGlobalID" in url
    assert ANCHOR["id"] == "USGS-182252067115800"
    assert ANCHOR["local_aquifer_code"] == "110RCBV"
    assert ANCHOR["local_aquifer_name"] == "Rio Culebrinas Valley Aquifer"
    assert SOURCE_NATIVE_EPSG == 32161


def test_freeze_requires_exactly_one_feature():
    for n in (0, 2):
        try:
            freeze_response(_response(n=n))
        except ValueError as exc:
            assert str(exc) == f"sige_feature_cardinality:{n}"
        else:
            raise AssertionError("cardinality must fail closed")


def test_freeze_requires_globalid_geometry_and_expected_aquifer_type():
    try:
        freeze_response(_response(global_id=""))
    except ValueError as exc:
        assert str(exc) == "sige_globalid_missing"
    else:
        raise AssertionError("missing GlobalID must fail closed")

    response = _response()
    response["features"][0]["geometry"] = None
    try:
        freeze_response(response)
    except ValueError as exc:
        assert str(exc) == "sige_geometry_missing"
    else:
        raise AssertionError("missing geometry must fail closed")

    try:
        freeze_response(_response(description="FISSURED AQUIFERS, INCLUDING KARST AND VOLCANIC AQUIFERS"))
    except ValueError as exc:
        assert str(exc).startswith("sige_unexpected_aquifer_type:")
    else:
        raise AssertionError("unexpected aquifer type must fail closed")


def test_expected_types_are_bounded():
    assert EXPECTED_DESCRIPTIONS == {
        "INTERGRANULAR AQUIFERS",
        "INTERGRANULAR UNIT OVERLYING FISSURED ROCK UNIT",
    }


def test_freeze_emits_stable_globalid_hash_receipt():
    feature, receipt = freeze_response(_response())
    assert receipt["state"] == "FROZEN"
    assert receipt["canonical_geometry_bound"] is True
    assert receipt["proximity_identity_used"] is False
    assert receipt["anchor"]["local_aquifer_code"] == "110RCBV"
    assert receipt["description"] == "INTERGRANULAR AQUIFERS"
    assert len(receipt["feature_sha256"]) == 64
    assert feature["properties"]["source_globalid"] == receipt["global_id"]
    assert feature["properties"]["identity_state"] == "PASS_STABLE_GLOBALID"
