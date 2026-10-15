import json
from browser_cdp import Browser,ROOT
b=Browser();checks=[]
try:
    b.goto('http://127.0.0.1:8011/');b.login();b.js("go('p2')")
    b.wait("document.getElementById('chat').textContent.includes('你好')")
    b.js("ask('基坑临边防护有什么要求')")
    b.wait("document.querySelector('#chat .message-refs button')",timeout=30)
    assert b.js("document.getElementById('chat').textContent.includes('JGJ80-2016')")
    checks.append('流式问答与离线标识')
    b.click('#chat .message-refs button');b.wait("document.getElementById('mTitle').textContent==='资料详情'")
    assert b.js("document.getElementById('p5').classList.contains('active')")
    checks.append('引用定位原文与条款')
    b.js("closeModal();go('p2')")
    b.wait("document.getElementById('chat').textContent.includes('JGJ80-2016')")
    b.js('newChat()');b.js("ask('火星量子计算机维修')")
    b.wait("document.getElementById('chat').textContent.includes('未检索到相关依据')")
    checks.append('无依据拒答')
    for q in ['帮我起草楼梯口作业班前安全分析（JSA）','帮我起草楼梯口安全技术交底','帮我写今天的安全日志']:
        b.wait('!chatBusy');b.js('newChat()');b.js('ask('+json.dumps(q)+')')
        b.wait("document.getElementById('chat').textContent.includes('草稿待审核')",timeout=30)
        assert b.js("document.getElementById('chat').textContent.includes('保存为草稿')")
    checks.append('JSA交底日志三类草稿')
    b.screenshot('p2-chat.png')
    b.wait('!chatBusy');sid=b.js('curSessId')
    b.call('Page.reload');b.wait("typeof CUR_USER!=='undefined' && CUR_USER!==null");b.js("go('p2')")
    b.wait("document.getElementById('chat').textContent.includes('安全员工作日志')")
    checks.append('刷新恢复历史')
    b.js("delSess({stopPropagation(){}},"+json.dumps(sid)+')')
    b.wait('curSessId===null');checks.append('会话删除')
    b.js("ask('记住我负责5号楼，项目在厦门')");b.wait('!chatBusy')
    b.js('newChat()');b.js("ask('你记得我的项目背景吗')");b.wait('!chatBusy')
    assert b.js("document.getElementById('chat').textContent.includes('5号楼')")
    b.js('showMemory()');b.wait("document.getElementById('mBody').textContent.includes('长期记忆')")
    checks.append('长期记忆跨会话与查看入口');b.js('closeModal()')
    assert not b.errors,b.errors
    result={'page':'P2','result':'通过','checks':checks,'browser_errors':b.errors,'screenshot':'artifacts/p2-chat.png'}
    (ROOT/'artifacts/phase5-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:b.close()
