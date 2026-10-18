import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app import db

KNOWLEDGE=('kb_sources','kb_chunks','chunk_states','version_rules','kb_changes')
BUSINESS=('chat_sessions','chat_messages','chat_runs','user_memories','session_summaries','documents','document_versions','document_reviews','document_citations','handle_tasks','task_inputs','hazard_feedbacks','attachments','hazards','hazard_events','monitor_snapshots','monitor_runs','monitor_frames')

def ro(path):return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)

def table_digest(conn,table):
    rows=conn.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
    return hashlib.sha256(json.dumps([list(row) for row in rows],ensure_ascii=False).encode()).hexdigest()

def prepare(environment,execute=False):
    if environment!='demo' or os.getenv('APP_ENV','').lower() in {'production','prod'}:raise ValueError('此脚本仅允许 --environment demo，禁止生产环境执行')
    source=db.db_path().resolve()
    with closing(ro(source)) as src:
        counts={table:src.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in BUSINESS}
        active=sum(src.execute('SELECT count(*) FROM '+table+' WHERE status IN ('+','.join('?' for _ in states)+')',states).fetchone()[0] for table,states in [('chat_runs',('queued','running')),('handle_tasks',('queued','drafting','rule_check','reviewing','rework')),('monitor_runs',('queued','running'))])
    if active:raise ValueError('仍有任务运行，拒绝初始化；请等待任务完成并停止本地服务')
    if not execute:return {'dry_run':True,'source':str(source),'original_data_deleted':False,'old_business_counts':counts}
    generation=db.now().replace(':','').replace('+','_')+'-'+uuid.uuid4().hex[:8]
    backup=ROOT/'backend/data/backups'/('demo-init-'+generation);backup.mkdir(parents=True,exist_ok=False)
    with closing(ro(source)) as src,closing(sqlite3.connect(backup/'database.db')) as target:src.backup(target)
    with closing(ro(backup/'database.db')) as src:
        files={r[0] for table,column in [('attachments','file_path'),('monitor_frames','image_path'),('monitor_snapshots','image_path')] for r in src.execute('SELECT '+column+' FROM '+table) if r[0]}
    copied=[];missing=[]
    for relative in sorted(files):
        file=(ROOT/relative).resolve()
        if not file.is_relative_to(ROOT):raise ValueError('存在项目目录外的附件，请先人工核对：'+str(file))
        if not file.is_file():missing.append(relative);continue
        destination=backup/'files'/file.relative_to(ROOT);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,destination)
        with destination.open('rb') as f:copied.append({'path':relative,'sha256':hashlib.file_digest(f,'sha256').hexdigest()})
    config=ROOT/'backend/data/demo-runtime.json'
    if config.is_file():shutil.copy2(config,backup/'previous-demo-runtime.json')
    directory=ROOT/'backend/data/demo';directory.mkdir(exist_ok=True)
    output=directory/(generation+'.db');previous=os.environ.get('APP_DB');os.environ['APP_DB']=str(output)
    try:
        db.init_db(seed=False)
        with closing(ro(backup/'database.db')) as src,db.connect() as dst:
            src.row_factory=sqlite3.Row
            dst.execute('DELETE FROM version_rules')
            for table in ('users',*KNOWLEDGE):
                rows=src.execute('SELECT * FROM '+table).fetchall()
                if rows:
                    columns=rows[0].keys();dst.executemany('INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[tuple(r) for r in rows])
            user=dst.execute("SELECT id FROM users WHERE username='AQ20260001'").fetchone()
            if not user:raise ValueError('未找到王建国账号，初始化已停止')
            uid=user['id'];stamp=db.now();today=db.today()
            specs=[('3#楼东侧基坑临边防护缺失，未设防护栏杆','木工班组','3#楼东侧基坑','heavy',3),('2#楼3层临时用电私拉乱接，未用配电箱','电工班组','2#楼3层','heavy',2),('外脚手架连墙件设置待现场检查','架子工班组','3#楼外脚手架','heavy',-1),('主通道材料堆放影响通行，待现场确认','杂工班组','主通道','light',None)]
            reply='【演示模拟】木工班组已完成3#楼东侧基坑临边防护整改，补设防护栏杆及挡脚板，现申请安全员复查。'
            for i,(title,team,location,track,days) in enumerate(specs,1):
                hid=dst.execute('INSERT INTO hazards(code,title,category,location,description,track,level,status,source,responsible_team,responsible_person,deadline,created_by,created_at,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('DEMO-'+today.strftime('%Y%m%d')+f'-{i:04d}',title,'现场隐患',location,'【演示模拟】初始化种子，不代表实际现场事实。'+title,track,'一般隐患' if track=='heavy' else '轻微违章','待整改' if track=='heavy' else '待确认','manual',team,team+'负责人（演示角色）',str(today+db.timedelta(days=days)) if days is not None else None,uid,stamp,stamp if track=='heavy' else None)).lastrowid
                if i==1:dst.execute('INSERT INTO hazard_demo_cases VALUES(?,?,?,?,?)',(hid,reply,team,uid,stamp))
                db.event(dst,hid,'prepare_demo_case',uid,{'is_simulated':True,'note':'答辩初始种子；尚未启动办理、签发、登记反馈或现场复查'})
            for i,(camera,category,location) in enumerate([('CAM-03','未戴安全帽','3#楼二层作业面'),('CAM-02','未穿反光衣','主通道')],1):
                dst.execute('INSERT INTO monitor_snapshots(camera_id,captured_at,category,confidence,location,status,note,data_mode,dedup_key) VALUES(?,?,?,?,?,?,?,?,?)',(camera,stamp,category,None,location,'pending','【演示模拟】初始化待确认线索；没有模型置信度或真实抓拍图片，不代表实际现场事实。','demo','demo-init-'+generation+'-'+str(i)))
            dst.execute('INSERT INTO monitor_stats_daily VALUES(?,?,?,?,?,?,?)',(str(today),87,1,1,'暂无真实检测数据','演示数据','demo'))
            dst.execute('INSERT INTO runtime_meta VALUES(?,?)',('demo_generation',generation))
            db.audit(dst,'system','reset_demo','demo',generation,{'backup':str(backup.relative_to(ROOT)),'source_preserved':True})
            assert not dst.execute('PRAGMA foreign_key_check').fetchall()
        with closing(ro(backup/'database.db')) as src,closing(ro(output)) as dst:
            preserved={table:table_digest(src,table)==table_digest(dst,table) for table in ('users',*KNOWLEDGE)}
            assert all(preserved.values())
        report={'generation':generation,'backup':str(backup),'source_database':str(source),'demo_database':str(output),'original_data_deleted':False,'old_business_counts_excluded_from_demo':counts,'business_files_backed_up':copied,'missing_original_files':missing,'preserved_tables':preserved,'clean_demo':{'hazards':4,'documents':0,'feedbacks':0,'sessions':0,'long_term_memories':0,'pending_demo_clues':2},'original_materials_and_index_untouched':True}
        (backup/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        newconfig=config.with_suffix('.building.json');newconfig.write_text(json.dumps({'environment':'demo','database':str(output.relative_to(ROOT)),'generation':generation},ensure_ascii=False),encoding='utf-8');newconfig.replace(config)
        return report
    finally:
        if previous is None:os.environ.pop('APP_DB',None)
        else:os.environ['APP_DB']=previous

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--environment',required=True,choices=['demo']);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if args.execute:
        import socket
        with socket.socket() as s:
            s.settimeout(.5)
            if s.connect_ex(('127.0.0.1',8010))==0:raise ValueError('请先停止 8010 本地服务再初始化，避免初始化期间继续写入')
    report=prepare(args.environment,args.execute)
    if args.execute:(ROOT/'artifacts/demo-initialization.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='business_files_backed_up'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
