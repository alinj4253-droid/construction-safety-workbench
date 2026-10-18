from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from browser_cdp import Browser,ROOT

def main():
    three='--three-steps' in sys.argv
    result=json.loads((ROOT/'artifacts/hazard-workflow-verification.json').read_text(encoding='utf-8'))
    sandbox=Path(result['sandbox'])
    for directory in ('backend','frontend'):shutil.copytree(ROOT/directory,sandbox/directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('data','__pycache__'))
    env=os.environ.copy();env.update(APP_DB=result['database'],LLM_ENABLED='0',PYTHONUTF8='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
    log=open(sandbox/'workflow-browser-server.log','w',encoding='utf-8')
    proc=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8013'],cwd=sandbox,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    b=None
    def capture(name):
        b.wait("!document.getElementById('mask').classList.contains('on')||!document.getElementById('mask').getAnimations({subtree:true}).some(a=>a.playState==='running'&&a.effect.getTiming().iterations!==Infinity)")
        b.screenshot(name)
    try:
        b=Browser();b.goto('http://127.0.0.1:8013/');b.login()
        if three:
            assert b.js("document.querySelector('#lgUser').options.length===1&&document.querySelector('#lgUser').options[0].textContent.includes('王建国')")
            b.js("go('p6')");b.wait("document.getElementById('p6Register')!==null")
            b.click('#p6Register');b.wait("document.getElementById('p3').classList.contains('active')&&document.getElementById('hzD')!==null")
            b.js('closeModal()')
        b.js("go('p3')");b.wait("document.querySelector('#hzBody tr[data-hazard]')")
        initial_max=b.js("api('/api/hazards').then(x=>Math.max(...x.items.map(h=>h.id)))")
        b.click('[onclick="prepareDemoModal()"]');b.click('#prepareDemoButton')
        b.wait(f"p6Hazard?.is_demo&&p6Hazard.id===selectedHazard&&p6Hazard.id>{initial_max}&&document.querySelector('#p6Work [onclick=\"p6Start()\"]')")
        hid=b.js('p6Hazard.id')
        if three:assert b.js("document.querySelectorAll('#p6Work .cc-step').length===3")
        before=b.js("api('/api/hazards').then(x=>x.counts.all)")
        b.js('p6Start()');b.wait("p6Task?.status==='pending_human'",timeout=60)
        assert b.js("p6Task.steps.some(x=>x.name==='Agent B 独立复核')")
        did=b.js('p6Task.document_id')
        capture('hazard-workflow-handling.png')
        b.js('p6Sign()');b.wait("document.getElementById('mTitle').textContent==='人工确认签发'")
        b.click('#mFoot button.primary');b.wait("p6Task?.status==='issued'")
        assert b.js("api('/api/hazards').then(x=>x.counts.all)")==before
        if three:
            assert b.js("!document.querySelector('#p6Work [onclick*=p6Feedback]')&&!document.querySelector('#p6Work [onclick*=openReview]')")
            assert b.js("document.querySelectorAll('#p6Work .cc-step').length===3")
        word=b.js(f"fetch('/api/documents/{did}/export',{{headers:{{Authorization:'Bearer '+token}}}}).then(async r=>({{ok:r.ok,signature:Array.from(new Uint8Array(await r.arrayBuffer()).slice(0,2))}}))")
        assert word['ok'] and word['signature']==[80,75]
        if three:
            b.click(f'#p6Work [onclick="goLedger({hid})"]')
            b.wait("document.getElementById('p3').classList.contains('active')")
        b.js(f"go('p3');rectifyModal({hid})")
        b.wait("document.getElementById('mTitle').textContent==='登记整改反馈'")
        assert b.js("document.getElementById('mBody').textContent.includes('演示模拟数据，不代表真实班组提交')&&document.getElementById('mBody').textContent.includes('暂无整改证据')")
        assert b.js("document.querySelector('#rectifyNote')===null")
        capture('hazard-workflow-feedback.png')
        b.click('#receiveFeedbackButton');b.wait(f"HZ.find(x=>x.id==={hid})?.status==='待复查'&&!document.getElementById('mask').classList.contains('on')")
        assert b.js(f"api('/api/hazards/{hid}').then(h=>h.review_note===null&&h.closed_at===null)")
        b.js(f'openReview({hid})');b.wait("document.getElementById('mTitle').textContent==='复查销项'")
        assert b.js("document.getElementById('mBody').textContent.includes('木工班组已完成3#楼东侧基坑临边防护整改')&&document.getElementById('mBody').textContent.includes('王建国')&&document.getElementById('mBody').textContent.includes('暂无整改证据')")
        b.fill('#reviewNote','整改合格');capture('hazard-workflow-review.png')
        b.click('#mFoot button.primary');b.wait(f"HZ.find(x=>x.id==={hid})?.status==='已销项'&&document.getElementById('mTitle').textContent==='隐患详情与证据链'")
        archived=b.js(f"api('/api/hazards/{hid}')")
        assert archived['review_note']=='整改合格' and archived['feedbacks'][0]['is_simulated']
        assert {'submit_rectify','review_close'}.issubset({x['action'] for x in archived['events']})
        capture('hazard-workflow-archive.png')
        b.js(f"closeModal();goP6({hid})");b.wait(f"p6Hazard?.id!=={hid}&&!document.querySelector('#p6Queue [onclick=\"p6Sel({hid})\"]')")
        previous_max=b.js("api('/api/hazards').then(x=>Math.max(...x.items.map(h=>h.id)))")
        b.js("go('p3');prepareDemoModal()");b.click('#prepareDemoButton');b.wait(f'p6Hazard?.is_demo&&p6Hazard.id===selectedHazard&&p6Hazard.id>{previous_max}')
        repeat=b.js('p6Hazard.id');assert b.js(f"api('/api/hazards/{hid}')")==archived
        real=b.js("api('/api/hazards','POST',{title:'浏览器隔离测试：临时用电整改反馈',track:'heavy',responsible_team:'电工班组'})")
        rid=real['id'];b.js(f"api('/api/hazards/{rid}/actions','POST',{{action:'start_rectify'}})")
        b.js(f"go('p3');rectifyModal({rid})");b.wait("document.getElementById('rectifyNote')!==null")
        assert b.js("document.getElementById('rectifyNote').value===''&&!document.getElementById('mBody').textContent.includes('木工班组已完成')")
        b.fill('#rectifyNote','电工班组提供反馈：接地连接已重新固定');b.fill('#feedbackProvider','班组联系人（隔离测试）')
        doc=b.call('DOM.getDocument')['root']['nodeId'];node=b.call('DOM.querySelector',{'nodeId':doc,'selector':'#feedbackEvidenceFile'})['nodeId']
        b.call('DOM.setFileInputFiles',{'nodeId':node,'files':[str(sandbox/'artifacts/p1-dashboard.png')]})
        b.click('#receiveFeedbackButton');b.wait(f"HZ.find(x=>x.id==={rid})?.status==='待复查'")
        b.js(f'openReview({rid})');b.wait("document.querySelector('#rectifyEvidenceList img')?.naturalWidth>0")
        assert b.js("document.getElementById('mBody').textContent.includes('安全员代录班组反馈')")
        capture('hazard-workflow-review-evidence.png')
        b.fill('#reviewNote','现场复查发现连接仍有松动，退回整改');b.click('#mFoot button:nth-child(2)')
        b.wait(f"HZ.find(x=>x.id==={rid})?.status==='整改中'")
        b.js(f'rectifyModal({rid})');b.wait("document.getElementById('rectifyNote')!==null")
        assert b.js("document.getElementById('rectifyNote').value===''")
        b.fill('#rectifyNote','班组第二次反馈：连接重新固定完成');b.click('#receiveFeedbackButton')
        b.wait(f"HZ.find(x=>x.id==={rid})?.status==='待复查'")
        b.js(f'openReview({rid})');b.wait("document.getElementById('reviewNote')!==null")
        assert b.js("document.querySelectorAll('[data-feedback]').length===2")
        b.fill('#reviewNote','整改合格');b.click('#mFoot button.primary')
        b.wait(f"HZ.find(x=>x.id==={rid})?.status==='已销项'")
        if three:
            ids=b.js("api('/api/hazards?filter=heavy').then(x=>x.items.filter(h=>!['已销项','已闭环'].includes(h.status)).slice(0,2).map(h=>h.id))")
            assert len(ids)==2
            first,second=ids
            b.js(f"closeModal();go('p6');window.workflowOriginalFetch=window.fetch;window.fetch=(url,options)=>url==='/api/hazards/{first}'?new Promise(resolve=>{{window.releaseWorkflowSelection=()=>resolve(window.workflowOriginalFetch(url,options));}}):window.workflowOriginalFetch(url,options);window.workflowStaleSelection=p6Sel({first});true")
            b.wait("typeof window.releaseWorkflowSelection==='function'")
            b.js(f'p6Sel({second})');b.wait(f'p6Hazard?.id==={second}&&selectedHazard==={second}')
            b.js('releaseWorkflowSelection();workflowStaleSelection.then(()=>true)')
            assert b.js(f'p6Hazard.id==={second}&&selectedHazard==={second}')
            b.js('window.fetch=window.workflowOriginalFetch')
        assert not b.errors,b.errors
        report={'result':'通过','three_steps':three,'demo_hazard_id':hid,'document_id':did,'repeat_demo_id':repeat,'ordinary_hazard_id':rid,'dual_agent_issue_feedback_review_archive':True,'simulation_labeled_and_no_fake_images':True,'normal_feedback_initially_blank':True,'recorded_by_wang_not_team_account':True,'rectification_image_preview':True,'return_and_second_feedback':True,'closed_record_removed_from_queue':True,'repeat_demo_preserves_archive':True,'word_export':True,'stale_selection_ignored':three,'browser_errors':b.errors}
        (ROOT/'artifacts/hazard-workflow-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if b:b.close()
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        log.close()

if __name__=='__main__':main()
