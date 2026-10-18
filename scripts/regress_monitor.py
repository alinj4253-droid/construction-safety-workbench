from __future__ import annotations
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
os.environ['LLM_ENABLED']='0'
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from backend.app import db
    original_db=db.db_path().resolve()
    connect=sqlite3.connect
    def guarded(database,*args,**kwargs):
        if not str(database).startswith('file:') and Path(database).resolve()==original_db:raise RuntimeError('禁止测试写入原数据库')
        if original_db.as_uri() in str(database) and 'mode=ro' not in str(database):raise RuntimeError('禁止测试写入原数据库')
        return connect(database,*args,**kwargs)
    sqlite3.connect=guarded
    base=ROOT/'artifacts/tmp';base.mkdir(parents=True,exist_ok=True)
    sandbox=Path(tempfile.mkdtemp(prefix='monitor-fix-',dir=base))
    for directory in ('frontend','backend'):
        shutil.copytree(ROOT/directory,sandbox/directory,ignore=shutil.ignore_patterns('data','__pycache__'))
    shutil.copytree(ROOT/'videos',sandbox/'videos')
    weight=Path('construction-safety-inspection/models/helmet_yolo11n/weights/best.pt')
    (sandbox/weight).parent.mkdir(parents=True);shutil.copy2(ROOT/weight,sandbox/weight)
    manifest=Path('施工安全RAG知识源/清单/施工安全RAG知识源_来源总清单_20261015.csv')
    (sandbox/manifest).parent.mkdir(parents=True);shutil.copy2(ROOT/manifest,sandbox/manifest)
    db.ROOT=sandbox;os.environ['APP_DB']=str(sandbox/'backend/data/monitor-test.db')
    db.init_db()
    (sandbox/'artifacts').mkdir()
    shutil.copy2(ROOT/'artifacts/p1-dashboard.png',sandbox/'artifacts/p1-dashboard.png')
    source=sqlite3.connect(original_db.as_uri()+'?mode=ro',uri=True)
    try:
        with db.connect() as target:
            for table in ('chunk_states','kb_chunks','kb_changes','kb_sources','version_rules'):target.execute('DELETE FROM '+table)
            for table in ('kb_sources','kb_chunks','chunk_states','version_rules'):
                rows=source.execute('SELECT * FROM '+table).fetchall()
                if rows:target.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
    finally:source.close()
    import pytest
    code=pytest.main([str(ROOT/'backend/tests'/name) for name in ('test_monitor.py','test_dashboard.py','test_auth.py','test_identity.py','test_hazards.py')]+['-q','--maxfail=1','--junitxml='+str(ROOT/'artifacts/monitor-fix-tests.xml')])
    if code:return int(code)
    from fastapi.testclient import TestClient
    from backend.app.main import app
    results=[]
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        hazards_before=db.one('SELECT count(*) n FROM hazards')['n']
        start=time.monotonic();response=c.post('/api/monitor/detect-all',json={'max_frames':8});assert response.status_code==200,response.text
        jobs=response.json()['data']['runs']
        assert c.post('/api/monitor/detect-all',json={}).status_code==409
        for job in jobs:
            deadline=time.monotonic()+240
            while time.monotonic()<deadline:
                r=c.get('/api/monitor/runs/'+job['id']).json()['data']
                if r['status'] in {'done','error'}:break
                time.sleep(.3)
            assert r['status']=='done',r
            frames=r['result']['frames'];assert len(frames)==8
            for f in frames:
                image=c.get('/api/monitor/frames/'+str(f['id']));assert image.status_code==200 and image.headers['content-type']=='image/jpeg'
                assert f['helmet_on']==sum(d['class_id']==0 for d in f['detections'])
                assert f['helmet_off']==sum(d['class_id']==1 for d in f['detections'])
                assert all(.35<=d['confidence']<=1 and len(d['bbox'])==4 for d in f['detections'])
            best=max(frames,key=lambda f:f['helmet_on']+f['helmet_off'])
            (ROOT/'artifacts'/('monitor-fix-'+job['camera_id']+'.jpg')).write_bytes(c.get('/api/monitor/frames/'+str(best['id'])).content)
            results.append({'camera_id':job['camera_id'],'run_id':r['id'],'status':r['status'],'frames':frames,'new_clues':r['result']['new_clues'],'sampling':r['result']['sampling'],'duration':r['result']['duration'],'confidence_threshold':r['result']['confidence_threshold'],'applicability':r['result']['applicability'],'model_classes':r['result']['model_classes']})
            print(json.dumps({'camera':job['camera_id'],'frames':len(frames),'head_targets_per_sample':[f['helmet_on']+f['helmet_off'] for f in frames],'new_clues':r['result']['new_clues']},ensure_ascii=False),flush=True)
            assert c.get('/videos/'+next(x['file'] for x in c.get('/api/monitor/overview').json()['data']['cameras'] if x['id']==job['camera_id']),headers={'Range':'bytes=0-100'}).status_code==206
        assert db.one('SELECT count(*) n FROM hazards')['n']==hazards_before
        overview=c.get('/api/monitor/overview').json()['data'];home=c.get('/api/dashboard/summary').json()['data']['monitor_today']
        assert all(overview[k]==home[k] for k in home if k!='updated_at')
        pending=c.get('/api/monitor/snapshots?status=pending').json()['data'];actual=[s for s in pending if s['data_mode']=='yolo'];assert len(actual)>=2
        before=overview['real']['no_helmet']
        confirm=c.post(f"/api/monitor/snapshots/{actual[0]['id']}/confirm",json={'note':'隔离环境人工确认流程回归，非真实现场事实'})
        assert confirm.status_code==200
        assert c.post(f"/api/monitor/snapshots/{actual[1]['id']}/dismiss",json={'note':'隔离环境驳回流程回归'}).status_code==200
        home=c.get('/api/dashboard/summary').json()['data']['monitor_today'];assert home['real']['no_helmet']==before-1 and home['real']['confirmed_today']==1 and home['real']['dismissed_today']==1
        assert db.one('SELECT count(*) n FROM hazards')['n']==hazards_before+1
        repeat=c.post('/api/monitor/detect',json={'camera_id':'CAM-03','max_frames':8}).json()['data']['id']
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            repeated=c.get('/api/monitor/runs/'+repeat).json()['data']
            if repeated['status'] in {'done','error'}:break
            time.sleep(.3)
        assert repeated['status']=='done' and repeated['result']['new_clues']==0,repeated
        report={'sandbox':str(sandbox),'database':str(db.db_path()),'single_inference_worker':True,'cpu_threads':1,'source_database_write_forbidden':True,'elapsed_seconds':round(time.monotonic()-start,2),'four_cameras':results,'summary':home,'repeat_new_clues':0,'manual_confirmation_preserved':True,'home_monitor_equal':True}
        (ROOT/'artifacts/monitor-fix-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ('four_cameras','summary')},ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
