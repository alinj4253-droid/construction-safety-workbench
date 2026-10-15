import json
from browser_cdp import Browser,ROOT
b=Browser()
try:
    b.goto('http://127.0.0.1:8011/')
    assert b.js("document.getElementById('loginGate').classList.contains('on')")
    b.js("document.querySelector('#loginGate input[type=password]').value='wrong';doLogin()")
    assert b.js("document.getElementById('loginGate').classList.contains('on')")
    b.login();b.js("go('p2')");b.wait("typeof curSessId!=='undefined'")
    b.js("ask('记住，身份回归测试背景仅属于王建国')");b.wait('!chatBusy')
    own=b.js('curSessId');assert own
    b.call('Page.reload');b.wait("typeof CUR_USER!=='undefined' && CUR_USER?.id===1")
    b.js("go('p2')");b.wait(f"curSessId==='{own}'")
    b.js('toLogin()');b.login('AQ20260003')
    b.wait("document.querySelector('#p1 .page-head .d').textContent.includes('督办视角')")
    assert b.js("Array.from(document.querySelectorAll('#p1 .wi button')).every(b=>b.textContent==='督办')")
    b.js("go('p3')");b.wait("document.querySelector('#p3 .page-head button.primary').hidden")
    assert b.js("!Array.from(document.querySelectorAll('#hzBody button')).some(b=>/复查销项|提交整改|现场确认/.test(b.textContent))")
    b.js('goP6(1)');b.wait("document.getElementById('p6Work').textContent.includes('总监可查看')")
    assert b.js("Array.from(document.querySelectorAll('#p6Work button')).filter(b=>/p6Start|p6Sign/.test(b.getAttribute('onclick'))).every(b=>b.hidden)")
    b.js("go('p2')");b.wait("SESS.every(s=>s.user_id===3)")
    assert b.js('curSessId')!=own
    b.js("go('p1')");b.screenshot('identity-director.png')
    b.js('toLogin()');b.login();b.js('showMemory()');b.wait("document.getElementById('mBody').textContent.includes('身份回归测试背景')")
    b.js('closeModal();showProfile()');assert b.js("document.getElementById('mBody').textContent.includes('AQ20260001')")
    assert not b.errors,b.errors
    report={'result':'通过','checks':['错误凭证拒绝','刷新恢复身份会话','切换总监督办视角','P3与P6只读权限','会话记忆隔离','个人信息与记忆弹窗'],'browser_errors':b.errors,'screenshot':'artifacts/identity-director.png'}
    (ROOT/'artifacts/phase10-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
finally:b.close()
