import json
import time
from datetime import date,timedelta
from pathlib import Path
import httpx
from scripts.server_ready import wait_backend
wait_backend(8010)
with httpx.Client(base_url='http://127.0.0.1:8010',timeout=60) as c:
    token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token'];c.headers['Authorization']='Bearer '+token
    h=c.post('/api/hazards',json={'title':'接口验收 5#楼临边防护缺失，坠落高度3m','description':'安全员现场人工确认，5#楼二层临边防护栏杆缺失，坠落高度3m。','location':'5#楼二层','track':'heavy','responsible_team':'验收木工班组','responsible_person':'验收责任人','deadline':str(date.today()+timedelta(days=3))}).json()['data']
    tid=c.post('/api/handle/tasks',json={'hazard_id':h['id'],'note':'以上事实已由安全员现场人工核实；本任务为接口验收，不实际发送任何通知。'}).json()['data']['task_id']
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        t=c.get('/api/handle/tasks/'+tid).json()['data']
        if t['status'] in {'pending_human','needs_input','error'}:break
        time.sleep(.5)
    result={'task_id':tid,'hazard_id':h['id'],'status':t['status'],'document_id':t['document_id'],'steps':t['steps'],'reviews':t.get('document',{}).get('reviews',[])}
    Path('artifacts/online-handling.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':t['status'],'document_id':t['document_id'],'models':t.get('document',{}).get('content',{}).get('models')},ensure_ascii=False))
