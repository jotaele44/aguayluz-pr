"""Bounded TZif resource regression tests; no biological/production evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('tzif_boundary_helper', ROOT / 'tests/test_mycelial_consistency_v2_review201.py')
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
M = R.M


def header(version=b'\0', counts=(0, 0, 0, 0, 1, 4)):
    return b'TZif' + version + b'\0' * 15 + struct.pack('>6I', *counts)


def block(utoff=0, dst=0, index=0):
    return struct.pack('>iBB', utoff, dst, index) + b'UTC\0'


def valid(version=b'\0', offset=0):
    first = header(version) + block(offset)
    return first if version == b'\0' else first + header(version) + block(offset) + b'\n\n'


def row():
    return R.fixture()[4]


def no_authority(result):
    assert all(result[k] is False for k in R.FLAGS)
    for item in result.get('rows', []):
        assert all(item[k] is False for k in R.FLAGS)


def malformed():
    first = header(b'2') + block()
    return [
        b'', b'BAD!', b'TZif\0', header(), header(counts=(0,0,0,0,0,4)),
        header(counts=(0,0,0,0,1,0)), header(counts=(0,0,0,0,257,4)),
        header(counts=(0,0,0,2**32-1,1,4)), header(counts=(0,0,2**32-1,0,1,4)),
        header(counts=(0,0,0,0,1,2**32-1)), header(counts=(2,0,0,0,1,4)),
        header(counts=(0,2,0,0,1,4)), header(b'9') + block(),
        valid()+b'junk', first, first+b'TZif2', first+header(b'3')+block()+b'\n\n',
        first+header(b'\0')+block()+b'\n\n', first+header(b'2'),
        first+header(b'2')+block()+b'X', first+header(b'2')+block()+b'\nUTC0',
        first+header(b'2')+block()+b'\nUTC0\nEXTRA',
        first+header(b'2')+block()+b'\nUTC0\n\n',
        first+header(b'2')+block()+b'\nUTC0\0\n',
        first+header(b'2')+block()+b'\n\xff\n',
        first+header(b'2')+block()+b'\n'+b'A'*256+b'\n',
        header()+struct.pack('>iBB',0,2,0)+b'UTC\0',
        header()+block(index=4), header()+struct.pack('>iBB',0,0,0)+b'UTCA',
        header()+block(utoff=86400), header()+block(utoff=-86400),
        header()+struct.pack('>iBB',0,0,0)+b'\xffTC\0',
        header(counts=(0,0,0,0,1,130))+struct.pack('>iBB',0,0,128)+b'A'*129+b'\0',
        header(counts=(0,0,0,1,1,4))+struct.pack('>i',0)+b'\x01'+block(),
        header(counts=(0,0,0,2,1,4))+struct.pack('>ii',1,1)+b'\0\0'+block(),
        header(counts=(0,0,0,2,1,4))+struct.pack('>ii',2,1)+b'\0\0'+block(),
        header(counts=(1,1,0,0,1,4))+block()+b'\0\x01',
        header(counts=(0,1,0,0,1,4))+block()+b'\x02',
        header(counts=(0,0,1,0,1,4))+block()+struct.pack('>ii',100,2),
        header(counts=(0,0,1,0,1,4))+block()+struct.pack('>ii',-1,1),
        header(counts=(0,0,2,0,1,4))+block()+struct.pack('>iiii',100,1,100,2),
        b'X'*(M.MAX_TZIF_BYTES+1),
    ]


@pytest.mark.parametrize('data', malformed(), ids=lambda b: hashlib.sha256(b).hexdigest()[:12])
def test_malformed_resources_never_reach_decoder(data, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Malformed file reached decoder')
    monkeypatch.setattr(M, '_read_zone_bytes', lambda key: data)
    monkeypatch.setattr(M, 'ZoneInfo', SimpleNamespace(from_file=forbidden))
    result = R.call(row())
    assert result['state'] == 'FAIL'
    assert result['reason_codes']
    no_authority(result)


@pytest.mark.parametrize('version', [b'\0', b'2', b'3', b'4'])
def test_complete_valid_versions_decode_without_mutation(version, monkeypatch):
    data = valid(version)
    monkeypatch.setattr(M, '_read_zone_bytes', lambda key: data)
    result = R.call(row())
    assert result['state'] == 'PASS_CHECKED_CONSTRAINTS', result
    no_authority(result)


@pytest.mark.parametrize('footer', [b'UTC0', b'EST5EDT,M3.2.0/2,M11.1.0/2', b'<+04>-4'])
def test_valid_nonempty_footers(footer, monkeypatch):
    data = valid(b'2')[:-2] + b'\n'+footer+b'\n'
    monkeypatch.setattr(M, '_read_zone_bytes', lambda key: data)
    assert R.call(row())['state'] == 'PASS_CHECKED_CONSTRAINTS'


@pytest.mark.parametrize('footer', [b':', b'UTC999', b'UTC0,X', b'UTC0\t'])
def test_invalid_posix_footers_are_controlled(footer, monkeypatch):
    data=valid(b'2')[:-2]+b'\n'+footer+b'\n'
    monkeypatch.setattr(M, '_read_zone_bytes', lambda key: data)
    result=R.call(row())
    assert result['state']=='FAIL'; no_authority(result)


def test_valid_transition_and_type_data(monkeypatch):
    data=header(counts=(0,0,0,2,2,8))+struct.pack('>ii',100,200)+b'\0\1'+struct.pack('>iBBiBB',0,0,0,3600,1,4)+b'UTC\0DST\0'
    monkeypatch.setattr(M, '_read_zone_bytes', lambda key: data)
    assert R.call(row())['state']=='PASS_CHECKED_CONSTRAINTS'


def test_valid_indicators_and_leap_lengths(monkeypatch):
    data=header(counts=(1,1,1,0,1,4))+block()+struct.pack('>ii',100,1)+b'\1\1'
    monkeypatch.setattr(M, '_read_zone_bytes', lambda key: data)
    assert R.call(row())['state']=='PASS_CHECKED_CONSTRAINTS'


def test_every_prefix_of_valid_v2_rejected_before_decoder(monkeypatch):
    data=valid(b'2')
    def forbidden(*args, **kwargs):
        pytest.fail('Truncated bytes reached decoder')
    monkeypatch.setattr(M, 'ZoneInfo', SimpleNamespace(from_file=forbidden))
    for n in range(len(data)):
        monkeypatch.setattr(M, '_read_zone_bytes', lambda key, n=n: data[:n])
        result=R.call(row()); assert result['state']=='FAIL';no_authority(result)


def test_exact_validated_bytes_used_after_source_replacement(tmp_path, monkeypatch):
    d=tmp_path/'Synthetic';d.mkdir();p=d/'Zone';data=valid(offset=0);p.write_bytes(data)
    monkeypatch.setattr(M.zoneinfo,'TZPATH',(str(tmp_path),))
    validator=M._validate_tzif; actual=M.ZoneInfo; checked=[];decoded=[]
    def validate(b):
        validator(b);checked.append(b)
        p.write_bytes(valid(offset=3600)) # Simulate replacement after validation.
    def decode(stream, *, key):
        decoded.append(stream.getvalue())
        return actual.from_file(stream,key=key)
    monkeypatch.setattr(M,'_validate_tzif',validate)
    monkeypatch.setattr(M,'ZoneInfo',SimpleNamespace(from_file=decode))
    z=M._zone('Synthetic/Zone')
    assert checked==decoded==[data] and z.utcoffset(None).total_seconds()==0
    assert p.read_bytes()!=data


def test_corrupt_primary_file_does_not_fall_back(tmp_path, monkeypatch):
    p=tmp_path/'UTC';p.write_bytes(b'TZif\0');monkeypatch.setattr(M.zoneinfo,'TZPATH',(str(tmp_path),))
    def forbidden(*a,**k): pytest.fail('Corrupt primary must not fall back')
    monkeypatch.setattr(M.resources,'files',forbidden)
    result=R.call(row() | {'timezone':'UTC'})
    assert result['state']=='FAIL';no_authority(result)


def test_missing_primary_uses_local_package_snapshot(monkeypatch):
    monkeypatch.setattr(M.zoneinfo,'TZPATH',())
    result=R.call(row() | {'timezone':'UTC'})
    assert result['state']=='PASS_CHECKED_CONSTRAINTS';no_authority(result)


def test_missing_package_and_primary_do_not_default_to_utc(monkeypatch):
    monkeypatch.setattr(M.zoneinfo,'TZPATH',())
    def missing(*a,**k):raise ModuleNotFoundError('SYNTHETIC_PRIVATE_PATH')
    monkeypatch.setattr(M.resources,'files',missing)
    result=R.call(row());assert result['state']=='FAIL'
    assert 'UNRECOGNIZED_TIMEZONE' in result['reason_codes'];no_authority(result)


def test_unsupported_resource_backend_fails_closed(monkeypatch):
    monkeypatch.setattr(M.zoneinfo,'TZPATH',())
    monkeypatch.setattr(M.resources,'files',lambda *a: SimpleNamespace(joinpath=lambda *a: object()))
    result=R.call(row());assert result['state']=='FAIL'
    assert 'TIMEZONE_RESOURCE_BACKEND_UNSUPPORTED' in result['reason_codes'];no_authority(result)


def test_snapshot_size_limit_before_read(tmp_path, monkeypatch):
    p=tmp_path/'large';p.write_bytes(b'x'*(M.MAX_TZIF_BYTES+1))
    def forbidden(*a):pytest.fail('Oversized file read')
    monkeypatch.setattr(M.os,'read',forbidden)
    with pytest.raises(M.InputRejected,match='TIMEZONE_RESOURCE_LIMIT'):
        M._read_regular_tzif(p)


def test_directory_is_not_regular_resource(tmp_path):
    with pytest.raises((M.InputRejected,OSError)):
        M._read_regular_tzif(tmp_path)


@pytest.mark.skipif(not hasattr(os,'mkfifo'),reason='POSIX FIFO control only')
def test_fifo_is_rejected_before_blocking_read(tmp_path):
    p=tmp_path/'fifo';os.mkfifo(p)
    with pytest.raises(M.InputRejected,match='TIMEZONE_RESOURCE_NOT_REGULAR'):
        M._read_regular_tzif(p)


def test_short_read_is_not_claimed_complete(tmp_path,monkeypatch):
    p=tmp_path/'resource';p.write_bytes(valid())
    monkeypatch.setattr(M.os,'read',lambda *a:b'')
    with pytest.raises(M.InputRejected,match='TIMEZONE_RESOURCE_CHANGED'):
        M._read_regular_tzif(p)


def test_read_call_count_is_bounded(tmp_path,monkeypatch):
    p=tmp_path/'resource';p.write_bytes(b'x'*100)
    count=[]
    def fragments(*a):count.append(1);return b'x'
    monkeypatch.setattr(M.os,'read',fragments)
    with pytest.raises(M.InputRejected,match='TIMEZONE_RESOURCE_LIMIT'):
        M._read_regular_tzif(p)
    assert len(count)==64


def test_same_descriptor_changes_fail_closed(tmp_path,monkeypatch):
    p=tmp_path/'resource';data=valid();p.write_bytes(data);original=M.os.read;done=[]
    def changed(fd,n):
        b=original(fd,n)
        if not done:
            p.write_bytes(data+b'extra');done.append(1)
        return b
    monkeypatch.setattr(M.os,'read',changed)
    with pytest.raises(M.InputRejected,match='TIMEZONE_RESOURCE_CHANGED'):
        M._read_regular_tzif(p)


@pytest.mark.parametrize('exc',[struct.error,AssertionError,ValueError,EOFError,IndexError,OverflowError])
def test_decoder_error_containment_is_simulated_not_platform_claim(exc,monkeypatch):
    monkeypatch.setattr(M,'_read_zone_bytes',lambda key:valid())
    def bad(*args,**kwargs):raise exc('SYNTHETIC_PRIVATE_PATH')
    monkeypatch.setattr(M,'ZoneInfo',SimpleNamespace(from_file=bad))
    result=R.call(row());assert result['state']=='FAIL';no_authority(result)
    assert 'SYNTHETIC_PRIVATE_PATH' not in json.dumps(result)


def test_corrupt_resource_dependency_accounting(monkeypatch):
    monkeypatch.setattr(M,'_read_zone_bytes',lambda key:b'TZif\0')
    records=R.fixture();before=json.dumps(records,sort_keys=True)
    result=R.call(records)
    assert result['rows'][4]['state']==result['rows'][5]['state']=='FAIL'
    assert result['input_rows']==result['failed_rows']+result['passed_checked_constraints']
    assert json.dumps(records,sort_keys=True)==before;no_authority(result)


def test_schema_and_logical_serialization_are_unchanged():
    assert M.IMPLEMENTATION_VERSION=='2.0.3'
    assert M.SCHEMA_VERSION=='2.0.0'
    assert M.SCHEMA_SHA256=='bfe7e8628d93adb149c8b79672cbfb4c8025c56d1de3505cb07a9eec2f2a8aba'
    assert M.SERIALIZATION=='aguayluz.sorted-json-utf8/v1'
