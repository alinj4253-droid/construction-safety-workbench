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
        db.write("UPDATE monitor_snapshots SET captured_at='2020-01-01T09:00:00+08:00'")
        s=c.get('/api/monitor/overview').json()['data']
        assert s['pending']==2 and s['violations']==0 and sum(t['count'] for t in s['trend'])==0

def test_real_demo_statistics_and_latest_frames(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'real.db'))
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        sid=db.write('INSERT INTO monitor_snapshots(camera_id,captured_at,category,confidence,location,status,data_mode) VALUES(?,?,?,?,?,?,?)',('CAM-03',db.now(),'未戴安全帽',.9,'真实检测区','pending','yolo'))
        def both():
            m=c.get('/api/monitor/overview').json()['data']
            home=c.get('/api/dashboard/summary').json()['data']['monitor_today']
            assert all(m[k]==home[k] for k in home if k!='updated_at')
            assert sum(x['count'] for x in m['real']['trend'])==m['real']['no_helmet']
            return m
        m=both();assert m['real']['no_helmet']==1 and m['demo']['no_helmet']==3 and m['real']['pending_today']==1
        assert c.post(f'/api/monitor/snapshots/{sid}/confirm',json={'note':'回归测试人工核实'}).status_code==200
        m=both();assert m['real']['no_helmet']==1 and m['real']['confirmed_today']==1 and m['real']['pending']==0
        sid=db.write('INSERT INTO monitor_snapshots(camera_id,captured_at,category,confidence,location,status,data_mode) VALUES(?,?,?,?,?,?,?)',('CAM-01',db.now(),'未戴安全帽',.8,'另一真实检测区','pending','yolo'))
        assert c.post(f'/api/monitor/snapshots/{sid}/dismiss',json={'note':'人工判断误报'}).status_code==200
        m=both();assert m['real']['no_helmet']==1 and m['real']['dismissed_today']==1 and m['demo']['violations']==4
        db.write('INSERT INTO monitor_runs(id,camera_id,status,result_json,created_by,created_at) VALUES(?,?,?,?,?,?)',('latest-test','CAM-03','done',db.dumps({'frames':[]}),1,db.now()))
        latest=c.get('/api/monitor/latest').json()['data'];assert len(latest)==4
        assert next(x for x in latest if x['camera_id']=='CAM-03')['completed']['id']=='latest-test'
        assert c.get('/api/monitor/frames/999999').status_code==404
        assert c.get('/api/monitor/snapshots/1/image').status_code==404

def test_serial_batch_queue_and_failures(tmp_path,monkeypatch):
    from backend.app import monitor
    monkeypatch.setenv('APP_DB',str(tmp_path/'batch.db'))
    calls=[]
    monkeypatch.setattr(monitor.pool,'submit',lambda *args:calls.append(args))
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        assert c.post('/api/monitor/detect',json={'camera_id':'bad'}).status_code==400
        assert c.post('/api/monitor/detect-all',json={'max_frames':0}).status_code==422
        r=c.post('/api/monitor/detect-all',json={'max_frames':8});assert r.status_code==200
        assert [x['camera_id'] for x in r.json()['data']['runs']]==[x['id'] for x in monitor.CAMERAS]
        assert len(calls)==4 and monitor.pool._max_workers==1
        assert c.post('/api/monitor/detect',json={'camera_id':'CAM-03'}).status_code==409
        assert c.post('/api/monitor/detect-all',json={}).status_code==409
        db.write("UPDATE monitor_runs SET status='error'")
        monkeypatch.setattr(db,'ROOT',tmp_path)
        assert c.post('/api/monitor/detect',json={'camera_id':'CAM-03'}).status_code==404
        assert c.post('/api/monitor/detect-all',json={}).status_code==404

def test_detection_failure_keeps_error_and_no_fake_frames(tmp_path,monkeypatch):
    from backend.vision import detector
    monkeypatch.setenv('APP_DB',str(tmp_path/'failure.db'))
    with TestClient(app) as c:
        assert c.get('/api/monitor/latest').status_code==401
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260003','password':'123456'}).json()['data']['token']
        assert c.post('/api/monitor/detect-all',json={}).status_code==403
        assert c.post('/api/monitor/detect',json={'confidence':1.1}).status_code==422
        db.write('INSERT INTO monitor_runs(id,camera_id,status,created_by,created_at) VALUES(?,?,?,?,?)',('failure-test','CAM-03','queued',1,db.now()))
        def missing():raise FileNotFoundError('测试权重不可用')
        monkeypatch.setattr(detector,'model',missing)
        detector.process('failure-test','CAM-03',1)
        r=c.get('/api/monitor/runs/failure-test').json()['data']
        assert r['status']=='error' and 'FileNotFoundError' in r['error'] and not r['result'].get('frames')
        assert db.one('SELECT count(*) n FROM monitor_frames')['n']==0
        assert db.one("SELECT count(*) n FROM monitor_snapshots WHERE data_mode='yolo'")['n']==0
        import builtins
        real_import=builtins.__import__
        def unavailable(name,*args,**kwargs):
            if name=='cv2':raise ModuleNotFoundError('测试视频解码依赖缺失')
            return real_import(name,*args,**kwargs)
        db.write('INSERT INTO monitor_runs(id,camera_id,status,created_by,created_at) VALUES(?,?,?,?,?)',('decode-failure','CAM-03','queued',1,db.now()))
        with monkeypatch.context() as scoped:
            scoped.setattr(builtins,'__import__',unavailable)
            detector.process('decode-failure','CAM-03',1)
        assert db.one('SELECT status,error FROM monitor_runs WHERE id=?',('decode-failure',))['status']=='error'
