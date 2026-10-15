import json,time,uuid
from browser_cdp import Browser,ROOT
b=Browser()
try:
    b.goto('http://127.0.0.1:8011/');b.login();b.js("go('p5')")
    b.wait("Number(document.getElementById('kbStatNum').textContent)>=76")
    b.js("kbTypeChip('法规依据')");assert b.js("KB.every(s=>s.category==='法规依据')")
    b.js("kbStChip('现行')");assert b.js("KB.every(s=>s.status==='现行')")
    b.fill('#kbQ','JGJ 80');b.wait("KB.length>0 && KB.every(s=>s.doc_no.includes('80'))")
    b.js("kbDetail(KB[0].id)");b.wait("document.getElementById('mBody').textContent.includes('旧强制性条文已废止')")
    b.js('closeModal();openKbModal()')
    marker='浏览器核验-'+uuid.uuid4().hex[:8]
    b.fill('#kbName',marker);b.js("document.getElementById('kbType').value='项目资料'");b.fill('#kbNo',marker)
    path=ROOT/'artifacts/tmp/kb-browser.txt';path.parent.mkdir(exist_ok=True)
    path.write_text('第一条 '+marker+'红杉围挡巡检应登记检查时间、人员、现场地点、发现事项与整改结果。第二条 围挡检查记录应按项目要求留存。第三条 对检查发现的围挡损坏，由项目负责人安排维修，安全员复查记录实际整改结果。',encoding='utf-8')
    doc=b.call('DOM.getDocument');node=b.call('DOM.querySelector',{'nodeId':doc['root']['nodeId'],'selector':'#kbFile'})['nodeId'];b.call('DOM.setFileInputFiles',{'nodeId':node,'files':[str(path)]})
    b.js('submitKb()');b.wait(f"KB.some(s=>s.name==={json.dumps(marker)})")
    sid=b.js(f"KB.find(s=>s.name==={json.dumps(marker)}).id")
    assert b.js(f"KB.find(s=>s.id==={sid}).status==='待核验'")
    b.js(f'confirmKb({sid})');b.fill('#kbReviewNote','浏览器验收合成项目资料，原文与元数据一致');b.js("document.getElementById('kbReviewed').checked=true;submitKbConfirm("+str(sid)+")")
    assert b.js(f"KB.find(s=>s.id==={sid}).status==='现行'")
    b.js("kbTab('gov');checkUpdate2()");b.wait("document.getElementById('kbUpProg').textContent.includes('人工登记')")
    logs=b.js("api('/api/kb/changelog')");log=next(x for x in logs if x['source_id']==sid and x['action']=='confirm_source')
    b.js(f"kbUndoModal({log['id']})");b.fill('#kbUndoNote','浏览器验收撤销核验');b.js(f"kbRollback({log['id']})")
    assert b.js(f"api('/api/kb/sources/{sid}').then(s=>s.status==='待核验')")
    b.js("kbTab('browse');document.getElementById('kbQ').value='';kbType='';kbStatus='';load_p5()")
    b.screenshot('p5-knowledge.png');assert not b.errors,b.errors
    result={'page':'P5','result':'通过','checks':['类型状态关键词筛选','条款废止标签','上传待核验','人工核验生效','登记版本关系检查','变更日志与撤销'],'source_id':sid,'browser_errors':b.errors,'screenshot':'artifacts/p5-knowledge.png'}
    (ROOT/'artifacts/phase9-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:b.close()
