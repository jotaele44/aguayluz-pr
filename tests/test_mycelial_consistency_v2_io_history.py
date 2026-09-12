"""S1/S2 guards: synthetic inputs and explicitly simulated resource failures."""
from __future__ import annotations

import copy
import importlib.util
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'history_fixture', ROOT / 'tests/test_mycelial_consistency_v2_review201.py')
assert SPEC is not None and SPEC.loader is not None
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
M = R.M


def no_authority(result):
    assert all(result[k] is False for k in R.FLAGS)
    for row in result.get('rows', []):
        assert all(row[k] is False for k in R.FLAGS)
    if 'input_rows' in result:
        assert result['input_rows'] == result['passed_checked_constraints'] + result['failed_rows']


@pytest.mark.parametrize('key', [
    '/UTC', '../UTC', './UTC', 'America//Puerto_Rico', 'America/../UTC', 'UTC/',
    'UTC\\hidden', 'UTC\x00hidden', ' UTC', 'UTC ', 'UTC\n', '\u00e9urope/Paris',
    '.', '..', 'A'*65, '/'.join(['A'*64]*4), 'A'*300,
])
def test_bad_key_rejected_before_lookup(key, monkeypatch):
    calls = []
    def forbidden(value):
        calls.append(value)
        raise AssertionError('Invalid key reached lookup')
    monkeypatch.setattr(M, '_read_zone_bytes', forbidden)
    row = R.fixture()[4]
    row['timezone'] = key
    before = copy.deepcopy(row)
    result = R.call(row)
    assert result['state'] == 'FAIL'
    assert 'TIMEZONE_KEY_INVALID' in result['reason_codes']
    assert calls == [] and row == before
    no_authority(result)


@pytest.mark.parametrize('exc,code', [
    (OSError, 'TIMEZONE_DATA_ACCESS_FAILURE'),
    (IsADirectoryError, 'TIMEZONE_DATA_ACCESS_FAILURE'),
    (NotADirectoryError, 'TIMEZONE_DATA_ACCESS_FAILURE'),
    (PermissionError, 'TIMEZONE_DATA_ACCESS_FAILURE'),
    (FileNotFoundError, 'TIMEZONE_DATA_ACCESS_FAILURE'),
    (ValueError, 'TIMEZONE_DATA_INVALID'), (EOFError, 'TIMEZONE_DATA_INVALID'),
    (M.ZoneInfoNotFoundError, 'UNRECOGNIZED_TIMEZONE'),
])
def test_lookup_failure_containment(exc, code, monkeypatch):
    calls = []
    def unavailable(key):
        calls.append(key)
        raise exc('SYNTHETIC_PRIVATE_RESOURCE_PATH')
    monkeypatch.setattr(M, '_read_zone_bytes', unavailable)
    row = R.fixture()[4]
    result = R.call(row)
    assert result['state'] == 'FAIL' and code in result['reason_codes']
    assert calls == [row['timezone']]
    assert 'SYNTHETIC_PRIVATE_RESOURCE_PATH' not in json.dumps(result)
    no_authority(result)


@pytest.mark.parametrize('key', [
    'UTC', 'GMT', 'CET', 'EST5EDT', 'US/Eastern', 'Etc/GMT+1', 'Etc/GMT-3',
    'America/Puerto_Rico', 'America/Argentina/Buenos_Aires', 'Asia/Kathmandu',
    'Europe/Paris', 'Pacific/Chatham',
])
def test_aliases_and_nested_keys_preserved(key):
    row = R.fixture()[4]
    row['timezone'] = key
    before = copy.deepcopy(row)
    result = R.call(row)
    assert result['state'] == 'PASS_CHECKED_CONSTRAINTS', result
    assert row == before
    no_authority(result)


def test_unknown_is_not_defaulted_to_utc():
    row = R.fixture()[4]
    row['timezone'] = 'Synthetic/Nonexistent'
    result = R.call(row)
    assert 'UNRECOGNIZED_TIMEZONE' in result['reason_codes']
    assert result['state'] == 'FAIL'
    no_authority(result)


def test_io_failure_dependency_accounting(monkeypatch):
    def unavailable(key):
        raise PermissionError('SYNTHETIC_PRIVATE_RESOURCE_PATH')
    monkeypatch.setattr(M, '_read_zone_bytes', unavailable)
    result = R.call(R.fixture())
    assert result['rows'][4]['state'] == result['rows'][5]['state'] == 'FAIL'
    assert result['rows'][0]['state'] == 'PASS_CHECKED_CONSTRAINTS'
    assert 'SYNTHETIC_PRIVATE_RESOURCE_PATH' not in json.dumps(result)
    no_authority(result)


def rehash(rows):
    """Synthetic builder only: not a real-record amendment or migration."""
    entities = {(r['record_type'], r[M.KINDS[r['record_type']][1]]): r for r in rows}
    for row in rows:
        if row['record_type'] != 'mycelial_preschedule_commitment':
            continue
        for p in row['manifest']['plans']:
            p['site_definition_sha256'] = M.logical_sha256(entities[('mycelial_field_site', p['site_id'])])
            p['target_definition_sha256'] = M.logical_sha256(entities[('mycelial_study_target', p['target_id'])])
            p['substrate_definition_sha256'] = {k: M.logical_sha256(entities[('mycelial_substrate_unit', k)]) for k in p['substrate_unit_ids']}
        row['manifest_sha256'] = M.logical_sha256(row['manifest'])


def test_combined_roles_and_nonactivation():
    rows = R.combined()
    before = copy.deepcopy(rows)
    result = R.call(rows)
    assert result['state'] == 'PASS_CHECKED_CONSTRAINTS', result
    assert result['passed_checked_constraints'] == 9
    edges = result['reference_candidates']
    archived = [e for e in edges if e['requester_row'] == 3]
    active = [e for e in edges if e['requester_row'] == 4]
    assert archived and all(e['edge_role'] == 'historical_definition' for e in archived)
    assert active and all(e['edge_role'] == 'active_use' for e in active)
    assert 'HISTORICAL_DEFINITION_NOT_ACTIVE' in result['rows'][3]['review_hold_codes']
    assert rows == before
    no_authority(result)


@pytest.mark.parametrize('mutation', [
    'definition_hash', 'manifest_hash', 'unrelated_missing', 'future_registration',
    'bad_chronology', 'malformed_duplicate', 'rejected', 'retired', 'missing_unit',
    'cycle', 'ordinary_claims_history',
])
def test_archival_context_does_not_suppress_defects(mutation):
    rows = R.combined()
    if mutation == 'definition_hash':
        rows[3]['manifest']['plans'][0]['substrate_definition_sha256'][rows[2]['substrate_unit_id']] = '0'*64
        rows[3]['manifest_sha256'] = M.logical_sha256(rows[3]['manifest'])
    elif mutation == 'manifest_hash':
        rows[3]['manifest_sha256'] = '0'*64
    elif mutation == 'unrelated_missing':
        rows[3]['manifest']['plans'][0]['target_id'] = 'MYC_TGT_SYNTH_MISSING'
        rows[3]['manifest_sha256'] = M.logical_sha256(rows[3]['manifest'])
    elif mutation == 'future_registration':
        rows[2]['registered_at'] = '2026-01-01T07:00:00Z'
        rehash(rows)
    elif mutation == 'bad_chronology':
        rows[8]['committed_at'] = rows[3]['committed_at']
    elif mutation == 'malformed_duplicate':
        duplicate = copy.deepcopy(rows[2])
        del duplicate['registered_at']
        rows.append(duplicate)
    elif mutation in {'rejected', 'retired'}:
        rows[2]['review_state'] = mutation
        rehash(rows)
    elif mutation == 'missing_unit':
        rows[2]['substrate_unit_id'] = 'MYC_SUB_SYNTH_OTHER'
    elif mutation == 'cycle':
        rows[2]['supersedes_substrate_unit_id'] = rows[7]['substrate_unit_id']
        rehash(rows)
    else:
        rows[3]['review_state'] = 'needs_review'
    before = copy.deepcopy(rows)
    result = R.call(rows)
    assert result['state'] == 'FAIL'
    assert result['rows'][4]['state'] == result['rows'][5]['state'] == 'FAIL'
    assert rows == before
    no_authority(result)


@pytest.mark.parametrize('family', ['site', 'target', 'substrate', 'preschedule', 'survey', 'observation'])
def test_archived_definition_chain_never_becomes_active(family):
    rows = R.fixture()
    for row in rows:
        if 'review_state' in row:
            row['review_state'] = 'superseded'
    rehash(rows)
    result = R.call(rows)
    assert result['state'] == 'PASS_CHECKED_CONSTRAINTS', result
    no_authority(result)
    i = next(i for i, r in enumerate(rows) if M.KINDS[r['record_type']][0] == family)
    assert rows[i]['review_state'] == 'superseded'
    assert 'REVIEW_STATE_NOT_ELIGIBLE' in result['rows'][i]['review_hold_codes']
    if family in {'substrate', 'preschedule', 'survey', 'observation'}:
        rows[i]['review_state'] = 'needs_review'
        rehash(rows)
        result = R.call(rows)
        assert result['rows'][i]['state'] == 'FAIL'
        no_authority(result)


@pytest.mark.parametrize('field', ['preschedule_commitment_id', 'substrate_unit_ids'])
def test_current_survey_cannot_activate_archived_dependency(field):
    rows = R.combined()
    rows[4][field] = rows[3]['commitment_id'] if field == 'preschedule_commitment_id' else [rows[2]['substrate_unit_id']]
    result = R.call(rows)
    assert result['rows'][4]['state'] == 'FAIL'
    assert 'REFERENCE_REVIEW_STATE_NOT_USABLE' in result['rows'][4]['reason_codes']
    no_authority(result)


def test_input_cannot_supply_internal_role():
    rows = R.combined()
    rows[4]['edge_role'] = 'historical_definition'
    result = R.call(rows)
    assert result['rows'][4]['state'] == 'FAIL'
    assert 'SCHEMA_INVALID' in result['rows'][4]['reason_codes']
    no_authority(result)


@pytest.mark.parametrize('invalid', [False, True])
def test_combined_graph_order_invariance(invalid):
    rows = R.combined()
    if invalid:
        rows.append(copy.deepcopy(rows[2]))
    expected = R.call(rows)['rows']
    for seed in range(10):
        indices = list(range(len(rows)))
        random.Random(seed).shuffle(indices)
        result = R.call([rows[i] for i in indices])
        assert result['rows'] == [expected[i] for i in indices]
        no_authority(result)
