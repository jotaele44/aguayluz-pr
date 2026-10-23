"""Synthetic contract tests; fixtures never establish NOAA schema or PR coverage."""
import copy
import unittest
from datetime import datetime, timezone

from aguayluz.ionosphere import audit_status, validate_batch, validate_record

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def record():
    return dict(id='fixture:1', metric='TEC', value=0, units='TECU',
                observed_at='2026-10-23T11:59:00Z', retrieved_at='2026-10-23T12:00:00Z',
                source_url='https://example.org/fixture', source_sha256='a'*64,
                kind='MODEL', quality='UNKNOWN', longitude=-66, latitude=18)


class ContractTests(unittest.TestCase):
    def test_whole_row_zero_and_no_identity_or_impact_claim(self):
        row = record()
        row['raw_note'] = '  Mayagüez  '
        before = copy.deepcopy(row)
        result = validate_record(row, NOW)
        self.assertEqual(result['raw_record'], before)
        self.assertEqual(row, before)
        self.assertEqual(result['freshness'], 'FRESH')
        self.assertEqual(result['spatial_binding'], 'UNRESOLVED')
        self.assertEqual(result['impact'], 'UNKNOWN')
        self.assertEqual(result['quality'], 'UNKNOWN')

    def test_missing_is_not_zero(self):
        row = record(); row['value'] = None
        self.assertEqual(validate_record(row, NOW)['freshness'], 'MISSING')

    def test_stale_uses_observation_time(self):
        row = record(); row['observed_at'] = '2026-10-22T00:00:00Z'
        self.assertEqual(validate_record(row, NOW)['freshness'], 'STALE')

    def test_invalid_fields_fail_closed(self):
        cases = dict(value=[True, -1, float('nan'), float('inf'), '4'],
                     longitude=[181, None, True], latitude=[91, float('nan')],
                     source_sha256=['', 'x'*64, None], id=['', None],
                     source_url=['http://example.org', 'https://u:p@example.org'],
                     observed_at=['2026-10-23T12:01:00Z', '2026-10-23T11:59:00', None],
                     retrieved_at=['2026-10-22T00:00:00Z'], units=['TECU/min'],
                     metric=['OTHER'], quality=['good'], kind=['ESTIMATE'])
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    row = record(); row[field] = value
                    validate_record(row, NOW)

    def test_duplicates_and_missing_fields(self):
        with self.assertRaises(ValueError): validate_batch([record(), record()], NOW)
        with self.assertRaises(ValueError): validate_record({}, NOW)
        self.assertEqual(validate_batch([], NOW), [])

    def test_roti_requires_observation_window_and_method(self):
        row = record(); row.update(metric='ROTI', units='TECU/min')
        with self.assertRaises(ValueError): validate_record(row, NOW)
        row['kind'] = 'OBSERVATION'
        with self.assertRaises(ValueError): validate_record(row, NOW)
        row.update(window_seconds=300, method='fixture standard deviation of ROT')
        self.assertEqual(validate_record(row, NOW)['freshness'], 'FRESH')
        row['window_seconds'] = float('nan')
        with self.assertRaises(ValueError): validate_record(row, NOW)

    def test_audit_cannot_claim_live_pass(self):
        result = audit_status()
        self.assertEqual(result['state'], 'BLOCKED')
        self.assertIsNone(result['measurements'])
        self.assertFalse(any(result['claims'].values()))


class ApiTests(unittest.TestCase):
    def test_feature_flag(self):
        import os
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from server.backend.ionosphere_api import router
        app = FastAPI(); app.include_router(router)
        client = TestClient(app)
        with patch.dict(os.environ, {'AGUAYLUZ_IONOSPHERE_PREVIEW': '0'}):
            self.assertEqual(client.get('/ionosphere/status').status_code, 404)
        with patch.dict(os.environ, {'AGUAYLUZ_IONOSPHERE_PREVIEW': '1'}):
            self.assertEqual(client.get('/ionosphere/status').json()['state'], 'BLOCKED')
            self.assertEqual(client.post('/ionosphere/status').status_code, 405)
