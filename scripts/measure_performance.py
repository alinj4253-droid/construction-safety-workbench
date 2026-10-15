import json,time
import httpx
from browser_cdp import Browser,ROOT
from server_ready import wait_backend
wait_backend(8010)
with httpx.Client(base_url='http://127.0.0.1:8010') as c:
    start=time.monotonic();r=c.get('/');r.raise_for_status();html=round(time.monotonic()-start,4)
    c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
    start=time.monotonic();c.get('/api/dashboard/summary').raise_for_status();summary=round(time.monotonic()-start,4)
b=Browser()
try:
    b.goto();start=time.monotonic();b.login();b.wait("document.querySelector('#p1 .wi')")
    usable=round(time.monotonic()-start,4)
    b.wait("document.readyState==='complete' && performance.getEntriesByType('navigation')[0].loadEventEnd>0")
    navigation=b.js("(()=>{const n=performance.getEntriesByType('navigation')[0];return {dom_content_loaded_ms:n.domContentLoadedEventEnd,load_ms:n.loadEventEnd};})()")
    report={'html_seconds':html,'dashboard_api_seconds':summary,'login_to_dashboard_seconds':usable,'navigation':navigation,'homepage_under_2_seconds':usable<2 and 0<navigation['load_ms']<2000 and navigation['dom_content_loaded_ms']<2000}
    assert report['homepage_under_2_seconds'],report
    (ROOT/'artifacts/performance.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
finally:b.close()
