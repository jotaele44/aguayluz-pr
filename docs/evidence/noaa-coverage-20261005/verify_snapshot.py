"""Offline audit verification only; no acquisition or production side effects."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED = {'TJSJ', 'TJBQ', 'TJPS', 'TJRV', 'TJIG', 'TJVQ', 'TJCP', 'TJMZ'}
found = {key: set() for key in ('stationinfo', 'metar', 'taf')}
requests = {key: set() for key in found}
rows_by_kind = {key: [] for key in found}
payload_count = 0
for parent in (ROOT, ROOT / 'mayaguez-supplement'):
    receipt = json.loads((parent / 'receipt.json').read_text())
    for item in receipt['snapshots']:
        data = (parent / item['payload_file']).read_bytes()
        assert len(data) == item['bytes']
        assert hashlib.sha256(data).hexdigest() == item['sha256']
        assert item['identity'] == 'BYTE' and item['certification'] == 'OPEN'
        payload_count += 1
        kind = item['key']
        if kind not in found:
            continue
        # Parse query identifiers explicitly, including successful 204 responses.
        from urllib.parse import parse_qs, urlparse
        requested = set(parse_qs(urlparse(item['url']).query)['ids'][0].split(','))
        assert not requests[kind] & requested
        requests[kind].update(requested)
        assert item['http_status'] in (200, 204)
        rows = json.loads(data) if item['http_status'] == 200 else []
        assert isinstance(rows, list)
        ids = [row['icaoId'] for row in rows]
        assert len(ids) == len(set(ids))
        assert set(ids) <= requested
        assert not found[kind] & set(ids)
        found[kind].update(ids)
        rows_by_kind[kind].extend(rows)
        assert len(requested) == len(ids) + len(requested - set(ids))
        if item['http_status'] == 204:
            assert data == b''
        for row in rows:
            assert -90 <= row['lat'] <= 90 and -180 <= row['lon'] <= 180
        at = datetime.fromisoformat(item['retrieved_utc']).timestamp()
        for row in rows:
            if kind == 'metar':
                assert isinstance(row['obsTime'], (int, float)) and row['obsTime'] <= at
            if kind == 'taf':
                assert row['validTimeFrom'] < row['validTimeTo']
                assert row['validTimeFrom'] <= at < row['validTimeTo']
for kind in found:
    assert requests[kind] == EXPECTED
point = json.loads((ROOT / 'nws_point.raw').read_bytes())
forecast = json.loads((ROOT / 'nws_forecast.raw').read_bytes())
assert point['properties']['forecast'] == 'https://api.weather.gov/gridpoints/SJU/169,124/forecast'
periods = forecast['properties']['periods']
assert len({row['number'] for row in periods}) == len(periods)
for row in periods:
    assert datetime.fromisoformat(row['startTime']) < datetime.fromisoformat(row['endTime'])
for left, right in zip(periods, periods[1:]):
    assert datetime.fromisoformat(left['endTime']) == datetime.fromisoformat(right['startTime'])
a, b = found['metar'], found['taf']
result = {
    'scope': 'Frozen eight-ICAO registry query and one NWS point; not island-wide availability',
    'verification': 'PASS', 'certification': 'OPEN', 'payload_hashes_verified': payload_count,
    'products': {k: {'requested': len(EXPECTED), 'returned': len(v), 'not_returned': sorted(EXPECTED-v)} for k,v in found.items()},
    'metar_taf_sets': {'intersection': sorted(a&b), 'metar_only': sorted(a-b), 'taf_only': sorted(b-a), 'union': sorted(a|b), 'symmetric_difference': sorted(a^b)},
    'nws_forecast_periods': len(periods),
    'station_rows': [{'icao': i, **{k: i in v for k,v in found.items()}} for i in sorted(EXPECTED)],
}
print(json.dumps(result, indent=2))
