"""Isolated headless Chrome acceptance harness; never touches the user's browser profile."""
from __future__ import annotations
import base64
import json
import subprocess
import time
import urllib.request
from pathlib import Path
import websocket

ROOT=Path(__file__).resolve().parents[1]
class Browser:
    def __init__(self):
        import socket,tempfile
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.profile=Path(tempfile.mkdtemp(prefix='safety-browser-'))
        chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        self.proc=subprocess.Popen([str(chrome),'--headless=new','--no-first-run','--no-default-browser-check',f'--user-data-dir={self.profile}',f'--remote-debugging-port={port}','--remote-debugging-address=127.0.0.1','--window-size=1440,1000','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            try:
                tabs=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=1))
                self.ws=websocket.create_connection(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page'),timeout=20,suppress_origin=True);break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('headless Chrome unavailable')
        self.seq=0;self.errors=[]
        self.call('Runtime.enable');self.call('Page.enable')
    def call(self,method,params=None):
        self.seq+=1;seq=self.seq
        self.ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
        while True:
            r=json.loads(self.ws.recv())
            if r.get('method')=='Runtime.exceptionThrown':self.errors.append(r['params']['exceptionDetails'].get('text','exception'))
            if r.get('id')==seq:
                if 'error' in r:raise RuntimeError(str(r['error']))
                return r.get('result',{})
    def js(self,expression):
        r=self.call('Runtime.evaluate',{'expression':expression,'awaitPromise':True,'returnByValue':True})
        if 'exceptionDetails' in r:raise AssertionError(str(r['exceptionDetails']))
        return r.get('result',{}).get('value')
    def wait(self,expression,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                r=self.js('Boolean('+expression+')')
                if r:return r
            except AssertionError:pass
            time.sleep(.1)
        self.screenshot('browser-failure.png')
        raise AssertionError('browser condition timed out: '+expression+' '+str(self.js("({url:location.href,ready:document.readyState,title:document.title,errors:document.body?.textContent.slice(0,300)})"))+' '+str(self.errors))
    def goto(self,url='http://127.0.0.1:8010/'):
        from server_ready import wait_backend
        from urllib.parse import urlparse
        wait_backend(urlparse(url).port or 80)
        self.call('Page.navigate',{'url':url})
        self.wait("document.readyState!=='loading' && typeof doLogin==='function'",timeout=40)
        self.wait("document.querySelector('#lgUser').options[0].value==='AQ20260001'")
    def login(self,user='AQ20260001'):
        self.js(f"document.getElementById('lgUser').value={json.dumps(user)};document.querySelector('#loginGate input[type=password]').value='123456';doLogin()")
        self.wait("!document.getElementById('loginGate').classList.contains('on')")
        self.wait("document.querySelector('#p1 .page-head .d').textContent.includes('2026-')")
    def click(self,selector):return self.js(f"document.querySelector({json.dumps(selector)}).click()")
    def fill(self,selector,value):return self.js(f"(()=>{{const e=document.querySelector({json.dumps(selector)});e.value={json.dumps(value)};e.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")
    def screenshot(self,name):
        r=self.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        p=ROOT/'artifacts'/name;p.parent.mkdir(exist_ok=True)
        p.write_bytes(base64.b64decode(r['data']));return str(p)
    def close(self):
        try:self.call('Browser.close')
        except Exception:pass
        self.ws.close()
        try:self.proc.wait(timeout=5)
        except Exception:self.proc.terminate()

def p1():
    b=Browser()
    try:
        b.goto();b.login()
        assert b.js("document.querySelectorAll('#p1 .wi').length")>=4
        assert b.js("document.querySelector('#p1 .wi').textContent.includes('逾期')")
        b.screenshot('p1-dashboard.png')
        for i,target in [(0,'p2'),(1,'p6'),(2,'p3'),(3,'p4')]:
            b.js("go('p1')")
            b.click(f'#p1 .quick:nth-child({i+1})')
            # Registration opens a modal without leaving the dashboard, as in the prototype.
            if i==2:
                assert b.js("document.getElementById('mask').classList.contains('on')")
                b.js('closeModal()')
            else:assert b.js(f"document.getElementById('{target}').classList.contains('active')")
        b.js("go('p1')")
        b.wait("document.querySelectorAll('#p1 .wi').length>3")
        b.js("Array.from(document.querySelectorAll('#p1 .wi button')).find(x=>x.textContent==='复查').click()")
        b.wait("document.getElementById('mTitle').textContent==='复查销项'")
        b.js('closeModal()')
        assert not b.errors,b.errors
        return {'page':'P1','result':'通过','checks':['登录与日期','四统计卡','逾期优先','四快捷入口','待办复查定位'],'screenshot':'artifacts/p1-dashboard.png','browser_errors':b.errors}
    finally:b.close()

if __name__=='__main__':
    result=p1();(ROOT/'artifacts/phase4-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
