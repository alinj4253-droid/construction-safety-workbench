from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import db

def test_dashboard_live_counts_and_sort(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'p1.db'))
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        c.headers['Authorization']='Bearer '+token
        s=c.get('/api/dashboard/summary').json()['data']
        assert s['pending_review']==2 and s['overdue']==1
        assert [t['priority'] for t in s['todos']]==sorted(t['priority'] for t in s['todos'])
        assert s['todos'][0]['overdue_days']==1
        h=c.post('/api/hazards',json={'title':'新增临边隐患','track':'heavy'}).json()['data']
        assert c.get('/api/dashboard/summary').json()['data']['today_new']==s['today_new']+1
        db.write('DELETE FROM hazard_events');db.write('DELETE FROM hazards');db.write('DELETE FROM monitor_snapshots')
        empty=c.get('/api/dashboard/summary').json()['data']
        assert empty['today_new']==0 and empty['todos']==[]
