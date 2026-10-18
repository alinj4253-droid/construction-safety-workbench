import json
from contextlib import closing
import sqlite3
import pytest
from backend.app import db
from scripts import reset_demo

def test_reset_clones_knowledge_preserves_source_and_is_repeatable(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'ROOT',tmp_path);monkeypatch.setattr(reset_demo,'ROOT',tmp_path)
    source=tmp_path/'backend/data/original.db';monkeypatch.setenv('APP_DB',str(source))
    db.init_db(seed=False)
    with db.connect() as c:
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(1,'AQ20260001',db.password_hash('123456'),'王建国','专职安全员','测试项目','AQ20260001',db.now()))
        c.execute('INSERT INTO kb_sources(id,name,file_path) VALUES(?,?,?)',(1,'隔离测试知识元数据','fixture.txt'))
        c.execute('INSERT INTO kb_chunks VALUES(?,?,?,?,?)',('fixture',1,'测试节','隔离测试文本',1))
        c.execute('INSERT INTO chunk_states VALUES(?,?,?,?)',('fixture',1,'待核验','测试'))
        c.execute("INSERT INTO chat_sessions(id,user_id,title,created_at,updated_at) VALUES('old',1,'待保留的原会话',?,?)",(db.now(),db.now()))
        c.execute("INSERT INTO user_memories(user_id,value,active) VALUES(1,'原长期记忆',1)")
        c.execute("INSERT INTO hazards(id,code,title,track,status) VALUES(1,'OLD','原真实隐患','heavy','已销项')")
    with closing(reset_demo.ro(source)) as c:before={t:reset_demo.table_digest(c,t) for t in ('users','hazards','chat_sessions','user_memories',*reset_demo.KNOWLEDGE)}
    assert reset_demo.prepare('demo')['dry_run']
    with pytest.raises(ValueError):reset_demo.prepare('production',True)
    first=reset_demo.prepare('demo',True)
    assert first['original_data_deleted'] is False and all(first['preserved_tables'].values())
    assert (tmp_path/'backend/data/demo-runtime.json').is_file()
    with closing(reset_demo.ro(source)) as c:assert before=={t:reset_demo.table_digest(c,t) for t in before}
    firstdb=first['demo_database']
    monkeypatch.delenv('APP_DB');assert str(db.db_path())==firstdb
    assert db.one('SELECT count(*) n FROM chat_sessions')['n']==0 and db.one('SELECT count(*) n FROM user_memories')['n']==0
    assert db.one('SELECT count(*) n FROM documents')['n']==0 and db.one('SELECT count(*) n FROM hazards')['n']==4
    assert db.one('SELECT status FROM hazards WHERE id=1')['status']=='待整改'
    assert db.one('SELECT count(*) n FROM handle_tasks')['n']==0
    assert all(s['status']=='pending' and s['data_mode']=='demo' and s['confidence'] is None for s in db.rows('SELECT * FROM monitor_snapshots'))
    second=reset_demo.prepare('demo',True)
    assert second['generation']!=first['generation'] and second['demo_database']!=firstdb
    assert __import__('pathlib').Path(firstdb).is_file() and __import__('pathlib').Path(second['backup'],'database.db').is_file()
    config=json.loads((tmp_path/'backend/data/demo-runtime.json').read_text(encoding='utf-8'))
    assert config['generation']==second['generation']
