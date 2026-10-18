import json
import os
from pathlib import Path
import sys
import httpx
from browser_cdp import Browser,ROOT

sys.path.insert(0,str(ROOT))

def main():
    from backend.app import db
    from scripts.reset_demo import ro,table_digest,KNOWLEDGE
    from contextlib import closing
    initialization=json.loads((ROOT/'artifacts/demo-initialization.json').read_text(encoding='utf-8'))
    with closing(ro(Path(initialization['backup'])/'database.db')) as source,closing(ro(db.db_path())) as target:
        preserved={table:table_digest(source,table)==table_digest(target,table) for table in KNOWLEDGE}
        assert all(preserved.values())
    with httpx.Client(base_url='http://127.0.0.1:8010',timeout=20) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':os.getenv('SAFETY_DEMO_PASSWORD','123456')}).json()['data']['token']
        try:
            assert not c.get('/api/sessions').json()['data']
            memory=c.get('/api/memory').json()['data'];assert not memory['long_term'] and not memory['summaries']
            h=c.get('/api/hazards/1').json()['data'];assert h['status']=='待整改' and not h['documents'] and not h['feedbacks'] and not h['attachments']
            assert all(h['is_demo'] for h in c.get('/api/hazards').json()['data']['items'])
            assert not c.get('/api/handle/tasks?hazard_id=1').json()['data']
            snaps=c.get('/api/monitor/snapshots?status=all').json()['data'];assert len(snaps)==2 and all(s['status']=='pending' and s['data_mode']=='demo' for s in snaps)
            overview=c.get('/api/monitor/overview').json()['data'];assert overview['real']['violations']==0
            knowledge=c.get('/api/kb/sources').json()['data']['stats']
        finally:c.post('/api/auth/logout')
    b=Browser()
    try:
        b.call('Page.addScriptToEvaluateOnNewDocument',{'source':"localStorage.setItem('safety_demo_generation','old');localStorage.setItem('safety_session_1','old-session');localStorage.setItem('safety_run_1','old-run');"})
        b.goto();b.wait("localStorage.getItem('safety_demo_generation')!=='old'");b.login()
        assert b.js("localStorage.getItem('safety_session_1')===null&&localStorage.getItem('safety_run_1')===null")
        b.js("go('p2')");b.wait("document.getElementById('sessCnt').textContent==='0 条'")
        b.js('goP6(1)');b.wait("p6Hazard?.id===1&&p6Task===null")
        assert b.js("document.querySelectorAll('#p6Work .cc-step').length===3")
        b.screenshot('demo-initial-handling.png')
        b.js("go('p4');setMode('board');setMonitorView('overlay')");b.wait("monitorPlayback?.camera_id==='CAM-03'&&document.getElementById('vwVideo').readyState>=2")
        index=b.js('monitorPlayback.frames.findIndex(f=>f.detections.some(d=>d.class_id===0)&&f.detections.some(d=>d.class_id===1))')
        assert index>=0
        b.js(f"document.getElementById('vwVideo').pause();document.getElementById('vwVideo').currentTime={index}/monitorPlayback.fps")
        b.wait(f"monitorOverlayFrame==={index}&&document.querySelectorAll('#vwDetect .dbox').length>=2")
        b.js("document.getElementById('vwVideo').closest('.vw-main').scrollIntoView({block:'center'})");b.screenshot('demo-initial-monitor.png')
        b.js("go('p1')");b.wait("document.querySelector('[data-home-real]')?.dataset.homeReal==='0'")
        assert not b.errors,b.errors
        b.js('toLogin()')
    finally:b.close()
    report={'result':'通过','generation':initialization['generation'],'knowledge_unchanged':preserved,'knowledge_stats':knowledge,'chat_sessions':0,'long_term_memories':0,'documents':0,'case_1_not_started':True,'pending_simulated_monitor_clues':2,'old_browser_state_cleared':True,'cam03_green_and_orange_real_boxes':True,'browser_errors':[]}
    (ROOT/'artifacts/demo-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
