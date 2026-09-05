from scripts.federation_spatial_binding_v1_1 import bind_record


def test_no_match_stays_unresolved():
    row = {"asset_id": "WATER-1"}
    result = bind_record(
        row,
        id_field="asset_id",
        id_namespace="asset_id",
        canonical_index={},
        evidence_basis=["STABLE_ID"],
    )
    assert result["cardinality"] == "0:1"
    assert result["identity_state"] == "UNRESOLVED"


def test_name_only_is_rejected():
    row = {"asset_id": "WATER-1"}
    try:
        bind_record(
            row,
            id_field="asset_id",
            id_namespace="asset_id",
            canonical_index={"aguayluz-pr:asset_id:WATER-1": ["pr:water:1"]},
            evidence_basis=["NAME_ONLY"],
        )
    except ValueError as exc:
        assert "heuristic-only" in str(exc)
    else:
        raise AssertionError("name-only identity must fail closed")


def test_single_stable_match_is_provisional_not_certified():
    row = {"asset_id": "WATER-1"}
    result = bind_record(
        row,
        id_field="asset_id",
        id_namespace="asset_id",
        canonical_index={"aguayluz-pr:asset_id:WATER-1": ["pr:water:1"]},
        evidence_basis=["STABLE_ID"],
    )
    assert result["cardinality"] == "1:1"
    assert result["identity_state"] == "PROVISIONAL"
    assert result["canonical_ids"] == ["pr:water:1"]


def test_multiple_matches_preserve_one_to_many():
    row = {"asset_id": "WATER-1"}
    result = bind_record(
        row,
        id_field="asset_id",
        id_namespace="asset_id",
        canonical_index={
            "aguayluz-pr:asset_id:WATER-1": ["pr:water:1", "pr:water:2"]
        },
        evidence_basis=["STABLE_ID"],
    )
    assert result["cardinality"] == "1:N"
    assert result["identity_state"] == "UNRESOLVED"
