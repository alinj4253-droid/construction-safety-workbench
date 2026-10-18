"""SQLite business store. No dependency on either legacy application's imports."""
from __future__ import annotations
import csv
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=8))

def now():
    return datetime.now(TZ).isoformat(timespec='seconds')

def today():
    return datetime.now(TZ).date()

def db_path():
    if os.getenv('APP_DB'):return Path(os.environ['APP_DB'])
    config=ROOT/'backend/data/demo-runtime.json'
    if config.is_file():
        active=json.loads(config.read_text(encoding='utf-8'))
        selected=(ROOT/active['database']).resolve()
        if active.get('environment')!='demo' or not selected.is_relative_to((ROOT/'backend/data/demo').resolve()) or not selected.is_file():raise ValueError('演示数据库配置无效，拒绝自动选择其他数据库')
        return selected
    return ROOT/'backend/data/app.db'

@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def rows(sql, params=()):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]

def one(sql, params=()):
    rs = rows(sql, params)
    return rs[0] if rs else None

def write(sql, params=()):
    with connect() as c:
        return c.execute(sql, params).lastrowid

def dumps(x):
    return json.dumps(x, ensure_ascii=False)

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 180000).hex()

def password_ok(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)

def audit(c, actor, action, kind, object_id, detail=None):
    c.execute('INSERT INTO audit_logs(actor,action,object_type,object_id,detail,created_at) VALUES(?,?,?,?,?,?)',
              (str(actor), action, kind, str(object_id), dumps(detail or {}), now()))

def event(c, hazard_id, action, actor, detail=None):
    c.execute('INSERT INTO hazard_events(hazard_id,action,actor,detail,created_at) VALUES(?,?,?,?,?)',
              (hazard_id, action, str(actor), dumps(detail or {}), now()))
    audit(c, actor, action, 'hazard', hazard_id, detail)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS runtime_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,display_name TEXT,role TEXT,project TEXT,employee_no TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS tokens(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),expires_at TEXT);
CREATE TABLE IF NOT EXISTS hazards(id INTEGER PRIMARY KEY,code TEXT UNIQUE NOT NULL,title TEXT NOT NULL,category TEXT,location TEXT,description TEXT,track TEXT CHECK(track IN('light','heavy')) NOT NULL,level TEXT,status TEXT CHECK(status IN('待确认','待整改','整改中','待复查','已闭环','已销项')) NOT NULL,source TEXT CHECK(source IN('manual','ai_monitor','document')),responsible_team TEXT,responsible_person TEXT,deadline TEXT,rectify_note TEXT,review_note TEXT,created_by INTEGER REFERENCES users(id),created_at TEXT,confirmed_at TEXT,closed_at TEXT,version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS hazard_events(id INTEGER PRIMARY KEY,hazard_id INTEGER REFERENCES hazards(id),action TEXT,actor TEXT,detail TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,doc_no TEXT UNIQUE,hazard_id INTEGER REFERENCES hazards(id),type TEXT,title TEXT,content_json TEXT,draft_version INTEGER DEFAULT 1,status TEXT CHECK(status IN('draft','reviewing','rework','pending_human','issued','archived')),created_by INTEGER REFERENCES users(id),created_at TEXT,issued_by INTEGER REFERENCES users(id),issued_at TEXT);
CREATE TABLE IF NOT EXISTS document_versions(id INTEGER PRIMARY KEY,document_id INTEGER REFERENCES documents(id),version INTEGER,content_json TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS document_reviews(id INTEGER PRIMARY KEY,document_id INTEGER REFERENCES documents(id),round INTEGER,reviewer TEXT,result_json TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS handle_tasks(id TEXT PRIMARY KEY,hazard_id INTEGER REFERENCES hazards(id),document_id INTEGER REFERENCES documents(id),status TEXT,steps_json TEXT,note TEXT,created_by INTEGER REFERENCES users(id),created_at TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS kb_sources(id INTEGER PRIMARY KEY,name TEXT,category TEXT,doc_no TEXT,publish_date TEXT,effective_date TEXT,region TEXT,status TEXT CHECK(status IN('现行','待核验','历史版本')),legal_status TEXT DEFAULT '待核验',source_url TEXT,file_path TEXT UNIQUE,sha256 TEXT,cite_count INTEGER DEFAULT 0,created_at TEXT,parsed INTEGER DEFAULT 0,parse_note TEXT,content_kind TEXT,verified_by TEXT,verified_at TEXT);
CREATE TABLE IF NOT EXISTS kb_chunks(chunk_id TEXT PRIMARY KEY,source_id INTEGER REFERENCES kb_sources(id),section TEXT,text TEXT,page INTEGER,UNIQUE(source_id,section,text));
CREATE TABLE IF NOT EXISTS version_rules(old_no TEXT PRIMARY KEY,new_no TEXT,effective_date TEXT,basis_url TEXT);
CREATE TABLE IF NOT EXISTS kb_changes(id INTEGER PRIMARY KEY,source_id INTEGER REFERENCES kb_sources(id),action TEXT,before_json TEXT,after_json TEXT,actor TEXT,created_at TEXT,undone INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS document_citations(document_id INTEGER REFERENCES documents(id),chunk_id TEXT REFERENCES kb_chunks(chunk_id),snapshot_json TEXT,PRIMARY KEY(document_id,chunk_id));
CREATE TABLE IF NOT EXISTS monitor_snapshots(id INTEGER PRIMARY KEY,camera_id TEXT,captured_at TEXT,category TEXT,confidence REAL,location TEXT,image_path TEXT,status TEXT CHECK(status IN('pending','confirmed','dismissed')),hazard_id INTEGER UNIQUE REFERENCES hazards(id),note TEXT,data_mode TEXT DEFAULT 'demo',dedup_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS monitor_stats_daily(date TEXT PRIMARY KEY,on_site_count INTEGER,no_helmet_count INTEGER,no_vest_count INTEGER,peak_hour TEXT,hot_zone TEXT,data_mode TEXT DEFAULT 'demo');
CREATE TABLE IF NOT EXISTS chat_sessions(id TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),title TEXT,summary TEXT DEFAULT '',created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY,session_id TEXT REFERENCES chat_sessions(id) ON DELETE CASCADE,role TEXT,content TEXT,sources TEXT DEFAULT '[]',created_at TEXT);
CREATE TABLE IF NOT EXISTS chat_runs(id TEXT PRIMARY KEY,session_id TEXT REFERENCES chat_sessions(id) ON DELETE CASCADE,user_id INTEGER REFERENCES users(id),status TEXT,answer TEXT DEFAULT '',references_json TEXT DEFAULT '[]',mode TEXT,status_message TEXT,error TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS attachments(id INTEGER PRIMARY KEY,hazard_id INTEGER REFERENCES hazards(id),kind TEXT,file_path TEXT,original_name TEXT,created_by INTEGER REFERENCES users(id),created_at TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,object_type TEXT,object_id TEXT,detail TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS user_memories(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),value TEXT,source_session_id TEXT,source_message_id INTEGER,created_at TEXT,updated_at TEXT,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS session_summaries(session_id TEXT PRIMARY KEY REFERENCES chat_sessions(id) ON DELETE CASCADE,summary TEXT,summarized_through INTEGER DEFAULT 0,source_message_ids TEXT DEFAULT '[]',updated_at TEXT);
CREATE TABLE IF NOT EXISTS task_inputs(task_id TEXT PRIMARY KEY REFERENCES handle_tasks(id),facts_json TEXT,test_case TEXT);
CREATE TABLE IF NOT EXISTS hazard_demo_cases(hazard_id INTEGER PRIMARY KEY REFERENCES hazards(id),feedback_content TEXT NOT NULL,feedback_team TEXT NOT NULL,prepared_by INTEGER REFERENCES users(id),prepared_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hazard_feedbacks(id INTEGER PRIMARY KEY,hazard_id INTEGER NOT NULL REFERENCES hazards(id),content TEXT NOT NULL,responsible_team TEXT,feedback_source TEXT NOT NULL,provided_by TEXT,provided_at TEXT,recorded_by INTEGER REFERENCES users(id),recorded_at TEXT NOT NULL,is_simulated INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_feedback_hazard ON hazard_feedbacks(hazard_id,id);
CREATE TABLE IF NOT EXISTS chunk_states(chunk_id TEXT PRIMARY KEY REFERENCES kb_chunks(chunk_id),active INTEGER DEFAULT 1,legal_status TEXT DEFAULT '现行',note TEXT);
CREATE TABLE IF NOT EXISTS monitor_runs(id TEXT PRIMARY KEY,camera_id TEXT,status TEXT,result_json TEXT,error TEXT,created_by INTEGER REFERENCES users(id),created_at TEXT,finished_at TEXT);
CREATE TABLE IF NOT EXISTS monitor_frames(id INTEGER PRIMARY KEY,run_id TEXT REFERENCES monitor_runs(id),camera_id TEXT,media_time REAL,image_path TEXT,detections_json TEXT,created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_hazards_status ON hazards(status,deadline);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON kb_chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id,id);
'''

def init_db(seed=True):
    with connect() as c:
        c.executescript(SCHEMA)
        if seed and not c.execute('SELECT 1 FROM users').fetchone():
            for i, (name, role) in enumerate([('王建国','专职安全员'),('李文静','安全员'),('张志强','项目安全总监')],1):
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)', (i,f'AQ2026000{i}',password_hash('123456'),name,role,'厦门示范房建项目',f'AQ2026000{i}',now()))
            specs=[('3#楼东侧基坑临边防护缺失，未设防护栏杆','木工班组','heavy','整改中',-1,'manual'),
                   ('2#楼3层临时用电私拉乱接，未用配电箱','电工班组','heavy','待复查',1,'manual'),
                   ('外脚手架连墙件数量不足，间距超限','架子工班组','heavy','待复查',1,'manual'),
                   ('钢筋加工区未戴安全帽（已现场确认）','钢筋班组','light','整改中',None,'ai_monitor'),
                   ('主通道未穿反光衣（历史演示，已现场确认）','杂工班组','light','整改中',None,'manual'),
                   ('4#楼卸料平台限载标识缺失','架子工班组','heavy','已销项',-4,'manual')]
            for i,(title,team,track,status,offset,source) in enumerate(specs,1):
                deadline=str(today()+timedelta(days=offset)) if offset is not None else None
                stamp=now()
                c.execute('INSERT INTO hazards(id,code,title,category,location,description,track,level,status,source,responsible_team,responsible_person,deadline,created_by,created_at,confirmed_at,closed_at,review_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (i,f'HZ-{today():%Y%m%d}-{i:04d}',title,'临边防护' if i==1 else '临时用电' if i==2 else '脚手架' if i==3 else '个人防护',title.split('，')[0],title,track,'一般隐患' if track=='heavy' else '轻微违章',status,source,team,'种子记录责任人',deadline,1,stamp,stamp,stamp if status=='已销项' else None,'历史复查已确认' if status=='已销项' else None))
                event(c,i,'seed_confirmed',1,{'note':'演示历史事项，已人工确认；不与今日 pending 抓拍混计'})
            for i,(cat,loc,hm) in enumerate([('未戴安全帽','钢筋加工区','09:14'),('未戴安全帽','钢筋加工区','09:31'),('未穿反光衣','主通道','10:02'),('未戴安全帽','3#楼东侧','10:20')],1):
                c.execute('INSERT INTO monitor_snapshots(camera_id,captured_at,category,confidence,location,status,data_mode,dedup_key) VALUES(?,?,?,?,?,?,?,?)',
                          (f'CAM-0{(i-1)%4+1}',f'{today()}T{hm}:00+08:00',cat,[.87,.82,.79,.85][i-1],loc,'pending','demo',f'seed-{today()}-{i}'))
            c.execute('INSERT INTO monitor_stats_daily VALUES(?,?,?,?,?,?,?)',(str(today()),87,3,1,'09:00–10:00','钢筋加工区','demo'))
        if seed and not c.execute('SELECT 1 FROM kb_sources').fetchone():
            manifest=ROOT/'施工安全RAG知识源/清单/施工安全RAG知识源_来源总清单_20261015.csv'
            for r in csv.DictReader(manifest.open(encoding='utf-8-sig')):
                rel=r['相对路径']; historical='历史' in r['时效状态'] or '2022版' in r['文件名'] or r['文件名']=='PD2022_att3.docx'
                cat='案例参考' if '05_' in rel else '法规依据'
                c.execute('INSERT INTO kb_sources(name,category,doc_no,publish_date,effective_date,region,status,legal_status,source_url,file_path,sha256,created_at,content_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (r['资料名称'],cat,r['文号/标准号'],r['成文/发布日期'],r['实施日期'],r['地区/层级'],'历史版本' if historical else '待核验','已废止' if historical else '待核验',r['来源URL'],str(Path('施工安全RAG知识源')/rel),r['SHA256'],now(),r['内容类型']))
        for old,new,date in [('JGJ46-2005','JGJ/T46-2024','2025-01-01'),('建质规〔2022〕2号','建质规〔2024〕5号','2024-12-13'),('建质〔2008〕75号','2025修订','2026-06-01'),('DBJ/T13-91-2017','DBJ/T13-91-2025','2025-09-01'),('DBJ/T13-318-2019','DBJ/T13-318-2025','2025-09-01')]:
            c.execute('INSERT OR IGNORE INTO version_rules VALUES(?,?,?,?)',(old,new,date,'来源包版本关系，待逐项核实'))

TERMINAL={'已闭环','已销项'}
def overdue(h):
    return bool(h.get('deadline') and h['status'] not in TERMINAL and h['deadline'][:10] < str(today()))

def next_status(track,status,action,note=''):
    mapping={'light':{('待确认','confirm'):'整改中',('整改中','submit_rectify'):'已闭环'},
             'heavy':{('待整改','start_rectify'):'整改中',('整改中','submit_rectify'):'待复查',('待复查','review_close'):'已销项',('待复查','review_return'):'整改中'}}
    if action=='urge' and status not in TERMINAL:return status
    result=mapping.get(track,{}).get((status,action))
    if not result:raise ValueError('非法状态流转')
    if action in {'submit_rectify','review_close','review_return'} and not note.strip():raise ValueError('请填写整改记录或复查意见')
    return result

if __name__=='__main__':
    init_db()
    print(dumps({'hazards':one('SELECT count(*) n FROM hazards')['n'],'sources':one('SELECT count(*) n FROM kb_sources')['n']}))
