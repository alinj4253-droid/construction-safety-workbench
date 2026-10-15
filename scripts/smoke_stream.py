import json
import time
from pathlib import Path
import httpx
from scripts.server_ready import wait_backend
wait_backend(8010)
with httpx.Client(base_url='http://127.0.0.1:8010',timeout=60) as c:
    token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
    c.headers['Authorization']='Bearer '+token
    start=time.monotonic();first=None;answer='';rid=None;done=None
    with c.stream('POST','/api/chat/stream',json={'message':'临时用电接地要求'}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith('data: '):continue
            e=json.loads(line[6:])
            if e['type']=='session':rid=e['run_id']
            if e['type']=='token':
                if first is None:first=time.monotonic()-start
                answer+=e['content']
            if e['type']=='done':done=e
    saved=c.get('/api/task/'+rid+'/status').json()['data']
    assert answer==saved['answer'],'SSE must match the persisted complete answer'
    assert done and done['references'][0]['doc_no']=='JGJ/T46-2024'
    result={'first_answer_token_seconds':round(first,3),'total_seconds':round(time.monotonic()-start,3),'mode':done['mode'],'persisted_answer_matches':True,'citations':len(done['references'])}
    Path('artifacts/online-stream.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
