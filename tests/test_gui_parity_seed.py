"""A GUI fixture must remain schema-valid and must never delete a newer export."""

import json

from server.ingestion import gui_parity_teardown, seed_demo

from aguayluz.models import validate_against_schema


def configure(tmp_path, monkeypatch):
    for module in (seed_demo, gui_parity_teardown):
        monkeypatch.setattr(module, "OUTPUTS", tmp_path)
        monkeypatch.setattr(module, "REVIEW_QUEUE", tmp_path / "review_queue.json")
        monkeypatch.setattr(module, "SEED_MARKER", tmp_path / ".review_queue.seeded")
    return seed_demo.REVIEW_QUEUE, seed_demo.SEED_MARKER


def test_seed_validates_and_teardown_removes_only_its_bytes(tmp_path, monkeypatch):
    queue, marker = configure(tmp_path, monkeypatch)
    assert seed_demo.main() == 0
    validate_against_schema("review_queue", json.loads(queue.read_text()))
    original = queue.read_bytes()
    assert seed_demo.main() == 0
    assert queue.read_bytes() == original
    assert gui_parity_teardown.main() == 0
    assert not queue.exists()
    assert not marker.exists()
    assert gui_parity_teardown.main() == 0


def test_teardown_preserves_export_that_replaced_seed(tmp_path, monkeypatch):
    queue, marker = configure(tmp_path, monkeypatch)
    assert seed_demo.main() == 0
    queue.write_text('{"real":"export"}')
    assert gui_parity_teardown.main() == 1
    assert queue.read_text() == '{"real":"export"}'
    assert marker.exists()


def test_seed_and_teardown_preserve_preexisting_export(tmp_path, monkeypatch):
    queue, marker = configure(tmp_path, monkeypatch)
    queue.write_text('{"real":"export"}')
    assert seed_demo.main() == 0
    assert not marker.exists()
    assert gui_parity_teardown.main() == 0
    assert queue.read_text() == '{"real":"export"}'


def test_legacy_marker_is_not_deletion_authority(tmp_path, monkeypatch):
    queue, marker = configure(tmp_path, monkeypatch)
    queue.write_text('{"real":"export"}')
    marker.write_text('Written by old fixture script')
    assert gui_parity_teardown.main() == 1
    assert queue.exists()


def test_seed_does_not_replace_stale_marker(tmp_path, monkeypatch):
    queue, marker = configure(tmp_path, monkeypatch)
    marker.write_text('unverified previous ownership')
    assert seed_demo.main() == 1
    assert not queue.exists()
    assert marker.read_text() == 'unverified previous ownership'
