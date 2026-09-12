"""Controlled dependency-fault simulation in a disposable subprocess only."""
import importlib.util, json, struct, sys, tempfile, faulthandler, hashlib
from pathlib import Path
import zoneinfo
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('reviewed_module',ROOT/'research/mycelial/consistency_v2.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rows=json.loads((ROOT/'tests/fixtures/mycelial_consistency/v2/examples.json').read_text())['records']
case=sys.argv[1]
def hdr(version=b'\0',typecnt=1,charcnt=4):return b'TZif'+version+b'\0'*15+struct.pack('>6I',0,0,0,0,typecnt,charcnt)
body=struct.pack('>lbb',0,0,0)+b'UTC\0'
sources={'empty':b'', 'bad_magic':b'BAD!', 'short_header':b'TZif\0', 'short_body':hdr(), 'valid_v1':hdr()+body, 'valid_v2':hdr(b'2')+body+hdr(b'2')+body+b'\nUTC0\n', 'v2_missing_footer_end':hdr(b'2')+body+hdr(b'2')+body+b'\nUTC0','v2_invalid_footer_start':hdr(b'2')+body+hdr(b'2')+body+b'X'}
with tempfile.TemporaryDirectory(prefix='aguayluz_tzif_review_', dir=sys.argv[2] if len(sys.argv)>2 else None) as td:
 d=Path(td)/'Review';d.mkdir();(d/'Zone').write_bytes(sources[case]);zoneinfo.reset_tzpath([td])
 row=rows[4];row['timezone']='Review/Zone'
 print(json.dumps({'stage':'before_check_bytes','case':case,'resource_bytes':len(sources[case]),'resource_sha256':hashlib.sha256(sources[case]).hexdigest()}),file=sys.stderr,flush=True)
 faulthandler.dump_traceback_later(1.5)
 try:out={'case':case,'fault_kind':'SIMULATED_LOCAL_TZIF_RESOURCE','result':m.check_bytes(json.dumps(row).encode())}
 except Exception as exc:out={'case':case,'fault_kind':'SIMULATED_LOCAL_TZIF_RESOURCE','exception_type':type(exc).__name__,'exception_module':type(exc).__module__}
 faulthandler.cancel_dump_traceback_later()
 print(json.dumps(out))
