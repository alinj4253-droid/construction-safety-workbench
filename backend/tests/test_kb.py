import json
import sqlite3
import uuid
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import db
from backend.rag.knowledge import search

def test_upload_review_type_version_undo_and_citations(tmp_path,monkeypatch):
    original=db.db_path();target=tmp_path/'kb.db'
    with sqlite3.connect(original) as src,sqlite3.connect(target) as dst:src.backup(dst)
    monkeypatch.setenv('APP_DB',str(target));monkeypatch.setenv('LLM_ENABLED','0')
    with TestClient(app) as c:
        assert c.get('/api/kb/sources').status_code==401
        token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token'];c.headers['Authorization']='Bearer '+token
        def upload(category='法规依据',no=None,suffix=''):
            no=no or 'QA-OLD-'+uuid.uuid4().hex[:8]
            text='第一条 红杉围挡巡检应登记巡检时间、位置、检查人、问题描述和实际整改结果。第二条 项目负责人应对红杉围挡巡检记录进行检查，并保留完整可追溯记录。第三条 发现围挡破损应及时修复，现场安全员记录核实情况。'+suffix
            r=c.post('/api/kb/sources',data={'name':'红杉围挡巡检验收用例','category':category,'doc_no':no,'region':'国家','effective_date':'2020-01-01'},files={'file':('test.txt',text.encode(),'text/plain')})
            assert r.status_code==200,r.text
            return r.json()['data'],text
        s,text=upload();sid=s['id'];assert s['status']=='待核验' and s['parsed']==1
        assert not search('红杉围挡巡检',source_id=sid)
        assert c.post(f'/api/kb/sources/{sid}/confirm',json={'confirmed':False,'note':'checked'}).status_code==400
        assert c.post(f'/api/kb/sources/{sid}/confirm',json={'confirmed':True,'note':'QA人工核对合成资料'}).status_code==200
        assert search('红杉围挡巡检',source_id=sid,for_document=True)
        assert c.get('/api/kb/sources?type=法规依据&status=现行&keyword='+s['doc_no']).json()['data']['items'][0]['id']==sid
        duplicate=c.post('/api/kb/sources',data={'name':'重复','category':'法规依据','doc_no':'QA','region':'国家'},files={'file':('d.txt',text.encode(),'text/plain')});assert duplicate.status_code==409
        for category in ['项目资料','案例参考']:
            p,_=upload(category,no='QA-'+category,suffix=category)
            assert c.post(f"/api/kb/sources/{p['id']}/confirm",json={'confirmed':True,'note':'核对内部资料'}).status_code==200
            assert search('红杉围挡巡检',source_id=p['id'])
            assert not search('红杉围挡巡检',source_id=p['id'],for_document=True)
        assert c.post('/api/kb/version-rules',json={'old_no':s['doc_no'],'new_no':'QA-NEW','effective_date':'2020-02-01','basis_url':'QA合成版本关系，用于验证拦截'}).status_code==200
        # Block as soon as the independently registered legal relation applies.
        assert not search('红杉围挡巡检',source_id=sid,for_document=True)
        changes=c.post('/api/kb/check-updates').json()['data']['suggestions'];assert any(x['source_id']==sid and x['needs_change'] for x in changes)
        assert c.post(f'/api/kb/sources/{sid}/apply-update',json={'confirmed':True,'note':'按已核实关系归档'}).status_code==200
        log=c.get('/api/kb/changelog').json()['data'][0];assert log['action']=='apply_version_update'
        assert c.post(f"/api/kb/changelog/{log['id']}/undo",json={'confirmed':True,'note':'测试撤销不恢复旧法'}).status_code==200
        assert c.get(f'/api/kb/sources/{sid}').json()['data']['legal_status']=='已废止'
        assert not search('红杉围挡巡检',source_id=sid,for_document=True)
        assert search('红杉围挡巡检',source_id=sid,include_history=True)[0]['display_status']=='已废止'
        assert c.post(f'/api/kb/sources/{sid}/confirm',json={'confirmed':True,'note':'试图重新生效'}).status_code==400
        # A normal review can be undone back to pending, with no remaining retrieval eligibility.
        p,_=upload(suffix='撤销核验独立用例')
        c.post(f"/api/kb/sources/{p['id']}/confirm",json={'confirmed':True,'note':'核实'})
        lid=c.get('/api/kb/changelog').json()['data'][0]['id']
        assert c.post(f'/api/kb/changelog/{lid}/undo',json={'confirmed':True,'note':'需重新核对原件'}).status_code==200
        assert not search('红杉围挡巡检',source_id=p['id'])
        # A submitted standard number must never substitute curated text for the uploaded bytes.
        p,_=upload(no='JGJ80-2016',suffix='不得替换为内置条款')
        detail=c.get(f"/api/kb/sources/{p['id']}").json()['data'];assert '红杉' in ''.join(x['text'] for x in detail['chunks']) and not any(x['section']=='4.3.1' for x in detail['chunks'])
        assert db.one("SELECT count(*) n FROM audit_logs WHERE action='undo_kb_change'")['n']>=2
