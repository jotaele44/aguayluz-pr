"""Offline V03 manifestation version/revision classification tests."""
import pytest

from aguayluz.hydro_intelligence.manifestations import classify_manifestations

HOSTS = {"eia_923": {"www.eia.gov"}, "luma_bps_daily": {"lumapr.com"}}
A = "a" * 64
B = "b" * 64
U = "https://www.eia.gov/month.zip"
V = "https://www.eia.gov/mirror.zip"


def row(url, digest=A, source="eia_923"):
    return {"source_id": source, "artifact_url": url, "sha256": digest}


def classify(old, new):
    return classify_manifestations(old, new, allowed_hosts=HOSTS)


def test_new_and_repeat_revision_and_mirror_are_separate():
    old = [row(U)]
    records = classify(old, [row(U), row(U, B), row(V), row("https://www.eia.gov/new.zip", B)])
    assert [x["state"] for x in records] == [
        "REVIEW_CONFLICTING_CURRENT_URL",
        "REVIEW_CONFLICTING_CURRENT_URL",
        "SAME_BYTES_NEW_URL",
        "NEW_URL_NEW_BYTES",
    ]
    assert all(x["canonical_promotion"] is False for x in records)
    assert all(x["acquisition_state"] == "NOT_ASSERTED_BY_CLASSIFIER" for x in records)


def test_same_url_modified_bytes_has_distinct_revision():
    assert classify([row(U)], [row(U, B)])[0]["state"] == "SAME_URL_REVISED_BYTES"


def test_identical_url_and_hash_is_not_new_release():
    assert classify([row(U)], [row(U)])[0]["state"] == "BYTE_IDENTICAL_URL_REOBSERVED"


def test_same_bytes_new_url_not_conflated_with_original():
    assert classify([row(U)], [row(V)])[0]["state"] == "SAME_BYTES_NEW_URL"


def test_missing_history_does_not_imply_source_absence():
    assert classify([], [row(U)])[0]["state"] == "NEW_URL_NEW_BYTES"


def test_source_identity_scopes_digest_collisions():
    luma = row("https://lumapr.com/report.pdf", source="luma_bps_daily")
    assert classify([row(U)], [luma])[0]["state"] == "NEW_URL_NEW_BYTES"


@pytest.mark.parametrize("record", [
    row("http://www.eia.gov/a.zip"),
    row("https://evil.example/a.zip"),
    row(U, "not-a-digest"),
    {"source_id": "unregistered", "artifact_url": U, "sha256": A},
    {"source_id": "eia_923", "sha256": A},
])
def test_reject_invalid_manifestation(record):
    with pytest.raises(ValueError):
        classify([], [record])
