import io
import json
import sqlite3
import time
from datetime import timedelta
from docx import Document
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import db

def test_handling_normal_rework_insufficient_and_guards(tmp_path,monkeypatch):
    target=tmp_path/'p6.db'
    with sqlite3.connect(db.db_path()) as src,sqlite3.connect(target) as dst:src.backup(dst)
    monkeypatch.setenv('APP_DB',str(target));monkeypatch.setenv('LLM_ENABLED','0');monkeypatch.setenv('ALLOW_TEST_DRAFTS','1')
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token'];c.headers['Authorization']='Bearer '+token
        def hazard(title='临边防护缺失，坠落高度3m'):
            return c.post('/api/hazards',json={'title':title,'track':'heavy','responsible_team':'木工班组','responsible_person':'测试责任人','deadline':str(db.today()+timedelta(days=3))}).json()['data']
        def task(h,case=None):
            body={'hazard_id':h['id']}
            if case:body['test_case']=case
            response=c.post('/api/handle/tasks',json=body);assert response.status_code==200,response.text
            tid=response.json()['data']['task_id'];end=time.monotonic()+20
            while time.monotonic()<end:
                t=c.get('/api/handle/tasks/'+tid).json()['data']
                if t['status'] in {'pending_human','needs_input','error'}:return t
                time.sleep(.05)
            raise AssertionError('handling timed out')
        h=hazard();before=db.one('SELECT count(*) n FROM hazards')['n'];t=task(h)
        assert t['status']=='pending_human',t
        assert db.one('SELECT status FROM hazards WHERE id=?',(h['id'],))['status']=='待整改'
        assert db.one('SELECT count(*) n FROM hazards')['n']==before
        did=t['document_id']
        assert c.post(f'/api/documents/{did}/issue',json={'confirmed':False}).status_code==400
        result=c.post(f'/api/documents/{did}/issue',json={'confirmed':True})
        assert result.status_code==200,result.text
        again=c.post(f'/api/documents/{did}/issue',json={'confirmed':True}).json()['data']
        assert again['doc_no']==result.json()['data']['doc_no']
        assert db.one('SELECT count(*) n FROM hazards')['n']==before
        assert db.one('SELECT source,status FROM hazards WHERE id=?',(h['id'],))=={'source':'manual','status':'整改中'}
        word=c.get(f'/api/documents/{did}/export').content
        doc=Document(io.BytesIO(word));assert any('测试责任人' in p.text for p in doc.paragraphs)
        t=task(hazard(),'invented_deadline')
        assert t['status']=='pending_human' and t['document']['draft_version']==2
        assert any('invented_fact' in r['result_json'] for r in t['document']['reviews'])
        assert t['document']['content']['deadline']!='2099-12-31'
        failed=task(hazard(),'stubborn')
        assert failed['status']=='needs_input' and failed['document']['draft_version']==2
        assert c.post(f"/api/documents/{failed['document_id']}/issue",json={'confirmed':True}).status_code==400
        insufficient=task(hazard('火星量子计算机维修'))
        assert insufficient['status']=='needs_input' and insufficient['document']['reviews']
        missing=c.post('/api/hazards',json={'title':'楼梯口防护缺失','track':'heavy'}).json()['data']
        assert task(missing)['status']=='needs_input'
        h2=hazard();t2=task(h2);sid=t2['document']['content']['evidence'][0]['source_id']
        db.write("UPDATE kb_sources SET status='历史版本',legal_status='已废止' WHERE id=?",(sid,))
        assert c.post(f"/api/documents/{t2['document_id']}/issue",json={'confirmed':True}).status_code==400
        assert c.get(f"/api/documents/{did}").json()['data']['status']=='issued'
