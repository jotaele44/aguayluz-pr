import pytest
from integration.htr_context import HTRContextError, consume_htr_context


def base_row():
    return {
        "candidate_id": "htr_seed",
        "source_observation_id": "toponym:calle_luchetti_villalba",
        "hydro_entity_id": "hydro-name-family:antonio_lucchetti",
        "state": "CONTEXT_SUPPORTED",
        "identity_state": "DISTINCT_ENTITIES",
        "downstream_semantics": "CONTEXT_ONLY_NOT_IDENTITY",
        "relation_type": "ORTHOGRAPHIC_VARIANT",
        "pair_binding_state": "UNBOUND",
        "evidence": [],
    }


def test_name_recurrence_never_becomes_connectivity():
    out = consume_htr_context([base_row()])[0]
    assert out["canonical_identity"] is False
    assert out["connectivity_eligible"] is False
    assert out["connectivity_basis"] == "NONE_NAME_PROXIMITY_NOT_CONNECTIVITY"


def test_explicit_authoritative_pair_binding_can_be_connectivity_eligible():
    r = base_row()
    r.update(
        state="ADJUDICATED",
        relation_type="HYDRAULICALLY_CONNECTED_TO",
        pair_binding_state="BOUND_RELATION_NOT_IDENTITY",
        evidence=[{
            "relation_type": "HYDRAULICALLY_CONNECTED_TO",
            "binds_candidate_pair": True,
            "authoritative": True,
            "source_id": "authoritative:hydraulic-record",
        }],
    )
    out = consume_htr_context([r])[0]
    assert out["connectivity_eligible"] is True
    assert out["canonical_identity"] is False


def test_unbound_hydraulic_label_cannot_promote():
    r = base_row()
    r["relation_type"] = "HYDRAULICALLY_CONNECTED_TO"
    assert consume_htr_context([r])[0]["connectivity_eligible"] is False


def test_discovery_only_row_rejected():
    r = base_row()
    r["state"] = "CANDIDATE_NOT_IDENTITY"
    with pytest.raises(HTRContextError):
        consume_htr_context([r])


def test_unsupported_row_rejected():
    r = base_row()
    r["state"] = "UNSUPPORTED"
    r["identity_state"] = "UNRESOLVED"
    with pytest.raises(HTRContextError):
        consume_htr_context([r])
