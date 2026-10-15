from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import db

def test_auth_contract(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'app.db'))
    with TestClient(app) as c:
        assert c.get('/').status_code==200
        assert c.get('/static/app.js').status_code==200
        assert c.get('/docs').status_code==200
        assert c.get('/api/auth/me').status_code==401
        assert c.post('/api/auth/login',json={'username':'AQ20260001','password':'wrong'}).status_code==401
        r=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'})
        assert r.status_code==200
        headers={'Authorization':'Bearer '+r.json()['data']['token']}
        assert c.get('/api/auth/me',headers=headers).json()['data']['display_name']=='王建国'
        c.post('/api/auth/logout',headers=headers)
        assert c.get('/api/auth/me',headers=headers).status_code==401
