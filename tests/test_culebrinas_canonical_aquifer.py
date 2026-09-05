from operators.fetch_culebrinas_canonical_aquifer import (
    ANCHOR,
    LAYER_ID,
    SOURCE_NATIVE_EPSG,
    freeze_response,
    query_url,
)


def _response(global_id="{11111111-2222-3333-4444-555555555555}", n=1):
    features = []
    for i in range(n):
        features.append(
            {
                "attributes": {
                    "OBJECTID": 100 + i,
                    "DESCRIPCIO": "COASTAL EMBAYMENT AQUIFERS",
                    "GlobalID": global_id,
                },
                "geometry": {
                    "rings": [[[-67.2, 18.3], [-67.1, 18.3], [-67.1, 18.4], [-67.2, 18.3]]]
                },
            }
        )
    return {"features": features}


def test_query_contract_is_fixed_to_authoritative_layer_and_anchor():
    url = query_url()
    assert f"/{LAYER_ID}/query?" in url
    assert "geometry=-67.1512%2C18.394503" in url
    assert "outFields=OBJECTID%2CDESCRIPCIO%2CGlobalID" in url
    assert ANCHOR["id"] == "USGS-50148890"
    assert SOURCE_NATIVE_EPSG == 32161


def test_freeze_requires_exactly_one_feature():
    for n in (0, 2):
        try:
            freeze_response(_response(n=n))
        except ValueError as exc:
            assert str(exc) == f"sige_feature_cardinality:{n}"
        else:
            raise AssertionError("cardinality must fail closed")


def test_freeze_requires_globalid_and_geometry():
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


def test_freeze_emits_stable_globalid_hash_receipt():
    feature, receipt = freeze_response(_response())
    assert receipt["state"] == "FROZEN"
    assert receipt["canonical_geometry_bound"] is True
    assert receipt["proximity_identity_used"] is False
    assert len(receipt["feature_sha256"]) == 64
    assert feature["properties"]["source_globalid"] == receipt["global_id"]
    assert feature["properties"]["identity_state"] == "PASS_STABLE_GLOBALID"
