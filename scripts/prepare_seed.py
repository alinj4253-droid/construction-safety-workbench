"""Create a NEW clean demo store from reviewed source metadata, without copying QA business data."""
import argparse
import os
import sqlite3
from pathlib import Path
from backend.app import db
from backend.rag.knowledge import Knowledge

def prepare(source_path,output):
    source_path=Path(source_path).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('目标数据库已存在，拒绝覆盖。请指定一个新文件。')
    if not source_path.is_file():raise ValueError('知识库参考数据库不存在')
    output.parent.mkdir(parents=True,exist_ok=True)
    old=os.environ.get('APP_DB');os.environ['APP_DB']=str(output)
    try:
        db.init_db()
        with sqlite3.connect(source_path) as src,db.connect() as dst:
            src.row_factory=sqlite3.Row
            sources=[dict(r) for r in src.execute("SELECT * FROM kb_sources WHERE file_path NOT LIKE 'backend/data/uploads/%' AND file_path NOT LIKE 'backend\\data\\uploads\\%' ORDER BY id")]
            ids={s['id'] for s in sources};chunks=[dict(r) for r in src.execute('SELECT * FROM kb_chunks') if r['source_id'] in ids];keys={k['chunk_id'] for k in chunks}
            states=[dict(r) for r in src.execute('SELECT * FROM chunk_states') if r['chunk_id'] in keys]
            changes=[dict(r) for r in src.execute("SELECT * FROM kb_changes WHERE action='initial_source_validation'") if r['source_id'] in ids]
            for table in ['chunk_states','kb_chunks','kb_changes','kb_sources']:dst.execute('DELETE FROM '+table)
            def insert(table,rows):
                if rows:
                    fields=list(rows[0]);dst.executemany('INSERT INTO '+table+'('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',[tuple(r[k] for k in fields) for r in rows])
            for s in sources:s['cite_count']=0
            insert('kb_sources',sources);insert('kb_chunks',chunks);insert('chunk_states',states);insert('kb_changes',changes)
            db.audit(dst,'system','prepare_clean_demo','system','seed',{'sources':len(sources),'hazards':6,'pending_demo_clues':4,'no_qa_documents_or_chats':True})
            assert not dst.execute('PRAGMA foreign_key_check').fetchall()
        Knowledge().save()
        return {'path':str(output),'sources':len(sources),'parsed':sum(s['parsed'] for s in sources),'approved':sum(s['status']=='现行' for s in sources),'chunks':len(chunks),'hazards':db.one('SELECT count(*) n FROM hazards')['n'],'documents':db.one('SELECT count(*) n FROM documents')['n']}
    finally:
        if old is None:os.environ.pop('APP_DB',None)
        else:os.environ['APP_DB']=old

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',default='backend/data/app.db');p.add_argument('--output',required=True);a=p.parse_args();print(db.dumps(prepare(a.source,a.output)))
