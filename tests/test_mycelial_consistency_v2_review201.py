"""Desired-behavior tests against the unchanged head; no xfail or remediation claims."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('fresh_review_subject', ROOT/'research/mycelial/consistency_v2.py')
assert SPEC is not None and SPEC.loader is not None
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)
FLAGS=('record_admitted','field_authorized','public_export_authorized','model_eligible')


def fixture():
    return json.loads((ROOT/'tests/fixtures/mycelial_consistency/v2/examples.json').read_text())['records']


def call(value):
    return M.check_bytes(json.dumps(value,allow_nan=False).encode('utf-8'))


def combined():
    """Two historical predecessor edges with internally consistent synthetic hashes."""
    rows=fixture()
    oldsub,oldplan=rows[2],rows[3]
    oldsub['review_state']='superseded';oldplan['review_state']='superseded'
    newsub=copy.deepcopy(oldsub)
    newsub.update(substrate_unit_id='MYC_SUB_SYNTH_NEW',registered_at='2025-12-30T14:00:00Z',supersedes_substrate_unit_id=oldsub['substrate_unit_id'],review_state='needs_review')
    newplan=copy.deepcopy(oldplan)
    newplan.update(commitment_id='MYC_PSC_SYNTH_NEW',committed_at='2025-12-31T13:00:00Z',supersedes_commitment_id=oldplan['commitment_id'],review_state='needs_review')
    rows.extend([newsub,newplan])
    newplan['manifest']['plans'][0]['substrate_unit_ids']=[newsub['substrate_unit_id']]
    rows[4]['preschedule_commitment_id']=newplan['commitment_id']
    rows[4]['substrate_unit_ids']=[newsub['substrate_unit_id']]
    rows[5]['substrate_unit_id']=newsub['substrate_unit_id']
    entities={(r['record_type'],r[M.KINDS[r['record_type']][1]]):r for r in rows}
    for row in (oldplan,newplan):
        for plan in row['manifest']['plans']:
            plan['site_definition_sha256']=M.logical_sha256(entities[('mycelial_field_site',plan['site_id'])])
            plan['target_definition_sha256']=M.logical_sha256(entities[('mycelial_study_target',plan['target_id'])])
            plan['substrate_definition_sha256']={sid:M.logical_sha256(entities[('mycelial_substrate_unit',sid)]) for sid in plan['substrate_unit_ids']}
        row['manifest_sha256']=M.logical_sha256(row['manifest'])
    return rows


@pytest.mark.parametrize('zone',['America','Etc','A'*300],ids=['directory-America','directory-Etc','overlong-key'])
def test_untrusted_timezone_filesystem_failures_return_reason_codes(zone):
    # tzdata is installed in the recorded test environment; no monkeypatch is used.
    row=fixture()[4];row['timezone']=zone
    result=call(row)
    assert result['state']=='FAIL'
    assert result['reason_codes']
    assert all(result[k] is False for k in FLAGS)


def test_composed_historical_predecessors_do_not_poison_current_records():
    rows=combined()
    # Establish no malformed individual record or plan-hash mismatch is the cause.
    assert all(M.check_record(row)['state']=='PASS_CHECKED_CONSTRAINTS' for row in rows)
    result=call(rows)
    for i in (8,4,5):
        assert result['rows'][i]['state']=='PASS_CHECKED_CONSTRAINTS', result['rows'][i]
        assert result['rows'][i]['review_hold_codes']
        assert all(result['rows'][i][k] is False for k in FLAGS)


@pytest.mark.parametrize('zone',['UTC','America/Puerto_Rico','Europe/Paris'])
def test_valid_timezone_keys_keep_diagnostic_nonadmission(zone):
    row=fixture()[4];row['timezone']=zone
    result=call(row)
    assert result['state']=='PASS_CHECKED_CONSTRAINTS'
    assert result['review_hold_codes']
    assert all(result[k] is False for k in FLAGS)


@pytest.mark.parametrize('row_index',[2,3],ids=['substrate','commitment'])
def test_direct_active_use_of_superseded_record_remains_blocked(row_index):
    rows=fixture();rows[row_index]['review_state']='superseded'
    result=call(rows)
    assert result['rows'][4]['state']=='FAIL'
    assert result['rows'][5]['state']=='FAIL'


@pytest.mark.parametrize('mutation',['duplicate','missing','cycle'])
def test_combined_history_does_not_license_ambiguous_or_invalid_graph(mutation):
    rows=combined()
    if mutation=='duplicate': rows.append(copy.deepcopy(rows[2]))
    elif mutation=='missing': del rows[2]['registered_at']
    else: rows[2]['supersedes_substrate_unit_id']=rows[7]['substrate_unit_id']
    result=call(rows)
    assert result['state']=='FAIL'
    assert result['rows'][4]['state']=='FAIL'
    assert all(result[k] is False for k in FLAGS)


@pytest.mark.parametrize('data',[b'{"a":1,"a":2}',b'{"a":NaN}',b'\xff'])
def test_strict_input_controls_still_return_fail(data):
    result=M.check_bytes(data)
    assert result['state']=='FAIL'
    assert all(result[k] is False for k in FLAGS)


def test_graph_input_is_not_mutated_and_arithmetic_closes():
    rows=combined();before=copy.deepcopy(rows);result=call(rows)
    assert rows==before
    assert result['input_rows']==result['failed_rows']+result['passed_checked_constraints']
    assert all(result[k] is False for k in FLAGS)
    assert all(all(row[k] is False for k in FLAGS) for row in result['rows'])


@pytest.mark.parametrize('stamp',['2026-01-01T08:00:00+00:60','2026-01-01T08:00:00+24:00'])
def test_offset_component_correction_remains_effective(stamp):
    row=fixture()[4];row['scheduled_for']=stamp
    assert call(row)['state']=='FAIL'
    assert row['scheduled_for']==stamp


def test_original_positive_bundle_still_passes_selected_constraints():
    result=call(fixture())
    assert result['state']=='PASS_CHECKED_CONSTRAINTS'
    assert all(result[k] is False for k in FLAGS)


@pytest.mark.parametrize('field',['observer_count','person_minutes'])
def test_large_numeric_correction_remains_effective(field):
    row=fixture()[4];row[field]=10**400
    result=call(row)
    assert result['state']=='FAIL'
    assert all(result[k] is False for k in FLAGS)


@pytest.mark.parametrize('stamp',['0001-01-01T00:00:00Z','9999-12-31T23:59:59-23:59'])
def test_conversion_range_correction_remains_effective(stamp):
    row=fixture()[4];row['scheduled_for']=stamp
    result=call(row)
    assert result['state']=='FAIL'
    assert all(result[k] is False for k in FLAGS)
