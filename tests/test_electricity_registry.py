"""Source-registry scientific negatives and full native contract, synthetic only."""
import hashlib
import json
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aguayluz.electricity.evidence import GeneratorClaim, SourceReceipt
from aguayluz.electricity.projection import electricity_projection
from aguayluz.electricity.registry import (
    RegistryConflict,
    RegistryQuery,
    SourceRegistry,
    source_entity_id,
)
from aguayluz.electricity.review import claim_identifier
from aguayluz.electricity.store import EvidenceStore

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def seed(root, changes=None):
    store = EvidenceStore(root)
    raw = b'SYNTHETIC REGISTRY INPUT; NO OFFICIAL OR OPERATIONAL EVIDENCE'
    digest = hashlib.sha256(raw).hexdigest()
    store.capture(raw, SourceReceipt(sha256=digest, byte_count=len(raw), retrieved_at=NOW,
                  source_url='https://www.eia.gov/electricity/data/eia860m/', authority='TEST ONLY',
                  schema_signature='TEST ONLY', license='UNRESOLVED'))
    base = dict(source_system='EIA-860M', plant_id='1', generator_id='01', valid_from=NOW,
                name='Same name', status='OP', nameplate_mw=10, receipt_sha256=digest)
    claims = [GeneratorClaim(**(base | change)) for change in (changes or [{}])]
    store.add_claims(claims)
    return store, claims


def test_empty_registry_is_unavailable_read_only(tmp_path):
    view = SourceRegistry(EvidenceStore(tmp_path / 'missing')).page(RegistryQuery())
    assert view['availability'] == 'UNAVAILABLE' and view['total'] == 0
    assert view['entities'] == [] and view['next_offset'] is None
    assert not (tmp_path / 'missing').exists()


def test_identity_separates_sources_literal_ids_and_names(tmp_path):
    store, claims = seed(tmp_path, [{}, {'generator_id': '1'}, {'plant_id': '2'},
                                    {'source_system': 'EIA-860'}, {'generator_id': 'a:b'}])
    entities = SourceRegistry(store).page(RegistryQuery())['entities']
    assert len(entities) == 5 and len({e['entity_id'] for e in entities}) == 5
    assert {e['generator_id'] for e in entities} == {'01', '1', 'a:b'}
    assert source_entity_id(claims[0], 'plant') != source_entity_id(claims[0], 'generator')
    renamed = claims[0].model_copy(update={'name': 'Different display name'})
    assert source_entity_id(renamed, 'generator') == source_entity_id(claims[0], 'generator')
    assert all(e['identity_basis'] == 'SOURCE_GENERATOR_IDENTIFIER' for e in entities)
    plants = SourceRegistry(store).page(RegistryQuery(entity_kind='plant'))['entities']
    assert len(plants) == 3
    assert all(e['identity_basis'] == 'GENERATOR_SOURCE_PLANT_ID_REFERENCE' for e in plants)
    assert not any('canonical_id' in e or 'connectivity' in e for e in entities)


def test_half_open_time_boundaries_no_silent_snapshot_closure(tmp_path):
    mid = NOW + timedelta(days=31)
    end = mid + timedelta(days=28)
    store, claims = seed(tmp_path, [{'valid_to': mid}, {'valid_from': mid, 'valid_to': end, 'nameplate_mw': 20},
                                   {'generator_id': 'open'}, {'generator_id': 'open', 'valid_from': mid, 'nameplate_mw': 99}])
    registry = SourceRegistry(store)
    for at, expected in [(NOW - timedelta(seconds=1), 0), (NOW, 2), (mid, 2), (end, 1)]:
        assert registry.page(RegistryQuery(at=at))['total'] == expected
    page = registry.page(RegistryQuery(at=mid))
    selected = {e['generator_id']: e for e in page['entities']}
    assert selected['01']['selected_claim_count'] == 1
    assert selected['01']['conflicting_pair_count'] == 0
    assert selected['open']['selected_claim_count'] == 2
    assert selected['open']['conflicting_pair_count'] == 1
    history = registry.history(source_entity_id(claims[0], 'generator'), RegistryQuery(at=mid, revision=registry.revision))
    assert [c['selected_at'] for c in history['claims']] == [False, True]
    assert all(not c['conflicting_claim_ids'] for c in history['claims'])
    assert SourceRegistry(store).page(RegistryQuery(at=mid.astimezone(timezone(timedelta(hours=-4)))))['entities'] == page['entities']


def test_overlap_equal_assertions_and_different_generators_are_not_false_conflicts(tmp_path):
    store, claims = seed(tmp_path, [{}, {'valid_from': NOW + timedelta(days=1)},
                                    {'nameplate_mw': 12}, {'generator_id': '1', 'nameplate_mw': 99}])
    registry = SourceRegistry(store)
    identifier = source_entity_id(claims[0], 'generator')
    history = registry.history(identifier, RegistryQuery(revision=registry.revision))
    assert history['entity']['conflicting_pair_count'] == 2
    assert sum(len(c['conflicting_claim_ids']) for c in history['claims']) == 4
    assert {c['claim_id'] for c in history['claims']} == {claim_identifier(c.model_dump(mode='json')) for c in claims[:3]}
    plant = registry.page(RegistryQuery(entity_kind='plant'))['entities'][0]
    assert plant['selected_claim_count'] == 4 and plant['conflicting_pair_count'] == 2
    assert 'capacity_mw' not in plant  # No aggregate or inferred available capacity.
    assert history['sources'][0]['license'] == 'UNRESOLVED'


@pytest.mark.parametrize('field,value', [('name', 'Other'), ('status', 'RE'), ('nameplate_mw', 50)])
def test_each_source_claim_disagreement_stays_unresolved(tmp_path, field, value):
    store, _ = seed(tmp_path, [{}, {field: value}])
    view = SourceRegistry(store).page(RegistryQuery())
    assert view['entities'][0]['conflicting_pair_count'] == 1
    assert view['canonical_promotion'] == 'BLOCKED'


def test_stable_list_and_history_pagination_full_denominator_sql_and_restore(tmp_path):
    store, claims = seed(tmp_path / 'live', [{'generator_id': f'{i:02}'} for i in range(7)] + [{'nameplate_mw': 12}])
    registry = SourceRegistry(store)
    found, offset = [], 0
    while True:
        page = registry.page(RegistryQuery(limit=2, offset=offset, revision=registry.revision))
        found.extend(page['entities'])
        if page['next_offset'] is None:
            break
        offset = page['next_offset']
    with sqlite3.connect(store.root / 'ledger.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM claims').fetchone()[0] == 8
        identities = db.execute("SELECT count(DISTINCT json_extract(payload,'$.generator_id')) FROM claims").fetchone()[0]
    assert len(found) == identities == 7 and len({e['entity_id'] for e in found}) == identities
    # Separate plant history pagination covers every exact claim including the overlap.
    plant_id = source_entity_id(claims[0], 'plant')
    history_ids = []
    for offset in range(0, 8, 3):
        detail = registry.history(plant_id, RegistryQuery(limit=3, offset=offset, revision=registry.revision))
        history_ids.extend(c['claim_id'] for c in detail['claims'])
    assert set(history_ids) == {claim_identifier(c.model_dump(mode='json')) for c in claims}
    # Quiesced SQLite backup plus immutable raw bytes. Later live writes survive.
    backup = tmp_path / 'backup'
    backup.mkdir()
    with sqlite3.connect(store.root / 'ledger.sqlite3') as live, sqlite3.connect(backup / 'ledger.sqlite3') as saved:
        live.backup(saved)
    shutil.copytree(store.root / 'raw', backup / 'raw')
    store.add_claims([claims[0].model_copy(update={'generator_id': 'later'})])
    restored = SourceRegistry(EvidenceStore(backup))
    assert restored.page(RegistryQuery()) == registry.page(RegistryQuery())
    assert restored.history(plant_id, RegistryQuery(revision=registry.revision)) == registry.history(plant_id, RegistryQuery(revision=registry.revision))
    assert SourceRegistry(store).page(RegistryQuery())['total'] == 8
    assert restored.revision == electricity_projection(EvidenceStore(backup))['revision']


def test_revision_rejects_cross_page_or_detail_changes(tmp_path):
    store, claims = seed(tmp_path)
    old = SourceRegistry(store)
    store.add_claims([claims[0].model_copy(update={'generator_id': '2'})])
    with pytest.raises(RegistryConflict):
        SourceRegistry(store, old.revision)
    new = SourceRegistry(store)
    with pytest.raises(RegistryConflict):
        new.page(RegistryQuery(revision=old.revision))
    with pytest.raises(RegistryConflict):
        new.history(source_entity_id(claims[0], 'generator'), RegistryQuery())
    with pytest.raises(KeyError):
        new.history('a' * 64, RegistryQuery(revision=new.revision))


def test_literal_search_is_filter_only_no_alias_or_case_normalization(tmp_path):
    store, _ = seed(tmp_path, [{}, {'generator_id': '1'}, {'plant_id': '2'}])
    registry = SourceRegistry(store)
    assert registry.page(RegistryQuery(search='same'))['total'] == 0
    assert registry.page(RegistryQuery(search='Same'))['total'] == 3
    assert registry.page(RegistryQuery(plant_id='1', search='01'))['total'] == 1
    assert registry.page(RegistryQuery(source_system='EIA-923'))['total'] == 0


@pytest.mark.parametrize('updates', [{'at': '2026-01-01T00:00:00'}, {'offset': 1}, {'limit': 101},
                                    {'plant_id': '01'}, {'source_system': 'OSM'}, {'search': '\x00'},
                                    {'entity_kind': 'dam'}, {'revision': 'bad'}, {'unknown': True}])
def test_query_negatives(updates):
    with pytest.raises(ValidationError):
        RegistryQuery(**updates)


def test_schema_list_history_and_bounded_performance(tmp_path):
    # Predeclared diagnostic budget: 1,000 claims / 200 entities under two seconds
    # for list + a 5-version history after raw verification, on this runner only.
    store, claims = seed(tmp_path, [{'generator_id': str(i % 200), 'valid_from': NOW + timedelta(days=i // 200)} for i in range(1000)])
    started = time.monotonic()
    registry = SourceRegistry(store)
    page = registry.page(RegistryQuery())
    history = registry.history(source_entity_id(claims[0], 'generator'), RegistryQuery(revision=registry.revision))
    elapsed = time.monotonic() - started
    assert page['total'] == 200 and history['total'] == 5
    assert elapsed < 2
    schema = json.loads(Path('schemas/electricity_registry.v1.schema.json').read_text())
    for value in (page, history):
        jsonschema.validate(value, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(page | {'canonical_promotion': 'ALLOWED'}, schema)


def test_api_public_reads_strict_inputs_stale_revision_and_corruption(tmp_path, monkeypatch):
    from server.backend import electricity_api
    from server.backend.app import app
    store, claims = seed(tmp_path)
    monkeypatch.setattr(electricity_api, '_store', lambda: store)
    monkeypatch.delenv('API_SECRET_KEY', raising=False)
    client = TestClient(app)
    path = '/electricity/v1/registry'
    before = electricity_projection(store)
    page = client.get(path).json()
    identifier = page['entities'][0]['entity_id']
    revision = page['source_revision']
    assert client.get(path + f'/{identifier}', params={'revision': revision}).status_code == 200
    assert client.get(path + '/' + 'f' * 64, params={'revision': revision}).status_code == 404
    assert client.get(path + '/bad', params={'revision': revision}).status_code == 422
    assert client.get(path + f'/{identifier}').status_code == 422
    assert client.post(path, json={'canonical': True}).status_code == 405
    for suffix in ('?limit=0', '?offset=1', '?limit=1&limit=2', '?foo=bar', '?at=2026-01-01', '?plant_id=01'):
        assert client.get(path + suffix).status_code == 422
    assert client.get(path + f'/{identifier}?revision={revision}&entity_kind=plant').status_code == 422
    after = electricity_projection(store)
    assert {k: v for k, v in after.items() if k != 'generated_at'} == {k: v for k, v in before.items() if k != 'generated_at'}
    store.add_claims([claims[0].model_copy(update={'generator_id': 'new'})])
    assert client.get(path, params={'revision': revision}).status_code == 409
    assert client.get(path + f'/{identifier}', params={'revision': revision}).status_code == 409
    (store.root / 'raw' / claims[0].receipt_sha256).write_bytes(b'corrupt')
    failure = client.get(path)
    assert failure.status_code == 503 and failure.json()['detail'] == 'ELECTRICITY_REGISTRY_INTEGRITY_FAILED'
