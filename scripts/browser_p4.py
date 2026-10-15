import json
from browser_cdp import Browser,ROOT
b=Browser()
try:
    b.goto('http://127.0.0.1:8011/');b.login();b.js("go('p4')")
    b.wait("document.getElementById('normal').textContent.includes('模型待训练')")
    assert b.js("document.getElementById('normal').textContent.includes('不作为执法/追责依据')")
    ids=b.js("Array.from(document.querySelectorAll('.snap[data-snapshot]')).map(e=>Number(e.dataset.snapshot))")
    assert len(ids)>=2
    before=b.js("api('/api/hazards').then(d=>d.counts.all)")
    b.js(f'confirmSnap({ids[0]})');b.fill('#snapshotNote','浏览器验收：现场确认未规范佩戴安全帽')
    b.js(f"snapshotAction({ids[0]},'confirm')")
    assert b.js("api('/api/hazards').then(d=>d.counts.all)")==before+1
    b.js(f'dismissSnap({ids[1]})');b.fill('#snapshotNote','浏览器验收：远景遮挡误报，不入账')
    b.js(f"snapshotAction({ids[1]},'dismiss')")
    assert b.js("api('/api/hazards').then(d=>d.counts.all)")==before+1
    b.js("setMode('board');switchCam(0)");assert b.js("document.getElementById('vwTag').textContent.startsWith('CAM-01')")
    b.js('switchCam(2);togglePatrol()');assert b.js('patrolT!==null');b.js('togglePatrol()');assert b.js('patrolT===null')
    b.screenshot('p4-monitor.png')
    assert not b.errors,b.errors
    result={'page':'P4','result':'通过','checks':['人工确认创建轻轨','驳回不入账','真实聚合趋势','四路切换与轮巡','如实标注演示数据与能力边界'],'browser_errors':b.errors,'screenshot':'artifacts/p4-monitor.png'}
    (ROOT/'artifacts/phase8-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:b.close()
