import json
import sqlite3
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import db

def test_chat_sessions_drafts_and_grounding(tmp_path,monkeypatch):
    target=tmp_path/'p2.db'
    with sqlite3.connect(db.db_path()) as src,sqlite3.connect(target) as dst:src.backup(dst)
    monkeypatch.setenv('APP_DB',str(target));monkeypatch.setenv('LLM_ENABLED','0')
    with TestClient(app) as c:
        def auth(name):return {'Authorization':'Bearer '+c.post('/api/auth/login',json={'username':name,'password':'123456'}).json()['data']['token']}
        h=auth('AQ20260001')
        r=c.post('/api/chat/stream',headers=h,json={'message':'基坑临边防护有什么要求'})
        es=[json.loads(b[6:]) for b in r.text.split('\n\n') if b.startswith('data: ')]
        sid=es[0]['session_id'];rid=es[0]['run_id']
        done=es[-1]
        assert done['type']=='done' and done['references'][0]['doc_no']=='JGJ80-2016'
        assert '离线兜底' in ''.join(e.get('content','') for e in es if e['type']=='token')
        assert len(c.get('/api/sessions/'+sid+'/messages',headers=h).json()['data'])==2
        assert c.get('/api/task/'+rid+'/status',headers=h).json()['data']['status']=='done'
        assert c.get('/api/sessions/'+sid+'/messages',headers=auth('AQ20260002')).status_code==404
        unknown=c.post('/api/chat/stream',headers=h,json={'message':'火星量子计算机维修'}).text
        assert '未检索到相关依据' in unknown and 'chunk_id' not in unknown
        for kind in ['jsa','jiaodi','log']:
            d=c.post('/api/draft',headers=h,json={'kind':kind,'context':'楼梯口防护'}).json()['data']
            assert d['status']=='draft' and d['mode']=='offline'
            assert c.post(f"/api/documents/{d['id']}/save-draft",headers=h).status_code==200
            exported=c.get(f"/api/documents/{d['id']}/export",headers=h)
            assert exported.status_code==200 and exported.content.startswith(b'PK')
        assert c.delete('/api/sessions/'+sid,headers=h).status_code==200
        assert c.get('/api/sessions/'+sid+'/messages',headers=h).status_code==404
