import csv
import io
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import db

def test_dual_track_export_evidence_and_logs(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'p3.db'))
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token'];c.headers['Authorization']='Bearer '+token
        light=c.post('/api/hazards',json={'title':'现场人工发现未戴安全帽','track':'light'}).json()['data']
        assert c.post(f"/api/hazards/{light['id']}/actions",json={'action':'submit_rectify','note':'已纠正'}).status_code==400
        assert c.post(f"/api/hazards/{light['id']}/actions",json={'action':'confirm'}).json()['data']['status']=='整改中'
        assert c.post(f"/api/hazards/{light['id']}/actions",json={'action':'submit_rectify','note':'已当场纠正并教育'}).json()['data']['status']=='已闭环'
        h=c.post('/api/hazards',json={'title':'=危险公式测试','track':'heavy'}).json()['data']
        for action,note in [('urge','系统催办'),('start_rectify',''),('submit_rectify','已完成整改'),('review_return','防护固定不足'),('submit_rectify','再次加固'),('review_close','现场复查合格')]:
            response=c.post(f"/api/hazards/{h['id']}/actions",json={'action':action,'note':note});assert response.status_code==200,response.text
        detail=c.get(f"/api/hazards/{h['id']}").json()['data']
        assert detail['status']=='已销项' and detail['review_note']=='现场复查合格'
        assert len(detail['events'])==7
        assert c.post('/api/hazards/2/actions',json={'action':'review_close','note':''}).status_code==400
        selected=c.get('/api/hazards?filter=heavy').json()['data']['items']
        exported=c.get('/api/hazards/export?filter=heavy')
        records=list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
        assert len(records)==len(selected) and [int(r['id']) for r in records]==[h['id'] for h in selected]
        assert 'event_summary' in records[0] and records[0]['title'].startswith("'=")
        assert c.get('/api/hazards/export?format=xlsx').content.startswith(b'PK')
        assert c.post('/api/hazards/1/attachments',files={'file':('script.html',b'<script>bad</script>','text/html')}).status_code==400
        png=(db.ROOT/'artifacts/p1-dashboard.png').read_bytes()
        a=c.post('/api/hazards/1/attachments',files={'file':('整改证据.png',png,'image/png')},data={'kind':'rectify'})
        assert a.status_code==200,a.text
        aid=a.json()['data']['id'];assert c.get('/api/hazards/attachments/'+str(aid)).content==png
        assert any(e['action']=='upload_evidence' for e in c.get('/api/hazards/1').json()['data']['events'])
