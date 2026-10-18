from __future__ import annotations
import json
import os
import time
import httpx
from browser_cdp import Browser,ROOT

def main():
    user=os.getenv('MONITOR_DEMO_USERNAME','AQ20260001');password=os.getenv('MONITOR_DEMO_PASSWORD','123456')
    with httpx.Client(base_url='http://127.0.0.1:8010',timeout=20) as main_client,httpx.Client(base_url='http://127.0.0.1:8014',timeout=20) as monitor:
        original=main_client.get('/api/health').json()['data']
        login=main_client.post('/api/auth/login',json={'username':user,'password':password});login.raise_for_status()
        secret=login.json()['data']['token'];monitor.headers['Authorization']='Bearer '+secret;main_client.headers['Authorization']='Bearer '+secret
        try:
            health=monitor.get('/api/monitor-service/health').json()['data']
            response=monitor.post('/api/monitor/detect-all',json={'max_frames':8,'confidence':.5});response.raise_for_status()
            jobs=response.json()['data']['runs'];runs=[]
            for job in jobs:
                deadline=time.monotonic()+240
                while time.monotonic()<deadline:
                    run=monitor.get('/api/monitor/runs/'+job['id']).json()['data']
                    if run['status'] in {'done','error'}:break
                    time.sleep(.5)
                assert run['status']=='done',run
                frames=run['result']['frames'];assert len(frames)==8
                runs.append({'camera_id':job['camera_id'],'run_id':run['id'],'frames':len(frames),'confidence_threshold':run['result']['confidence_threshold'],'head_targets_per_sample':[f['helmet_on']+f['helmet_off'] for f in frames],'new_clues':run['result']['new_clues']})
                print(json.dumps(runs[-1],ensure_ascii=False),flush=True)
            overview=monitor.get('/api/monitor/overview').json()['data'];summary=monitor.get('/api/dashboard/summary').json()['data']['monitor_today']
            assert all(overview[k]==summary[k] for k in summary if k!='updated_at')
            after=main_client.get('/api/health').json()['data'];assert original==after
            b=Browser()
            try:
                b.call('Page.navigate',{'url':'http://127.0.0.1:8010/'})
                b.wait("typeof doLogin==='function'&&document.getElementById('lgUser').options[0]?.value==='AQ20260001'")
                b.login(user);b.js("go('p4');setMode('board')")
                b.wait('CAMS.length===4&&monitorLatest.length===4')
                assert b.js('monitorOrigin()')=='http://127.0.0.1:8014'
                for i in range(4):
                    b.js(f"switchCam({i});setMonitorView('result')")
                    b.wait("!document.getElementById('vwResult').hidden&&document.getElementById('vwResult').naturalWidth>0&&monitorFrameId===monitorFrames[CAMS[curCam].id]")
                    assert b.js("document.getElementById('monitorFrameSelect').options.length===8")
                    if i==2:
                        b.js("document.getElementById('vwVideo').closest('.vw-main').scrollIntoView({block:'center'})")
                        b.screenshot('monitor-live-CAM-03.png')
                b.js("go('p1')")
                b.wait("document.querySelector('[data-home-real]')!==null")
                assert b.js("Number(document.querySelector('[data-home-real]').dataset.homeReal)")==summary['real']['no_helmet']
                b.js("go('p2');ask('汇总今日监控线索并给出巡查建议')")
                b.wait("Array.from(document.querySelectorAll('.message-text')).at(-1)?.textContent.includes('今日真实 YOLO 安全帽线索')")
                assert not b.errors,b.errors
                b.js('toLogin()')
            finally:b.close()
            report={'original_service_health_before':original,'original_service_health_after':after,'original_service_unchanged':True,'monitor_service':health,'runs':runs,'summary':summary,'live_frontend_four_results_verified':True,'home_monitor_equal':True,'no_manual_confirmation_or_dismissal_performed':True}
            (ROOT/'artifacts/monitor-live-activation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'original_service_unchanged':True,'live_frontend_four_results_verified':True,'home_monitor_equal':True},ensure_ascii=False))
        finally:main_client.post('/api/auth/logout')

if __name__=='__main__':main()
