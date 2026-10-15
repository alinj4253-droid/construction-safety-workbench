import sqlite3
import time
from fastapi.testclient import TestClient
from backend.app import db
from backend.app.main import app
from backend.app.recovery import recover_interrupted
from backend.agents.handling import rule_check,local_draft
from backend.rag.knowledge import search

def test_identity_permissions_audits_and_restart(tmp_path,monkeypatch):
    target=tmp_path/'identity.db'
    with sqlite3.connect(db.db_path()) as src,sqlite3.connect(target) as dst:src.backup(dst)
    monkeypatch.setenv('APP_DB',str(target));monkeypatch.setenv('LLM_ENABLED','0')
    with TestClient(app) as c:
        for path in ['/api/dashboard/summary','/api/hazards','/api/monitor/overview','/api/kb/sources','/api/sessions','/api/memory','/api/documents/1']:
            assert c.get(path).status_code==401,path
        def login(username):
            d=c.post('/api/auth/login',json={'username':username,'password':'123456'}).json()['data'];c.headers['Authorization']='Bearer '+d['token'];return d['token']
        operator=login('AQ20260001');todos1=c.get('/api/dashboard/summary').json()['data']['todos']
        h=c.post('/api/hazards',json={'title':'临边防护缺失','track':'heavy','responsible_team':'QA木工班','responsible_person':'QA责任人','deadline':str(db.today())}).json()['data']
        tid=c.post('/api/handle/tasks',json={'hazard_id':h['id']}).json()['data']['task_id']
        for _ in range(100):
            task=c.get('/api/handle/tasks/'+tid).json()['data']
            if task['status'] in {'pending_human','error','needs_input'}:break
            time.sleep(.05)
        assert task['status']=='pending_human',task
        did=task['document_id'];assert c.post(f'/api/documents/{did}/issue',json={'confirmed':True}).status_code==200
        sid=c.post('/api/sessions',json={'title':'仅王建国会话'}).json()['data']['id']
        c.post('/api/memory',json={'value':'王建国专属项目背景'})
        pending=c.get('/api/monitor/snapshots').json()['data'][0]['id']
        assert c.post(f'/api/monitor/snapshots/{pending}/confirm',json={'note':'QA现场确认'}).status_code==200
        u=c.post('/api/kb/sources',data={'name':'身份审计测试资料','category':'项目资料','region':'厦门'},files={'file':('audit.txt',('审计验收项目资料，记录每次巡检事实及审核情况。'*8).encode(),'text/plain')});assert u.status_code==200,u.text
        actions={'register','create_handle_task','issue_document','confirm_snapshot','upload_source'}
        records=db.rows('SELECT * FROM audit_logs WHERE actor=?',('1',))
        assert actions.issubset({r['action'] for r in records})
        assert all(r['created_at'] and r['object_type'] and r['object_id'] for r in records if r['action'] in actions)
        login('AQ20260003');todos3=c.get('/api/dashboard/summary').json()['data']['todos']
        assert any(t['type']=='snapshot' for t in todos1) and all(t['type']!='snapshot' and t['view_action']=='urge' for t in todos3)
        assert c.post('/api/hazards',json={'title':'总监不能代填','track':'heavy'}).status_code==403
        assert c.post(f'/api/documents/{did}/issue',json={'confirmed':True}).status_code==403
        assert c.post(f"/api/hazards/{h['id']}/actions",json={'action':'submit_rectify','note':'非法代整改'}).status_code==403
        assert c.post(f"/api/hazards/{h['id']}/actions",json={'action':'urge','note':'总监实际督办'}).status_code==200
        assert c.get(f'/api/sessions/{sid}/messages').status_code==404
        assert not c.get('/api/memory').json()['data']['long_term']
        c.post('/api/auth/logout');assert c.get('/api/auth/me').status_code==401
        # Rule check rejects fabricated clause numbers independently of LLM review.
        e=search('临边防护',for_document=True);draft=local_draft(h,e);draft['body']+='依据JGJ80-2016第9.9.9条。'
        assert any(x['type']=='unsupported_clause' for x in rule_check(draft,h,e))
        # Check inactive indexed clauses again at manual issue time.
        db.write('UPDATE chunk_states SET active=0 WHERE chunk_id=?',(e[0]['chunk_id'],))
        assert any(x['type']=='invalid_source' for x in rule_check(local_draft(h,e),h,e))
        db.write("UPDATE handle_tasks SET status='drafting' WHERE id=?",(tid,))
        recovered=recover_interrupted();assert recovered['handle_tasks']>=1
        assert db.one('SELECT status,error FROM handle_tasks WHERE id=?',(tid,))['status']=='error'
        assert not recover_interrupted()
