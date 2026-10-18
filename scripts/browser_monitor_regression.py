from __future__ import annotations
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
import httpx
from browser_cdp import Browser,ROOT

def main():
    report=json.loads((ROOT/'artifacts/monitor-fix-regression.json').read_text(encoding='utf-8'))
    sandbox=Path(report['sandbox'])
    shutil.copytree(ROOT/'frontend',sandbox/'frontend',dirs_exist_ok=True)
    shutil.copytree(ROOT/'backend',sandbox/'backend',dirs_exist_ok=True,ignore=shutil.ignore_patterns('data','__pycache__'))
    env=os.environ.copy();env.update(APP_DB=report['database'],LLM_ENABLED='0',PYTHONUTF8='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
    output=open(sandbox/'browser-server.log','w',encoding='utf-8')
    proc=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8013'],cwd=sandbox,env=env,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW)
    b=None
    try:
        b=Browser();b.goto('http://127.0.0.1:8013/');b.login();b.js("go('p4');setMode('board')")
        b.wait('CAMS.length===4&&monitorLatest.length===4')
        before=b.js('monitorLatest.map(x=>x.latest.id)')
        b.click('[onclick="runDetection(true)"]')
        b.wait('monitorLatest.some(x=>["queued","running"].includes(x.latest?.status))')
        assert b.js('Array.from(document.querySelectorAll("[data-detect]")).every(x=>x.disabled)')
        b.wait('monitorLatest.length===4&&monitorLatest.every(x=>x.latest?.status==="done"&&!'+json.dumps(before)+'.includes(x.latest.id))',timeout=180)
        checks=[]
        for i in range(4):
            b.js(f"switchCam({i});setMonitorView('result')")
            b.wait("!document.getElementById('vwResult').hidden&&document.getElementById('vwResult').naturalWidth>0&&monitorFrameId===monitorFrames[CAMS[curCam].id]")
            assert b.js("document.getElementById('monitorFrameSelect').options.length===8")
            assert b.js("document.getElementById('monitorResultPanel').textContent.includes('真实 YOLO 检测结果')")
            assert b.js("document.getElementById('vwVideo').paused")
            frame=b.js("({camera:CAMS[curCam].id,frame_id:monitorFrameId,text:document.getElementById('monitorResultPanel').textContent})")
            checks.append(frame)
            b.js("document.getElementById('vwVideo').closest('.vw-main').scrollIntoView({block:'center'})")
            b.screenshot(f'monitor-browser-CAM-0{i+1}.png')
            b.js("setMonitorView('replay')")
            b.wait("document.getElementById('vwVideo').readyState>=2&&!document.getElementById('vwVideo').paused")
            b.js("document.getElementById('vwVideo').currentTime=2")
            b.js('load_p4()')
            assert b.js("document.getElementById('vwVideo').currentTime>=1.9")
        b.js("switchCam(2);setMonitorView('result')")
        b.wait("!document.getElementById('vwResult').hidden")
        b.js("document.getElementById('monitorFrameSelect').selectedIndex=0;selectMonitorFrame(Number(document.getElementById('monitorFrameSelect').value))")
        b.wait("monitorFrameId===Number(document.getElementById('monitorFrameSelect').value)")
        b.js("document.getElementById('vwResult').src='/missing-detection-image.jpg'")
        b.wait("document.getElementById('vwNoSignal').textContent.includes('检测图片无法显示')")
        b.js("setMonitorView('replay');document.getElementById('vwVideo').src='/videos/not-existing.mp4'")
        b.wait("document.getElementById('vwNoSignal').textContent.includes('本地录像缺失')")
        b.js('switchCam(2)')
        b.wait("document.getElementById('vwVideo').readyState>=2")
        b.js("togglePatrol()")
        assert b.js('patrolT!==null')
        b.js('togglePatrol()');assert b.js('patrolT===null')
        b.js("go('p1')")
        b.wait("document.querySelector('[data-home-real]')!==null")
        previous=b.js("api('/api/monitor/overview').then(x=>x.real.no_helmet)")
        pending=b.js("api('/api/monitor/snapshots').then(xs=>xs.find(x=>x.data_mode==='yolo')?.id)")
        assert pending
        b.js(f"api('/api/monitor/snapshots/{pending}/dismiss','POST',{{note:'浏览器隔离环境：验证其他操作后的首页自动同步'}})")
        b.wait(f"Number(document.querySelector('[data-home-real]').dataset.homeReal)==={previous-1}",timeout=15)
        b.screenshot('monitor-home-sync.png')
        b.js("monitorRoutePromise=Promise.resolve('http://127.0.0.1:65530');load_p1()")
        b.wait("document.querySelector('#p1 .grid > .card:nth-child(2)').textContent.includes('监控统计暂不可用')")
        assert b.js("document.querySelector('#p1 .stat-num').textContent.length>0")
        b.js("monitorRoutePromise=Promise.resolve('');load_p1();go('p4');setMode('board');setMonitorView('result')")
        b.wait("!document.getElementById('vwResult').hidden")
        b.js("go('p2');ask('汇总今日监控线索并给出巡查建议')")
        b.wait("Array.from(document.querySelectorAll('.message-text')).at(-1)?.textContent.includes('今日真实 YOLO 安全帽线索')")
        assert b.js("!Array.from(document.querySelectorAll('.message-text')).at(-1).textContent.includes('人次')")
        b.call('Page.reload',{'ignoreCache':True})
        b.wait("typeof doLogin==='function'&&document.querySelector('#p1 .page-head .d').textContent.includes('2026-')")
        b.js("go('p4');setMode('board');setMonitorView('result')")
        b.wait("monitorLatest.length===4&&!document.getElementById('vwResult').hidden&&document.getElementById('vwResult').naturalWidth>0")
        assert not b.errors,b.errors
        result={'result':'通过','four_video_replay':True,'four_real_detection_display':True,'serial_batch_buttons':True,'frame_selection':True,'refresh_preserves_playback':True,'page_reload_restores_results':True,'home_auto_sync_after_dismiss':True,'missing_image_fallback':True,'missing_video_fallback':True,'monitor_service_failure_keeps_other_home_data':True,'monitor_narrative_consistent':True,'browser_errors':b.errors,'camera_evidence':checks}
        (ROOT/'artifacts/monitor-browser-regression.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='camera_evidence'},ensure_ascii=False))
    finally:
        if b:b.close()
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        output.close()

if __name__=='__main__':main()
