"""Record README demo GIF frames against an isolated demo database.

Requires a clean demo store started with APP_DB pointing at a database made by
`python -m scripts.prepare_seed`, e.g.:

    APP_DB=backend/data/gif-demo.db python -m uvicorn backend.app.main:app --port 8012

Frames are written under artifacts/tmp/gif-frames/ (gitignored) and assembled
into docs/assets/*.gif afterwards. Every step degrades gracefully: a failed
section is reported and skipped, so partial recordings still complete.
"""
from __future__ import annotations
import base64
import json
import os
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from browser_cdp import Browser

FRAMES=ROOT/'artifacts/tmp/gif-frames'
PORT=os.getenv('DEMO_PORT','8012')
GAP=float(os.getenv('DEMO_FRAME_GAP','0.5'))

def shot(b,stem):
    FRAMES.mkdir(parents=True,exist_ok=True)
    r=b.call('Page.captureScreenshot',{'format':'png'})
    (FRAMES/f'{stem}.png').write_bytes(base64.b64decode(r['data']))

def cap(b,stem,n,gap=GAP):
    for i in range(n):
        shot(b,f'{stem}_{i:03d}');time.sleep(gap)

def settle_cap(b,stem,condition,frames,gap=GAP,timeout=40):
    """Capture frames while polling a condition; stops early when met."""
    deadline=time.monotonic()+timeout;i=0
    while i<frames and time.monotonic()<deadline:
        shot(b,f'{stem}_{i:03d}');i+=1;time.sleep(gap)
        try:
            if b.js('Boolean('+condition+')'):break
        except Exception:pass
    return i

def main():
    steps=[]
    def mark(name,ok,detail=''):
        steps.append({'step':name,'ok':ok,'detail':detail});print(json.dumps(steps[-1],ensure_ascii=False),flush=True)
    b=Browser()
    try:
        b.goto(f'http://127.0.0.1:{PORT}/')
        cap(b,'01-login',4);mark('login-screen',True)
        b.login()
        b.wait("document.querySelectorAll('#p1 .wi').length>=4")
        cap(b,'02-dashboard',8);mark('dashboard',True)
    except Exception as e:
        mark('dashboard',False,str(e)[:200])
    try:
        b.js("go('p2')");time.sleep(1)
        cap(b,'03-chat',3)
        b.js("ask('基坑临边防护有什么要求')")
        settle_cap(b,'04-chat-stream',"document.querySelector('#chat .message-refs button')",10,timeout=45)
        cap(b,'05-chat-refs',6)
        b.click('#chat .message-refs button')
        b.wait("document.getElementById('mTitle').textContent==='资料详情'")
        cap(b,'06-chat-ref-detail',5)
        b.js("closeModal()");mark('chat',True)
    except Exception as e:
        mark('chat',False,str(e)[:200])
    try:
        b.js("go('p3')");time.sleep(1)
        for stem,f in [('07-ledger-all','all'),('08-ledger-heavy','heavy'),('09-ledger-light','light')]:
            b.js('filterHz('+json.dumps(f)+')');time.sleep(.6);cap(b,stem,4)
        b.js('viewHazard(1)')
        b.wait("document.getElementById('mTitle').textContent==='隐患详情与证据链'")
        cap(b,'10-ledger-detail',6)
        b.js('closeModal()');mark('ledger',True)
    except Exception as e:
        mark('ledger',False,str(e)[:200])
    try:
        b.js("go('p4');setMode('board');switchCam(0)")
        time.sleep(1.5);cap(b,'11-monitor-cam01',6)
        b.js('switchCam(2)');time.sleep(1.5);cap(b,'12-monitor-cam03',6)
        b.js('switchCam(3)');time.sleep(1.5);cap(b,'13-monitor-cam04',6)
        mark('monitor',True)
    except Exception as e:
        mark('monitor',False,str(e)[:200])
    try:
        b.js("go('p5')");time.sleep(1);cap(b,'14-kb',5);mark('kb',True)
    except Exception as e:
        mark('kb',False,str(e)[:200])
    finally:
        b.close()
    (ROOT/'artifacts/tmp/gif-record-summary.json').write_text(json.dumps(steps,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE '+json.dumps(steps,ensure_ascii=False))

if __name__=='__main__':
    main()
