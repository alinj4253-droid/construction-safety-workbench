import json
from fastapi.testclient import TestClient
import pytest
from backend.app import db
from backend.app.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'feedback.db'))
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        yield c

def demo(c):
    r=c.post('/api/hazards/demo-cases',json={'confirmed':True});assert r.status_code==200,r.text
    return r.json()['data']

def test_simulated_reply_received_without_faking_team_actor(client):
    c=client;h=demo(c);hid=h['id']
    assert h['status']=='待整改' and h['is_demo'] and h['code'].startswith('DEMO-')
    detail=c.get(f'/api/hazards/{hid}').json()['data']
    assert not detail['feedbacks'] and not detail['attachments'] and not detail['demo_feedback']['received']
    assert detail['demo_feedback']['feedback_content'].startswith('【演示模拟】')
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','feedback_source':'demo_simulation'}).status_code==400
    c.post(f'/api/hazards/{hid}/actions',json={'action':'start_rectify'})
    r=c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','feedback_source':'demo_simulation','note':'伪造另一份内容','feedback_provider':'木工班组账号','feedback_at':'2026-01-01T12:00:00+08:00'})
    assert r.status_code==200,r.text
    detail=c.get(f'/api/hazards/{hid}').json()['data'];f=detail['feedbacks'][0]
    assert detail['status']=='待复查' and detail['closed_at'] is None and detail['review_note'] is None
    assert f['content']==detail['demo_feedback']['feedback_content'] and f['recorded_by_name']=='王建国'
    assert f['feedback_source']=='demo_simulation' and f['recorded_by']==1 and f['is_simulated']==1
    assert f['provided_by'] is None and f['provided_at'] is None and f['recorded_at']
    event=next(e for e in detail['events'] if e['action']=='submit_rectify')
    assert event['actor']=='1' and json.loads(event['detail'])['recording_mode']=='安全员登记演示模拟反馈'
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'review_close','note':''}).status_code==400
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'review_close','note':'整改合格'}).status_code==200
    archived=c.get(f'/api/hazards/{hid}').json()['data']
    assert archived['status']=='已销项' and archived['review_note']=='整改合格' and archived['closed_at']
    assert archived['feedbacks']==detail['feedbacks']
    assert {'submit_rectify','review_close'}.issubset({e['action'] for e in archived['events']})

def test_real_feedback_is_blank_until_recorded_and_return_preserves_rounds(client):
    c=client;h=c.post('/api/hazards',json={'title':'真实隐患接口回归','track':'heavy','responsible_team':'电工班组'}).json()['data'];hid=h['id']
    c.post(f'/api/hazards/{hid}/actions',json={'action':'start_rectify'})
    detail=c.get(f'/api/hazards/{hid}').json()['data'];assert detail['demo_feedback'] is None and not detail['feedbacks'] and detail['rectify_note'] is None
    for body in [dict(feedback_source='demo_simulation'),dict(feedback_source='team_submitted'),dict(feedback_team='木工班组'),dict(feedback_team='')]:
        r=c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','note':'测试反馈',**body});assert r.status_code==400,r.text
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','note':'   '}).status_code==400
    version=detail['version']
    r=c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','version':version,'note':'班组反馈：接地连接已加固','feedback_team':'电工班组','feedback_provider':'班组联系人','feedback_at':'2026-10-18T10:00:00+08:00'})
    assert r.status_code==200,r.text
    f=c.get(f'/api/hazards/{hid}').json()['data']['feedbacks'][0]
    assert f['feedback_source']=='safety_officer_recorded' and f['recorded_by_name']=='王建国' and f['provided_by']=='班组联系人' and f['is_simulated']==0
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'review_close','note':'整改合格','version':version}).status_code==409
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'review_return','note':'现场复查连接仍不牢固'}).json()['data']['status']=='整改中'
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','note':'班组再次反馈：连接已重新处理'}).json()['data']['status']=='待复查'
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'review_close','note':'整改合格'}).json()['data']['status']=='已销项'
    archived=c.get(f'/api/hazards/{hid}').json()['data'];assert len(archived['feedbacks'])==2
    assert archived['feedbacks'][-1]==f and archived['feedbacks'][0]['provided_at'] is None
    assert not any(f['is_simulated'] for f in archived['feedbacks'])

def test_repeat_demo_preparation_keeps_closed_archive_and_preset_is_single_use(client):
    c=client;h=demo(c);hid=h['id']
    c.post(f'/api/hazards/{hid}/actions',json={'action':'start_rectify'})
    c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','feedback_source':'demo_simulation'})
    c.post(f'/api/hazards/{hid}/actions',json={'action':'review_return','note':'模拟复查退回'})
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','feedback_source':'demo_simulation'}).status_code==400
    c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','note':'第二轮模拟班组回复'})
    c.post(f'/api/hazards/{hid}/actions',json={'action':'review_close','note':'整改合格'})
    before=c.get(f'/api/hazards/{hid}').json()['data'];new=demo(c)
    assert new['id']!=hid and new['code']!=h['code'] and new['title']==h['title'] and new['status']=='待整改'
    assert c.get(f'/api/hazards/{hid}').json()['data']==before
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','note':'不得修改档案'}).status_code==400
    listing=c.get('/api/hazards?filter=heavy').json()['data']['items'];assert all(x['is_demo'] for x in listing if x['id'] in {hid,new['id']})

def test_legacy_feedback_missing_metadata_and_idempotent_migration(client):
    c=client;hid=2
    db.write('UPDATE hazards SET rectify_note=? WHERE id=?',('历史整改记录，没有提交人元数据',hid))
    before=db.one('SELECT * FROM hazards WHERE id=?',(hid,));events=db.rows('SELECT * FROM hazard_events WHERE hazard_id=?',(hid,))
    db.init_db(seed=False);db.init_db(seed=False)
    assert db.one('SELECT * FROM hazards WHERE id=?',(hid,))==before and db.rows('SELECT * FROM hazard_events WHERE hazard_id=?',(hid,))==events
    f=c.get(f'/api/hazards/{hid}').json()['data']['feedbacks'][0]
    assert f['feedback_source']=='legacy' and f['provided_by'] is None and f['recorded_by_name'] is None and f['recorded_at'] is None
    assert f['content']==before['rectify_note']

def test_feedback_evidence_metadata_and_permissions(client):
    c=client;h=demo(c);hid=h['id'];png=(db.ROOT/'artifacts/p1-dashboard.png').read_bytes()
    for name,body in [('整改图片.png',png),('整改记录.pdf',b'%PDF-1.4\n% isolated feedback fixture\n%%EOF')]:
        response=c.post(f'/api/hazards/{hid}/attachments',data={'kind':'rectify'},files={'file':(name,body)});assert response.status_code==200,response.text
        assert c.get('/api/hazards/attachments/'+str(response.json()['data']['id'])).content==body
    files=c.get(f'/api/hazards/{hid}').json()['data']['attachments'];assert len(files)==2 and files[0]['is_image'] and not files[1]['is_image']
    assert all(f['available'] and f['created_at'] and f['recorded_by_name']=='王建国' for f in files)
    c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260003','password':'123456'}).json()['data']['token']
    assert c.post('/api/hazards/demo-cases',json={'confirmed':True}).status_code==403
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','note':'越权反馈'}).status_code==403
