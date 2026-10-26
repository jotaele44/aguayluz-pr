"""Synthetic, bounded contract tests; these never certify an official EIA layout."""
import hashlib
import io
import json
import logging
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aguayluz.electricity.eia import AcquisitionError, EIAClient
from aguayluz.electricity.evidence import (
    GeneratorClaim,
    Measurement,
    SourceReceipt,
    reconcile_claims,
)
from aguayluz.electricity.projection import electricity_projection
from aguayluz.electricity.store import EvidenceStore
from aguayluz.electricity.workbook import HEADERS, parse_860m

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def receipt(raw=b"original source", **updates):
    return SourceReceipt(sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw),
                         source_url="https://www.eia.gov/electricity/data/eia860m/",
                         authority="EIA", retrieved_at=NOW, schema_signature="synthetic-test/v1", **updates)


def measure(**updates):
    return Measurement(**({"entity_id": "EIA:1:01", "metric": "generation", "value": 1.0, "unit": "MWh",
                           "interval_start": NOW, "interval_end": NOW + timedelta(hours=1),
                           "evidence_class": "OBSERVED", "receipt_sha256": receipt().sha256} | updates))


def claim(**updates):
    return GeneratorClaim(**({"source_system": "EIA-860M", "plant_id": "1", "generator_id": "01",
                              "valid_from": NOW, "name": "same name", "nameplate_mw": 1.0,
                              "status": "OP", "receipt_sha256": receipt().sha256} | updates))


def workbook(rows=None, headers=HEADERS):
    rows = rows or [list(headers), ["1", "01", "PR", "Plant", "10"], ["2", "1", "TX", "Plant", "20"]]
    elements = []
    for row_index, row in enumerate(rows, 1):
        cells = ''.join(f'<c r="{chr(65+i)}{row_index}" t="inlineStr"><is><t>{escape(value)}</t></is></c>' for i, value in enumerate(row))
        elements.append(f'<row r="{row_index}">{cells}</row>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(elements) + '</sheetData></worksheet>')
    return stream.getvalue()


@pytest.mark.parametrize("updates", [{"value": float('nan')}, {"value": float('inf')}, {"unit": "MW/h"},
                                      {"interval_end": NOW}, {"interval_start": NOW.replace(tzinfo=None)},
                                      {"review_state": "CANONICAL"}, {"evidence_class": "LIVE"},
                                      {"evidence_class": "RECONSTRUCTED"}, {"evidence_class": "FORECAST"},
                                      {"receipt_sha256": "../escape"}])
def test_measurement_negative_controls(updates):
    with pytest.raises(ValidationError):
        measure(**updates)


def test_distinct_derived_states_require_method_uncertainty_issue_time():
    reconstructed = measure(evidence_class="RECONSTRUCTED", method_version="balance/v1", uncertainty=2)
    forecast = measure(evidence_class="FORECAST", method_version="model/v1", uncertainty=3, issued_at=NOW)
    assert reconstructed.evidence_class != forecast.evidence_class
    with pytest.raises(ValidationError):
        measure(evidence_class="FORECAST", method_version="model/v1", uncertainty=3, issued_at=NOW + timedelta(seconds=1))


@pytest.mark.parametrize("url", ["http://eia.gov/a", "https://user:pass@eia.gov/a", "https://eia.gov/a?api_key=x", "https://eia.gov/a#secret"])
def test_receipt_cannot_embed_credentials(url):
    with pytest.raises(ValidationError):
        SourceReceipt(**(receipt().model_dump() | {"source_url": url}))


def test_receipt_parameters_cannot_embed_credentials():
    with pytest.raises(ValidationError):
        receipt(request_parameters=(("api_key", "test-value"),))


def test_identity_never_uses_names_or_proximity_and_preserves_raw_ids():
    left, right = claim(), claim(plant_id="2")
    assert left.source_identity != right.source_identity
    assert claim(generator_id="1").source_identity != left.source_identity
    assert reconcile_claims([left, right])["contradictions"] == []
    with pytest.raises(ValidationError):
        claim(generator_id=" 01 ")
    with pytest.raises(ValidationError):
        claim(valid_from=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        claim(valid_to=NOW)


def test_temporal_contradictions_and_effective_dated_identity():
    old = claim(valid_to=NOW + timedelta(days=2))
    new = claim(valid_from=NOW + timedelta(days=1), nameplate_mw=2)
    conflict = reconcile_claims([new, old])
    assert conflict == reconcile_claims([old, new])
    assert len(conflict['contradictions']) == 1
    assert conflict['canonical_promotion'] == 'BLOCKED'
    assert reconcile_claims([old, claim(valid_from=old.valid_to, nameplate_mw=2)])['contradictions'] == []


def test_store_integrity_idempotency_orphans_and_immutable_sql(tmp_path):
    store = EvidenceStore(tmp_path / 'evidence')
    empty = electricity_projection(store)
    assert not store.root.exists()
    assert all(v['availability'] == 'UNAVAILABLE' for v in empty['states'].values())
    first = store.capture(b'original source', receipt())
    assert first == store.capture(b'original source', receipt())
    with pytest.raises(ValueError):
        store.capture(b'changed', receipt())
    identifier = store.add_measurement(measure())
    assert identifier == store.add_measurement(measure())
    store.add_claims([claim(), claim()])
    before = electricity_projection(store)
    assert len(before['generator_claims']) == 1
    assert len(before['states']['OBSERVED']['measurements']) == 1
    assert before['revision'] == electricity_projection(store)['revision']
    for table in ('receipts', 'measurements', 'claims'):
        with sqlite3.connect(store.root / 'ledger.sqlite3') as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(f'DELETE FROM {table}')
    with pytest.raises(ValueError):
        store.add_claims([claim(receipt_sha256='a' * 64)])
    with pytest.raises(FileNotFoundError):
        store.add_measurement(measure(receipt_sha256='a' * 64))
    (store.root / 'raw' / receipt().sha256).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='integrity'):
        store.snapshot()


def test_store_rejects_path_alias_and_symlink(tmp_path):
    store = EvidenceStore(tmp_path)
    with pytest.raises(ValueError):
        store.read_raw('../secret')
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'raw' / receipt().sha256).symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='symlink'):
        store.capture(b'original source', receipt())


def test_offline_workbook_pr_filter_raw_ids_and_arithmetic():
    raw = workbook()
    result = parse_860m(raw, sheet_path='xl/worksheets/sheet1.xml', receipt_sha256=hashlib.sha256(raw).hexdigest(), effective_at=NOW)
    assert result['arithmetic'] == {'source': 2, 'retained': 1, 'excluded': 1, 'unresolved': 0}
    assert result['claims'][0].generator_id == '01'
    assert result['raw_rows'][0]['Generator ID'] == '01'
    assert result['canonical_promotion'] == 'BLOCKED'


def test_offline_workbook_unknown_schema_and_unresolved_scope():
    with pytest.raises(ValueError):
        parse_860m(workbook(headers=('wrong',)), sheet_path='xl/worksheets/sheet1.xml', receipt_sha256=hashlib.sha256(workbook(headers=('wrong',))).hexdigest(), effective_at=NOW)
    raw = workbook([list(HEADERS), ['1', '01', '', 'Plant', '10'], ['bad', '01', 'PR', 'Plant', 'NaN']])
    result = parse_860m(raw, sheet_path='xl/worksheets/sheet1.xml', receipt_sha256=hashlib.sha256(raw).hexdigest(), effective_at=NOW)
    assert result['arithmetic']['unresolved'] == 2


@pytest.mark.parametrize('member,payload', [('../escape', 'x'), ('xl/worksheets/sheet1.xml', '<!DOCTYPE a><a/>')])
def test_workbook_unsafe_archive_and_xml(member, payload):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr(member, payload)
    with pytest.raises(ValueError):
        parse_860m(stream.getvalue(), sheet_path='xl/worksheets/sheet1.xml', receipt_sha256=hashlib.sha256(stream.getvalue()).hexdigest(), effective_at=NOW)


def api_client(tmp_path, handler):
    return EIAClient(EvidenceStore(tmp_path), client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)


def metadata():
    return {'frequency': [{'id': 'monthly'}], 'facets': [{'id': 'stateid'}], 'data': {'generation': {'units': 'MWh'}}}


def test_eia_pagination_metadata_receipts_and_secret_redaction(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('EIA_API_KEY', 'synthetic-credential-not-real')
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/facet/stateid/'):
            response = {'totalFacets': 1, 'facets': [{'id': 'PR'}]}
        elif request.url.path.endswith('/data/'):
            offset = int(request.url.params['offset'])
            response = {'total': 2, 'data': [{'stateid': 'PR', 'period': f'2026-0{offset+1}', 'generation': '1'}]}
        else:
            response = metadata()
        return httpx.Response(200, json={'response': response})
    with caplog.at_level(logging.DEBUG):
        client = api_client(tmp_path, handler)
        result = client.monthly_pr('facility-fuel', data_column='generation', state_facet='stateid', start='2026-01', end='2026-02', page_size=1)
    assert len(result['rows']) == 2
    assert 'synthetic-credential-not-real' not in caplog.text
    assert len(result['receipt_sha256']) == 4
    snapshot = client.store.snapshot()
    assert 'synthetic-credential-not-real' not in json.dumps(snapshot)
    assert requests[-1].url.params['offset'] == '1'
    assert any(('offset', '1') in SourceReceipt.model_validate(s).request_parameters for s in snapshot['sources'])


def test_eia_missing_credential_retry_schema_and_endpoint_failure(tmp_path, monkeypatch):
    monkeypatch.delenv('EIA_API_KEY', raising=False)
    client = api_client(tmp_path, lambda _: httpx.Response(429, headers={'retry-after': '1'}))
    with pytest.raises(AcquisitionError, match='CREDENTIAL_MISSING'):
        client.discover('facility-fuel')
    monkeypatch.setenv('EIA_API_KEY', 'synthetic-credential-not-real')
    with pytest.raises(AcquisitionError, match='RETRY_EXHAUSTED'):
        client.discover('facility-fuel')
    assert not tmp_path.joinpath('ledger.sqlite3').exists()
    with pytest.raises(AcquisitionError, match='ENDPOINT_UNSUPPORTED'):
        client.discover('../secret')
    client = api_client(tmp_path, lambda _: httpx.Response(200, content=b'not JSON'))
    with pytest.raises(AcquisitionError, match='SCHEMA_INVALID'):
        client.discover('facility-fuel')
    assert len(client.store.snapshot()['sources']) == 1  # Invalid raw bytes remain evidence.


@pytest.mark.parametrize('case', ['no-pr', 'partial-facets', 'wrong-state', 'empty-page', 'drift', 'repeated', 'wrong-column', 'invalid-period'])
def test_eia_fail_closed_scope_pagination_and_schema(tmp_path, monkeypatch, case):
    monkeypatch.setenv('EIA_API_KEY', 'synthetic-credential-not-real')
    def handler(request):
        if request.url.path.endswith('/facet/stateid/'):
            response = {'totalFacets': 2 if case == 'partial-facets' else 1, 'facets': [{'id': 'TX' if case == 'no-pr' else 'PR'}]}
        elif request.url.path.endswith('/data/'):
            offset = int(request.url.params['offset'])
            response = {'total': 2 if case != 'drift' or offset == 0 else 3, 'data': [] if case == 'empty-page' else [{'stateid': 'TX' if case == 'wrong-state' else 'PR', 'period': '2026-01', 'generation': '1'}]}
        else:
            response = metadata()
        return httpx.Response(200, json={'response': response})
    client = api_client(tmp_path, handler)
    with pytest.raises(AcquisitionError):
        client.monthly_pr('facility-fuel', data_column='nope' if case == 'wrong-column' else 'generation', state_facet='stateid', start='2026-99' if case == 'invalid-period' else '2026-01', end='2026-02', page_size=1)


@pytest.mark.parametrize('url', ['http://www.eia.gov/a.xlsx', 'https://evil.test/electricity/data/eia860m/xls/a.xlsx', 'https://www.eia.gov@evil.test/a.xlsx', 'https://www.eia.gov/electricity/data/eia860m/xls/../a.xlsx', 'https://www.eia.gov/electricity/data/eia860m/xls/a.xlsx?api_key=test'])
def test_eia_ssrf_and_url_negatives(tmp_path, url):
    with pytest.raises(AcquisitionError, match='OFFICIAL_URL_REQUIRED'):
        api_client(tmp_path, lambda _: pytest.fail('network must not be reached')).acquire_workbook(url)


def test_workbook_capture_and_echoed_secret_refusal(tmp_path, monkeypatch):
    url = 'https://www.eia.gov/electricity/data/eia860m/xls/test.xlsx'
    client = api_client(tmp_path, lambda _: httpx.Response(200, content=workbook()))
    digest = client.acquire_workbook(url)
    assert client.store.read_raw(digest).startswith(b'PK')
    monkeypatch.setenv('EIA_API_KEY', 'synthetic-credential-not-real')
    client = api_client(tmp_path, lambda _: httpx.Response(200, content=b'synthetic-credential-not-real'))
    with pytest.raises(AcquisitionError, match='CONTAINS_CREDENTIAL'):
        client.discover('facility-fuel')
    assert all(s['sha256'] != hashlib.sha256(b'synthetic-credential-not-real').hexdigest() for s in client.store.snapshot()['sources'])


def test_canonical_application_auth_import_tamper_and_contract(tmp_path, monkeypatch):
    from server.backend import electricity_api
    from server.backend.app import app
    monkeypatch.setattr(electricity_api.legacy, 'DATA', tmp_path)
    client = TestClient(app)
    path = '/electricity/v1/'
    monkeypatch.delenv('API_SECRET_KEY', raising=False)
    assert client.get(path + 'projection').json()['certification'] == 'NOT_CERTIFIED'
    assert client.post(path + 'acquire', json={'url': 'https://example.test'}).status_code == 503
    monkeypatch.setenv('API_SECRET_KEY', 'test-operator-key-not-real')
    assert client.post(path + 'acquire', json={'url': 'https://example.test'}).status_code == 401
    raw = workbook()
    store = EvidenceStore(tmp_path / 'electricity')
    store.capture(raw, receipt(raw))
    headers = {'Authorization': 'Bearer test-operator-key-not-real'}
    body = {'sha256': hashlib.sha256(raw).hexdigest(), 'sheet_path': 'xl/worksheets/sheet1.xml', 'effective_at': NOW.isoformat()}
    response = client.post(path + 'import/860m', json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()['arithmetic']['retained'] == 1
    assert len(client.get(path + 'projection').json()['generator_claims']) == 1
    assert client.post(path + 'import/860m', json=body | {'sha256': '../bad'}, headers=headers).status_code == 422
    (store.root / 'raw' / body['sha256']).write_bytes(b'tampered')
    assert client.get(path + 'projection').status_code == 503
    assert 'tampered' not in client.get(path + 'projection').text


def test_projection_schema_and_determinism(tmp_path):
    from pathlib import Path

    import jsonschema
    schema = json.loads((Path(__file__).parents[1] / 'schemas/electricity_projection.v1.schema.json').read_text())
    jsonschema.validate(electricity_projection(EvidenceStore(tmp_path)), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(electricity_projection(EvidenceStore(tmp_path)) | {'schema_version': 'unknown'}, schema)


def test_offline_upload_auth_capture_import_and_failed_acquisition_history(tmp_path, monkeypatch):
    from server.backend import electricity_api
    from server.backend.app import app
    monkeypatch.setattr(electricity_api.legacy, 'DATA', tmp_path)
    monkeypatch.setenv('API_SECRET_KEY', 'synthetic-operator-only')
    client = TestClient(app)
    headers = {'Authorization': 'Bearer synthetic-operator-only', 'X-EIA-Source-URL': 'https://www.eia.gov/electricity/data/eia860m/xls/test.xlsx', 'Content-Type': 'application/octet-stream'}
    raw = workbook()
    path = '/electricity/v1/import/workbook'
    assert client.post(path, content=raw).status_code == 401
    assert client.post(path, content=b'invalid', headers=headers).status_code == 422
    assert client.post(path, content=raw, headers=headers | {'X-EIA-Source-URL': 'https://evil.test/a.xlsx'}).status_code == 422
    captured = client.post(path, content=raw, headers=headers)
    assert captured.status_code == 200
    assert captured.json()['origin_verification'] == 'UNVERIFIED'
    projection = client.get('/electricity/v1/projection').json()
    assert projection['sources'][0]['schema_signature'] == 'OFFLINE_ORIGIN_UNVERIFIED/AUDIT_ONLY'
    assert projection['acquisition_attempts'][0]['code'] == 'EIA_OFFLINE_CAPTURED_AUDIT_ONLY'
    failure = client.post('/electricity/v1/acquire', headers={'Authorization': headers['Authorization']}, json={'url': 'https://evil.test/a.xlsx'})
    assert failure.status_code == 502
    assert client.get('/electricity/v1/projection').json()['acquisition_attempts'][-1]['code'] == 'EIA_OFFICIAL_URL_REQUIRED'


def test_acquisition_redacts_transport_error_and_refuses_redirect_and_bad_port(tmp_path, monkeypatch):
    monkeypatch.setenv('EIA_API_KEY', 'synthetic-credential-not-real')
    def fail(request):
        raise httpx.ConnectError('contains synthetic-credential-not-real', request=request)
    with pytest.raises(AcquisitionError, match='RETRY_EXHAUSTED') as result:
        api_client(tmp_path, fail).discover('facility-fuel')
    assert 'synthetic-credential-not-real' not in str(result.value)
    client = api_client(tmp_path, lambda _: httpx.Response(302, headers={'location': 'https://evil.test'}))
    with pytest.raises(AcquisitionError, match='HTTP_302'):
        client.discover('facility-fuel')
    for url in ['https://www.eia.gov:invalid/electricity/data/eia860m/xls/a.xlsx', 'https://[bad']:
        with pytest.raises(AcquisitionError, match='OFFICIAL_URL_REQUIRED'):
            client.acquire_workbook(url)


def test_symlinked_parent_database_and_acquisition_audit_controls(tmp_path):
    store = EvidenceStore(tmp_path / 'store')
    store.root.mkdir()
    (store.root / 'raw').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='directory symlinks'):
        store.capture(b'original source', receipt())
    (store.root / 'ledger.sqlite3').symlink_to(tmp_path / 'missing.sqlite3')
    with pytest.raises(ValueError, match='database symlinks'):
        store.record_attempt('EIA_FAILED')
    with pytest.raises(ValueError, match='database symlinks'):
        store.snapshot()
    with pytest.raises(ValueError, match='invalid acquisition'):
        store.record_attempt('https://example.test?api_key=secret')


def test_offline_rollback_rehearsal_restores_scientific_revision(tmp_path):
    import shutil
    live = EvidenceStore(tmp_path / 'live')
    live.capture(b'original source', receipt())
    live.add_measurement(measure())
    before = electricity_projection(live)
    backup = tmp_path / 'backup'
    backup.mkdir()
    # Source acquisition is quiesced during this rehearsal. sqlite backup gives
    # a consistent DB image; raw content is copied and rehashed on restoration.
    with sqlite3.connect(live.root / 'ledger.sqlite3') as source, sqlite3.connect(backup / 'ledger.sqlite3') as target:
        source.backup(target)
    shutil.copytree(live.root / 'raw', backup / 'raw')
    live.capture(b'revised source', receipt(b'revised source'))
    live.add_measurement(measure(value=2, receipt_sha256=receipt(b'revised source').sha256))
    assert electricity_projection(live)['revision'] != before['revision']
    restored = EvidenceStore(backup)
    assert electricity_projection(restored)['revision'] == before['revision']
    assert electricity_projection(restored)['states'] == before['states']
    assert len(live.snapshot()['measurements']) == 2  # Rehearsal never destroys live evidence.


def test_projection_load_replay_and_missing_source_fail_closed(tmp_path):
    import time
    store = EvidenceStore(tmp_path)
    store.capture(b'original source', receipt())
    for index in range(100):
        store.add_measurement(measure(interval_start=NOW + timedelta(hours=index), interval_end=NOW + timedelta(hours=index+1)))
    started = time.monotonic()
    first = electricity_projection(store)
    for _ in range(10):
        assert electricity_projection(store)['revision'] == first['revision']
    assert time.monotonic() - started < 10  # Bounded local smoke, not production load certification.
    (store.root / 'raw' / receipt().sha256).unlink()
    with pytest.raises(FileNotFoundError):
        store.snapshot()
