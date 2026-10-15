from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import db
from backend.vision.detector import map_head_classes

def test_mapping_does_not_drop_helmet_heads():
    ds=map_head_classes([(0,.92,(0,0,20,20)),(1,.81,(40,0,60,20)),(0,.1,(80,0,90,20))])
    assert len(ds)==2 and ds[0]['class_id']==0 and ds[1]['class_id']==1
    assert len(map_head_classes([(0,.9,(0,0,20,20))]))==1

def test_confirm_dismiss_idempotency_and_statistics(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'p4.db'))
    with TestClient(app) as c:
        assert c.get('/api/monitor/snapshots').status_code==401
        token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token'];c.headers['Authorization']='Bearer '+token
        before=db.one('SELECT count(*) n FROM hazards')['n']
        assert c.post('/api/monitor/snapshots/1/confirm',json={'note':''}).status_code==400
        first=c.post('/api/monitor/snapshots/1/confirm',json={'note':'安全员到现场确认未佩戴安全帽'}).json()['data']
        again=c.post('/api/monitor/snapshots/1/confirm',json={'note':'重复确认'}).json()['data']
        assert first==again and db.one('SELECT count(*) n FROM hazards')['n']==before+1
        h=db.one('SELECT * FROM hazards WHERE id=?',(first['hazard_id'],));assert h['source']=='ai_monitor' and h['track']=='light' and h['confirmed_at'] and h['status']=='整改中'
        assert c.post('/api/monitor/snapshots/2/dismiss',json={'note':'头部被遮挡，误报'}).status_code==200
        assert db.one('SELECT count(*) n FROM hazards')['n']==before+1
        assert c.post('/api/monitor/snapshots/2/confirm',json={'note':'改成确认'}).status_code==400
        s=c.get('/api/monitor/overview').json()['data']
        assert s['violations']==3 and s['no_helmet']==2 and s['pending']==2
        assert sum(t['count'] for t in s['trend'])==s['no_helmet']
        assert len(s['classes'])==2 and '演示' in s['vest_mode']
