"""Fresh desired-behavior review: no code edits, xfails, or admission assertions."""
from __future__ import annotations
import copy
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('reviewed_test_helper', ROOT/'tests/test_mycelial_consistency_v2_review201.py')
assert SPEC and SPEC.loader
R=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(R)
M=R.M
FLAGS=R.FLAGS

def no_authority(result):
    assert all(result[k] is False for k in FLAGS)
    for row in result.get('rows',[]):assert all(row[k] is False for k in FLAGS)
    if 'input_rows' in result:assert result['input_rows']==result['failed_rows']+result['passed_checked_constraints']

@pytest.mark.parametrize('case,expected',[
    ('empty','FAIL'),('bad_magic','FAIL'),('short_header','FAIL'),('short_body','FAIL'),
    ('v2_invalid_footer_start','FAIL'),('v2_missing_footer_end','FAIL'),
    ('valid_v1','PASS_CHECKED_CONSTRAINTS'),('valid_v2','PASS_CHECKED_CONSTRAINTS'),
])
def test_real_loader_returns_controlled_result_for_simulated_tzif_resource(case,expected,tmp_path):
    # Fault injection modifies only a disposable subprocess TZPATH. Host tzdata
    # and source files remain unchanged. Parent owns cleanup even after timeout.
    env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
    with tempfile.TemporaryDirectory(prefix='pr257_tzif_test_') as parent:
        command=[sys.executable,str(ROOT/'tests/_mycelial_tzif_probe.py'),case,parent]
        try:
            process=subprocess.run(command,capture_output=True,text=True,timeout=5,env=env)
        except subprocess.TimeoutExpired as exc:
            err=exc.stderr or b''
            (tmp_path/f'tzif_{case}.stderr.txt').write_bytes(err.encode() if isinstance(err,str) else err)
            pytest.fail('Dependency loader did not return controlled result within isolated 5-second safety timeout')
    (tmp_path/f'tzif_{case}.stderr.txt').write_text(process.stderr)
    assert process.returncode==0,process.stderr
    payload=json.loads(process.stdout)
    (tmp_path/f'tzif_{case}.json').write_text(json.dumps(payload,indent=2)+'\n')
    assert 'exception_type' not in payload,payload
    result=payload['result'];assert result['state']==expected,result
    no_authority(result)
    if expected=='FAIL':assert result['reason_codes']

@pytest.mark.parametrize('case',['America','Etc','A'*300,'../UTC','UTC\x00hidden'])
def test_prior_bad_key_rejection_still_contains_failure(case):
    row=R.fixture()[4];row['timezone']=case
    result=R.call(row);assert result['state']=='FAIL';no_authority(result)

@pytest.mark.parametrize('zone',['UTC','America/Puerto_Rico','US/Eastern','Pacific/Chatham'])
def test_installed_valid_zones_are_preserved(zone):
    row=R.fixture()[4];row['timezone']=zone;before=copy.deepcopy(row)
    result=R.call(row);assert result['state']=='PASS_CHECKED_CONSTRAINTS';assert row==before;no_authority(result)

@pytest.mark.parametrize('permutation_seed',[0,13,101])
def test_archived_chains_remain_inspectable_and_nonactivating(permutation_seed):
    rows=R.combined(); before=copy.deepcopy(rows);random.Random(permutation_seed).shuffle(rows)
    result=R.call(rows);assert result['state']=='PASS_CHECKED_CONSTRAINTS'
    assert result['input_rows']==9 and result['failed_rows']==0
    assert sorted(M.logical_sha256(r) for r in rows)==sorted(M.logical_sha256(r) for r in before)
    no_authority(result)

@pytest.mark.parametrize('change',['active_old_commitment','active_old_substrate','ambiguous','cycle','wrong_hash'])
def test_archived_roles_do_not_bypass_active_or_integrity_failures(change):
    rows=R.combined()
    if change=='active_old_commitment':rows[4]['preschedule_commitment_id']=rows[3]['commitment_id']
    elif change=='active_old_substrate':rows[4]['substrate_unit_ids']=[rows[2]['substrate_unit_id']]
    elif change=='ambiguous':rows.append(copy.deepcopy(rows[2]))
    elif change=='cycle':rows[2]['supersedes_substrate_unit_id']=rows[7]['substrate_unit_id']
    else:rows[3]['manifest_sha256']='0'*64
    result=R.call(rows);assert result['state']=='FAIL';assert result['rows'][4]['state']=='FAIL';no_authority(result)

@pytest.mark.parametrize('data',[b'{"x":1,"x":2}',b'{"x":1e10000}',b'\xff',b'[]'])
def test_strict_input_failure_remains_reason_coded(data):
    result=M.check_bytes(data);assert result['state']=='FAIL';assert result['reason_codes'];no_authority(result)

def test_schema_pin_and_implementation_binding():
    assert M.IMPLEMENTATION_VERSION=='2.0.3'
    assert M.SCHEMA_SHA256=='bfe7e8628d93adb149c8b79672cbfb4c8025c56d1de3505cb07a9eec2f2a8aba'
