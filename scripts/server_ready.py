import hashlib,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
def wait_backend(port=8010,timeout=90):
    expected=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'backend').rglob('*.py')))).hexdigest()[:16]
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            r=httpx.get(f'http://127.0.0.1:{port}/api/health',timeout=2)
            if r.json()['data'].get('build')==expected:return
        except Exception:pass
        time.sleep(.2)
    raise RuntimeError('backend did not reload to the expected source version')
