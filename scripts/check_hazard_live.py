import json
from pathlib import Path
from browser_cdp import Browser

ROOT=Path(__file__).resolve().parents[1]

def main():
    ready=json.loads((ROOT/'artifacts/hazard-demo-ready.json').read_text(encoding='utf-8'))
    hid=ready['hazard_id']
    b=Browser()
    try:
        b.goto();b.wait("document.querySelectorAll('#lgUser option').length===1");b.login()
        b.js(f'goP6({hid})');b.wait(f'p6Hazard?.id==={hid}')
        assert b.js("document.querySelectorAll('#p6Work .cc-step').length===3")
        detail=b.js(f"api('/api/hazards/{hid}')")
        assert detail['status']=='待整改' and not detail['feedbacks'] and not detail['documents'] and not detail['attachments']
        assert detail['demo_feedback'] and not detail['demo_feedback']['received']
        b.screenshot('hazard-workflow-live.png')
        b.js('go("p3");viewHazard(1)');b.wait("document.getElementById('mTitle').textContent==='隐患详情与证据链'")
        assert b.js("document.getElementById('mBody').textContent.includes('已销项')")
        assert not b.errors,b.errors
        report={'result':'通过','demo_hazard_id':hid,'three_steps':True,'single_visible_identity':'王建国','fresh_case_not_started':True,'existing_closed_archive_readable':True,'browser_errors':b.errors}
        (ROOT/'artifacts/hazard-workflow-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
        b.js('toLogin()')
    finally:b.close()

if __name__=='__main__':main()
