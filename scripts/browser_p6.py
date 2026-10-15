import json
from datetime import date,timedelta
from browser_cdp import Browser,ROOT
b=Browser()
try:
    b.goto('http://127.0.0.1:8011/');b.login();b.js("go('p3');openHzModal()")
    for selector,value in [('#hzD','浏览器验收 5#楼临边防护缺失，坠落高度3m'),('#hzW','验收木工班组'),('#hzPerson','验收安全责任人'),('#hzDl',str(date.today()+timedelta(days=3))),('#hzLoc','5#楼二层')]:b.fill(selector,value)
    b.js('submitHz()');b.wait("!document.getElementById('mask').classList.contains('on')")
    hid=b.js('selectedHazard');b.js('goP6('+str(hid)+')')
    b.wait("document.getElementById('p6Work').textContent.includes('开始智能办理')")
    b.js('p6Start()');b.wait("p6Task?.status==='pending_human'",timeout=30)
    assert b.js("document.getElementById('p6Work').textContent.includes('AI 检查未发现阻断问题，待人工确认')")
    assert not b.js("document.getElementById('p6Work').textContent.includes('复核通过')")
    assert b.js("p6Task.steps.some(s=>s.name==='Agent B 独立复核')")
    b.screenshot('p6-handling.png')
    did=b.js('p6Task.document_id');b.js('saveDraft('+str(did)+')')
    before=b.js("api('/api/hazards').then(d=>d.counts.all)")
    b.js('p6Sign()');assert b.js("document.getElementById('mTitle').textContent==='人工确认签发'")
    b.js('issuePendingDocument('+str(did)+')');b.wait("p6Task?.status==='issued'")
    assert b.js("api('/api/hazards').then(d=>d.counts.all)")==before
    b.js('p6Feedback()');b.fill('#feedbackNote','已按原文及现场方案完成防护安装，申请现场复查')
    b.js(f"hazardAction({hid},'submit_rectify',document.getElementById('feedbackNote').value)")
    b.wait("p6Hazard.status==='待复查'")
    assert not b.errors,b.errors
    result={'page':'P6','result':'通过','checks':['真实双角色交接','规则与复核意见落库','人工签发二次确认','签发不重复新增隐患','保存草稿','提交实际整改反馈','无复核通过误导文案'],'hazard_id':hid,'document_id':did,'browser_errors':b.errors,'screenshot':'artifacts/p6-handling.png'}
    (ROOT/'artifacts/phase6-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:b.close()
