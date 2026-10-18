import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
import json
import argparse
from contextlib import closing
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--clean-demo',action='store_true');args=parser.parse_args()
    info=json.loads((ROOT/'artifacts/hazard-workflow-verification.json').read_text(encoding='utf-8'))
    sandbox=Path(info['sandbox'])
    from backend.app import db
    original=db.db_path().resolve();connect=sqlite3.connect
    def guarded(database,*args,**kwargs):
        if not str(database).startswith('file:') and Path(database).resolve()==original:raise RuntimeError('禁止在线回归写原数据库')
        return connect(database,*args,**kwargs)
    sqlite3.connect=guarded
    if not (ROOT/'.env').is_file():raise RuntimeError('未配置在线模型，本脚本不能伪造在线验证成功')
    if args.clean_demo:
        output=sandbox/'backend/data'/('demo-rehearsal-'+__import__('uuid').uuid4().hex+'.db')
        with closing(connect(original.as_uri()+'?mode=ro',uri=True)) as source,closing(connect(output)) as target:source.backup(target)
        info['database']=str(output)
    shutil.copy2(ROOT/'.env',sandbox/'.env')
    db.ROOT=sandbox;os.environ['APP_DB']=info['database'];os.environ['LLM_ENABLED']='1'
    from fastapi.testclient import TestClient
    from backend.app.main import app
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        h=c.get('/api/hazards/1').json()['data'] if args.clean_demo else c.post('/api/hazards/demo-cases',json={'confirmed':True}).json()['data'];hid=h['id']
        response=c.post('/api/handle/tasks',json={'hazard_id':hid});assert response.status_code==200,response.text
        tid=response.json()['data']['task_id'];deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            task=c.get('/api/handle/tasks/'+tid).json()['data']
            if task['status'] in {'pending_human','needs_input','error'}:break
            time.sleep(.5)
        document=task.get('document') or {};content=document.get('content') or {}
        modes={role:meta.get('mode') for role,meta in content.get('models',{}).items()}
        report={'environment':'隔离数据库，读取现有在线模型配置，不使用原库业务数据进行测试写入','hazard_id':hid,'task_id':tid,'task_status':task['status'],'agent_modes':modes,'source_database_write_forbidden':True}
        if task['status']=='pending_human' and modes=={'a':'online','b':'online'}:
            did=task['document_id'];assert c.post(f'/api/documents/{did}/issue',json={'confirmed':True}).status_code==200
            assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','feedback_source':'demo_simulation'}).json()['data']['status']=='待复查'
            assert c.post(f'/api/hazards/{hid}/actions',json={'action':'review_close','note':'整改合格'}).json()['data']['status']=='已销项'
            archive=c.get(f'/api/hazards/{hid}').json()['data'];assert archive['feedbacks'][0]['is_simulated'] and archive['review_note']=='整改合格'
            assert c.get(f'/api/documents/{did}/export').content.startswith(b'PK')
            report.update(result='通过',document_id=did,final_status='已销项',word_export=True)
        else:report.update(result='未通过在线验证',blocking_issues=[p.get('type') for r in document.get('reviews',[]) for p in json.loads(r['result_json']).get('issues',[]) if p.get('block')])
        (ROOT/'artifacts'/('demo-rehearsal-online.json' if args.clean_demo else 'hazard-workflow-online.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
        return 0 if report['result']=='通过' else 1

if __name__=='__main__':raise SystemExit(main())
