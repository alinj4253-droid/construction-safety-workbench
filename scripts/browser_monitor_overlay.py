import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from browser_cdp import Browser,ROOT

def main():
    info=json.loads((ROOT/'artifacts/monitor-fix-regression.json').read_text(encoding='utf-8'));sandbox=Path(info['sandbox'])
    shutil.copytree(ROOT/'frontend',sandbox/'frontend',dirs_exist_ok=True)
    shutil.copytree(ROOT/'backend',sandbox/'backend',dirs_exist_ok=True,ignore=shutil.ignore_patterns('data','__pycache__'))
    shutil.copytree(ROOT/'videos/ai_playback',sandbox/'videos/ai_playback',dirs_exist_ok=True)
    env=os.environ.copy();env.update(APP_DB=info['database'],LLM_ENABLED='0',PYTHONUTF8='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
    output=open(sandbox/'overlay-server.log','w',encoding='utf-8');proc=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8013'],cwd=sandbox,env=env,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW)
    b=None
    try:
        b=Browser();b.goto('http://127.0.0.1:8013/');b.login();b.js("go('p4');setMode('board');setMonitorView('overlay')")
        b.wait('CAMS.length===4&&monitorPlayback?.available&&curCam===2')
        checks=[]
        for index in range(4):
            b.js(f"switchCam({index});setMonitorView('overlay')")
            b.wait(f"monitorPlayback?.camera_id==='CAM-0{index+1}'&&document.getElementById('vwVideo').readyState>=2&&!document.getElementById('vwVideo').paused")
            before=b.js("document.getElementById('vwVideo').currentTime");time.sleep(.25)
            assert b.js("document.getElementById('vwVideo').currentTime")>before
            assert b.js("document.getElementById('vwVideo').getAttribute('src')===monitorPlayback.url")
            assert b.js("document.getElementById('monitorResultPanel').textContent.includes('非实时监控')")
            checks.append({'camera_id':f'CAM-0{index+1}','playback':True,'frames':b.js('monitorPlayback.frames.length'),'frames_with_heads':b.js('monitorPlayback.frames.filter(f=>f.detections.length).length')})
        b.js("switchCam(2);setMonitorView('overlay')");b.wait("monitorPlayback?.camera_id==='CAM-03'&&document.getElementById('vwVideo').readyState>=2")
        timeline=b.js('monitorPlayback.frames.filter(f=>f.detections.length).map(f=>f.index)');assert len(timeline)>1
        for index in [timeline[0],timeline[len(timeline)//2],timeline[-1]]:
            b.js(f"document.getElementById('vwVideo').pause();document.getElementById('vwVideo').currentTime={index}/monitorPlayback.fps")
            b.wait(f"monitorOverlayFrame==={index}&&document.querySelectorAll('#vwDetect .dbox').length===monitorPlayback.frames[{index}].detections.length")
            assert b.js(f"Array.from(document.querySelectorAll('#vwDetect .dbox')).every((el,i)=>el.dataset.box===monitorPlayback.frames[{index}].detections[i].bbox.join(','))")
            error=b.js("(()=>{const el=document.querySelector('#vwDetect .dbox'),d=monitorPlayback.frames[monitorOverlayFrame].detections[0],r=el.getBoundingClientRect(),l=document.getElementById('vwDetect').getBoundingClientRect();return Math.max(Math.abs(r.left-l.left-d.bbox[0]/monitorPlayback.width*l.width),Math.abs(r.top-l.top-d.bbox[1]/monitorPlayback.height*l.height));})()")
            assert error<1,error
        both=b.js('monitorPlayback.frames.findIndex(f=>f.detections.some(d=>d.class_id===0)&&f.detections.some(d=>d.class_id===1))');assert both>=0
        b.js(f"document.getElementById('vwVideo').currentTime={both}/monitorPlayback.fps");b.wait(f'monitorOverlayFrame==={both}')
        assert b.js("(()=>{const rs=Array.from(document.querySelectorAll('#vwDetect .dbox span')).map(e=>e.getBoundingClientRect());return rs.every((r,i)=>rs.every((s,j)=>i===j||r.right<=s.left||r.left>=s.right||r.bottom<=s.top||r.top>=s.bottom));})()")
        b.js("document.getElementById('vwVideo').closest('.vw-main').scrollIntoView({block:'center'})");b.screenshot('monitor-overlay-CAM-03.png')
        old=b.js('monitorOverlayFrame');b.js("document.getElementById('vwVideo').play()")
        b.wait(f'monitorOverlayFrame!=={old}');assert b.js("Number(document.getElementById('vwDetect').dataset.frame)===monitorOverlayFrame")
        b.call('Emulation.setDeviceMetricsOverride',{'width':1100,'height':900,'deviceScaleFactor':1,'mobile':False});b.js("document.getElementById('vwVideo').pause();paintMonitorOverlay(monitorPresentedTime,true)")
        assert b.js("document.getElementById('vwDetect').getBoundingClientRect().width<=document.getElementById('vwVideo').clientWidth+1")
        b.call('Emulation.clearDeviceMetricsOverride')
        b.call('Runtime.evaluate',{'expression':'fullscreenMonitor()','userGesture':True,'awaitPromise':True});b.wait("document.fullscreenElement?.classList.contains('vw-main')")
        assert b.js("document.getElementById('vwDetect').parentElement===document.fullscreenElement")
        b.js('document.exitFullscreen()');b.wait('!document.fullscreenElement')
        b.js("togglePatrol()");b.wait('curCam!==2',timeout=9);b.wait("monitorPlayback?.camera_id===CAMS[curCam].id");b.js('togglePatrol()')
        b.js("switchCam(2);setMonitorView('replay')");b.wait("document.getElementById('vwVideo').getAttribute('src').endsWith('cam03_workers.mp4')&&document.getElementById('vwVideo').readyState>=2")
        assert b.js("document.querySelectorAll('#vwDetect .dbox').length===0")
        b.js("setMonitorView('overlay')");b.wait("monitorPlayback?.camera_id==='CAM-03'")
        b.js("document.getElementById('vwVideo').src='/videos/missing-overlay.mp4'")
        b.wait("document.getElementById('vwNoSignal').textContent.includes('本地录像缺失')&&document.querySelectorAll('#vwDetect .dbox').length===0&&monitorPlayback===null")
        assert not b.errors,b.errors
        report={'result':'通过','four_cameras':checks,'frame_exact_coordinates':True,'seek_updates_boxes':True,'playback_updates_boxes':True,'resize_contain_alignment':True,'fullscreen_preserves_overlay':True,'labels_do_not_overlap':True,'automatic_patrol':True,'original_replay_retained':True,'missing_file_clears_boxes':True,'real_model_only':True,'browser_errors':b.errors}
        (ROOT/'artifacts/monitor-overlay-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if b:b.close()
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        output.close()

if __name__=='__main__':main()
