from __future__ import annotations
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[name]='1'
os.environ['LLM_ENABLED']='0'
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def digest_store(path):
    digest=hashlib.sha256()
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        for line in c.iterdump():digest.update(line.encode('utf-8'));digest.update(b'\n')
    return digest.hexdigest()

def file_digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--online',action='store_true');args=parser.parse_args()
    from backend.app import db
    original_db=db.db_path().resolve();before=digest_store(original_db)
    connect=sqlite3.connect
    def isolated_connect(database,*positional,**keywords):
        value=str(database)
        if not value.startswith('file:') and Path(value).resolve()==original_db:raise RuntimeError('回归测试禁止以可写连接访问原数据库')
        if value.startswith('file:') and original_db.as_uri() in value and 'mode=ro' not in value:raise RuntimeError('回归测试禁止以可写连接访问原数据库')
        return connect(database,*positional,**keywords)
    sqlite3.connect=isolated_connect
    index_before=file_digest(ROOT/'backend/data/index.npz')
    with closing(sqlite3.connect(original_db.as_uri()+'?mode=ro',uri=True)) as c:
        materials=[ROOT/r[0] for r in c.execute('SELECT file_path FROM kb_sources')]
    source_hashes={str(p):file_digest(p) for p in materials}
    temporary=ROOT/'artifacts/tmp';temporary.mkdir(parents=True,exist_ok=True)
    sandbox=Path(tempfile.mkdtemp(prefix='assistant-fix-',dir=temporary))
    (sandbox/'artifacts').mkdir();(sandbox/'videos').mkdir();(sandbox/'backend/data').mkdir(parents=True)
    shutil.copytree(ROOT/'frontend',sandbox/'frontend')
    picture=ROOT/'artifacts/p1-dashboard.png'
    if picture.is_file():shutil.copy2(picture,sandbox/'artifacts/p1-dashboard.png')
    manifest=Path('施工安全RAG知识源/清单/施工安全RAG知识源_来源总清单_20261015.csv')
    (sandbox/manifest).parent.mkdir(parents=True);shutil.copy2(ROOT/manifest,sandbox/manifest)
    original_root=db.ROOT;original_env=os.environ.get('APP_DB')
    db.ROOT=sandbox;os.environ['APP_DB']=str(sandbox/'backend/data/seed.db')
    db.init_db()
    with closing(sqlite3.connect(original_db.as_uri()+'?mode=ro',uri=True)) as source,db.connect() as target:
        for table in ('chunk_states','kb_chunks','kb_changes','kb_sources','version_rules'):target.execute('DELETE FROM '+table)
        for table in ('kb_sources','kb_chunks','chunk_states','version_rules'):
            rows=source.execute('SELECT * FROM '+table).fetchall()
            if rows:target.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
    import pytest
    try:
        code=pytest.main([str(ROOT/'backend/tests'),'-q','--maxfail=1','-k','not rank_stable_across_processes','--junitxml='+str(ROOT/'artifacts/assistant-fix-tests.xml')])
        for src,dest in [('e2e-results.json','assistant-fix-e2e.json'),('assistant-conversation-regression.json','assistant-conversation-regression.json')]:
            if (sandbox/'artifacts'/src).exists():shutil.copy2(sandbox/'artifacts'/src,ROOT/'artifacts'/dest)
        online=[]
        if code==0 and args.online:
            from backend.app.llm import config
            db.ROOT=original_root
            if config().get('OPENAI_API_KEY'):
                os.environ['LLM_ENABLED']='1'
                from fastapi.testclient import TestClient
                from backend.app.main import app
                with TestClient(app) as c:
                    c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
                    sid=None
                    for question in ['基坑临边防护有什么要求？','那工地上，这种防护常见的不规范情况有哪些？','那这个防护常见的隐患有哪些？','施工临时用电接地要求']:
                        response=c.post('/api/chat/stream',json={'message':question,'session_id':sid})
                        assert response.status_code==200,response.text
                        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                        assert events[-1]['type']=='done',events
                        sid=events[0]['session_id'];answer=''.join(e.get('content','') for e in events if e['type']=='token')
                        references=events[-1]['references'];assert references and '未检索到相关依据' not in answer
                        online.append({'question':question,'answer':answer,'mode':events[-1]['mode'],'references':references})
                (ROOT/'artifacts/assistant-online-regression.json').write_text(json.dumps(online,ensure_ascii=False,indent=2),encoding='utf-8')
        after=digest_store(original_db)
        unchanged=before==after and index_before==file_digest(ROOT/'backend/data/index.npz') and all(file_digest(Path(p))==digest for p,digest in source_hashes.items())
        result={'pytest_exit_code':int(code),'single_process':True,'numeric_threads':1,'excluded':'原跨进程hash稳定性测试，遵守本轮单进程要求','source_writable_connections_forbidden':True,'source_database_unchanged':before==after,'source_database_digest_before':before,'source_database_digest_after':after,'knowledge_materials_unchanged':all(file_digest(Path(p))==digest for p,digest in source_hashes.items()),'original_index_unchanged':index_before==file_digest(ROOT/'backend/data/index.npz'),'online_turns':len(online),'online_modes':[r['mode'] for r in online]}
        (ROOT/'artifacts/assistant-fix-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
        return int(code) if unchanged else 1
    finally:
        sqlite3.connect=connect
        db.ROOT=original_root
        if original_env is None:os.environ.pop('APP_DB',None)
        else:os.environ['APP_DB']=original_env

if __name__=='__main__':raise SystemExit(main())
