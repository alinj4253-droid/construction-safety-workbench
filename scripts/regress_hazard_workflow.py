from __future__ import annotations
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
os.environ['LLM_ENABLED']='0'
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def digest(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        return hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()

def main():
    from backend.app import db
    source_db=db.db_path().resolve();before=digest(source_db);connect=sqlite3.connect
    def guarded(database,*args,**kwargs):
        if not str(database).startswith('file:') and Path(database).resolve()==source_db:raise RuntimeError('禁止回归测试写入原数据库')
        if source_db.as_uri() in str(database) and 'mode=ro' not in str(database):raise RuntimeError('禁止回归测试写入原数据库')
        return connect(database,*args,**kwargs)
    sqlite3.connect=guarded
    temporary=ROOT/'artifacts/tmp';temporary.mkdir(parents=True,exist_ok=True)
    sandbox=Path(tempfile.mkdtemp(prefix='hazard-workflow-',dir=temporary))
    for directory in ('backend','frontend'):shutil.copytree(ROOT/directory,sandbox/directory,ignore=shutil.ignore_patterns('data','__pycache__'))
    shutil.copytree(ROOT/'videos',sandbox/'videos')
    (sandbox/'artifacts').mkdir();shutil.copy2(ROOT/'artifacts/p1-dashboard.png',sandbox/'artifacts/p1-dashboard.png')
    manifest=Path('施工安全RAG知识源/清单/施工安全RAG知识源_来源总清单_20261015.csv')
    (sandbox/manifest).parent.mkdir(parents=True);shutil.copy2(ROOT/manifest,sandbox/manifest)
    db.ROOT=sandbox;os.environ['APP_DB']=str(sandbox/'backend/data/seed.db');db.init_db()
    with closing(sqlite3.connect(source_db.as_uri()+'?mode=ro',uri=True)) as source,db.connect() as target:
        for table in ('chunk_states','kb_chunks','kb_changes','kb_sources','version_rules'):target.execute('DELETE FROM '+table)
        for table in ('kb_sources','kb_chunks','chunk_states','version_rules'):
            rows=source.execute('SELECT * FROM '+table).fetchall()
            if rows:target.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
    import pytest
    code=pytest.main([str(ROOT/'backend/tests'),'-q','--maxfail=1','-k','not rank_stable_across_processes','--junitxml='+str(ROOT/'artifacts/hazard-workflow-tests.xml')])
    if (sandbox/'artifacts/e2e-results.json').is_file():shutil.copy2(sandbox/'artifacts/e2e-results.json',ROOT/'artifacts/hazard-workflow-e2e.json')
    after=digest(source_db)
    report={'sandbox':str(sandbox),'database':str(db.db_path()),'pytest_exit_code':int(code),'single_process':True,'cpu_threads':1,'excluded':'原跨进程排序测试，遵守串行测试要求','original_database_write_forbidden':True,'original_database_unchanged':before==after,'live_database_note':'运行中的主服务可能继续写入真实会话或操作；全库摘要变化不作为回滚依据，测试连接禁止写原库'}
    (ROOT/'artifacts/hazard-workflow-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
    return int(code)

if __name__=='__main__':raise SystemExit(main())
