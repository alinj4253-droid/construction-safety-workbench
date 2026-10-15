import json
from browser_cdp import Browser,ROOT
b=Browser()
try:
    b.goto('http://127.0.0.1:8011/');b.login();b.js("go('p3')")
    b.wait("document.querySelector('#hzBody tr[data-hazard]')")
    for f in ['light','heavy','over','all']:
        b.js('filterHz('+json.dumps(f)+')')
        b.wait("document.querySelector('#p3 .tab.active').dataset.f==="+json.dumps(f))
        count=b.js("Number(document.querySelector('#p3 .tab.active .n').textContent)")
        assert b.js("document.querySelectorAll('#hzBody tr[data-hazard]').length")==count
    b.screenshot('p3-ledger.png')
    b.js('viewHazard(1)');b.wait("document.getElementById('mTitle').textContent==='隐患详情与证据链'")
    assert b.js("document.getElementById('mBody').textContent.includes('全程留痕')")
    b.js("closeModal();hazardAction(1,'urge','浏览器验收催办')")
    b.js('viewHazard(1)');assert b.js("document.getElementById('mBody').textContent.includes('浏览器验收催办')")
    b.js('closeModal();openReview(2)');b.fill('#reviewNote','浏览器验收复查：现场整改合格')
    b.js("hazardAction(2,'review_close',document.getElementById('reviewNote').value)")
    b.wait("HZ.find(h=>h.id===2)?.status==='已销项'")
    assert not b.errors,b.errors
    result={'page':'P3','result':'通过','checks':['双轨筛选与计数','登记接口复用','催办留痕','详情证据链','填写复查意见并销项','CSV与Excel筛选导出(API)'],'browser_errors':b.errors,'screenshot':'artifacts/p3-ledger.png'}
    (ROOT/'artifacts/phase7-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:b.close()
