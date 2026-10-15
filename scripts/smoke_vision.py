import json,time
from pathlib import Path
import httpx
from server_ready import wait_backend
wait_backend(8011)
with httpx.Client(base_url='http://127.0.0.1:8011',timeout=60) as c:
    token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token'];c.headers['Authorization']='Bearer '+token
    r=c.post('/api/monitor/detect',json={'camera_id':'CAM-03','max_frames':8});r.raise_for_status();rid=r.json()['data']['id'];start=time.monotonic()
    while time.monotonic()-start<180:
        run=c.get('/api/monitor/runs/'+rid).json()['data']
        if run['status'] in {'done','error'}:break
        time.sleep(.5)
    assert run['status']=='done',run
    assert run['result']['frames'],run
    fid=run['result']['frames'][0]['id'];image=c.get('/api/monitor/frames/'+str(fid));image.raise_for_status()
    Path('artifacts/vision-frame.jpg').write_bytes(image.content)
    report={'id':rid,'elapsed_seconds':round(time.monotonic()-start,3),'status':run['status'],'result':run['result']}
    Path('artifacts/real-vision.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
