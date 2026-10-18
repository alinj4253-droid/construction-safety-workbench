from __future__ import annotations
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from backend.app import db
from backend.app.security import current_user,require_operator
from backend.app.dashboard import monitor_summary,sync_monitor_stats
from backend.vision.detector import CAMERAS,process
router=APIRouter(prefix='/api/monitor');pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='safety-vision')

@router.get('/overview')
def overview(user=Depends(current_user)):
    return {'code':0,'data':{**monitor_summary(),'cameras':[{**c,'url':'/videos/'+c['file'],'available':(db.ROOT/'videos'/c['file']).exists()} for c in CAMERAS],'model_metrics':{'mAP50':.761,'precision':.827,'recall':.698,'scope':'历史训练验证集指标，不等于本次工地现场准确率'},'classes':['佩戴安全帽','未佩戴安全帽'],'vest_mode':'演示数据（模型待训练）'},'message':'ok'}

@router.get('/snapshots')
def snapshots(status:str='pending',user=Depends(current_user)):
    if status not in {'all','pending','confirmed','dismissed'}:raise ValueError('线索状态不合法')
    items=db.rows('SELECT * FROM monitor_snapshots '+('' if status=='all' else 'WHERE status=? ')+'ORDER BY captured_at DESC,id DESC',() if status=='all' else (status,))
    return {'code':0,'data':items,'message':'ok'}

class ConfirmInput(BaseModel):note:str=''
@router.post('/snapshots/{sid:int}/confirm')
def confirm(sid:int,body:ConfirmInput,user=Depends(current_user)):
    require_operator(user)
    if not body.note.strip():raise ValueError('请填写现场核实记录，不能仅凭模型抓拍入账')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');s=c.execute('SELECT * FROM monitor_snapshots WHERE id=?',(sid,)).fetchone()
        if not s:raise HTTPException(404,'抓拍不存在')
        s=dict(s)
        if s['status']=='confirmed':return {'code':0,'data':{'hazard_id':s['hazard_id']},'message':'已确认，无重复入账'}
        if s['status']=='dismissed':raise ValueError('已驳回线索不能确认，请保留原审计记录')
        hid=c.execute('INSERT INTO hazards(code,title,category,location,description,track,level,status,source,responsible_team,created_by,created_at,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      ('HZ-'+db.today().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:8].upper(),s['category']+' · '+s['location'],'个人防护',s['location'],body.note,'light','轻微违章','整改中','ai_monitor','待安全员填写',user['id'],db.now(),db.now())).lastrowid
        c.execute('UPDATE monitor_snapshots SET status=?,hazard_id=? WHERE id=?',('confirmed',hid,sid))
        db.event(c,hid,'confirm_monitor_clue',user['id'],{'snapshot_id':sid,'field_note':body.note,'data_mode':s['data_mode']});db.audit(c,user['id'],'confirm_snapshot','snapshot',sid,{'hazard_id':hid,'note':body.note})
        sync_monitor_stats(c)
    return {'code':0,'data':{'hazard_id':hid},'message':'人工确认后已进入轻轨整改中'}

@router.post('/snapshots/{sid:int}/dismiss')
def dismiss(sid:int,body:ConfirmInput,user=Depends(current_user)):
    require_operator(user)
    if not body.note.strip():raise ValueError('请填写误报或驳回原因')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');s=c.execute('SELECT * FROM monitor_snapshots WHERE id=?',(sid,)).fetchone()
        if not s:raise HTTPException(404,'抓拍不存在')
        if s['status']=='confirmed':raise ValueError('已确认入账的事项请在台账处理，不能删除确认事实')
        c.execute('UPDATE monitor_snapshots SET status=? WHERE id=?',('dismissed',sid));db.audit(c,user['id'],'dismiss_snapshot','snapshot',sid,{'reason':body.note})
        sync_monitor_stats(c)
    return {'code':0,'data':None,'message':'已驳回并留痕，未创建隐患'}

@router.get('/snapshots/{sid:int}/image')
def snapshot_image(sid:int,user=Depends(current_user)):
    s=db.one('SELECT image_path FROM monitor_snapshots WHERE id=?',(sid,))
    if not s or not s['image_path'] or not (db.ROOT/s['image_path']).is_file():raise HTTPException(404,'抓拍图片不存在或未生成')
    return FileResponse(db.ROOT/s['image_path'])

class DetectInput(BaseModel):
    camera_id:str='CAM-03'
    max_frames:int=Field(default=8,ge=1,le=60)
    confidence:float=Field(default=.5,ge=.25,le=.95)

class BatchInput(BaseModel):
    max_frames:int=Field(default=8,ge=1,le=60)
    confidence:float=Field(default=.5,ge=.25,le=.95)

@router.post('/detect-all')
def detect_all(body:BatchInput,user=Depends(current_user)):
    require_operator(user)
    missing=[c['id'] for c in CAMERAS if not (db.ROOT/'videos'/c['file']).is_file()]
    if missing:raise HTTPException(404,'缺少录像：'+', '.join(missing))
    jobs=[{'id':uuid.uuid4().hex,'camera_id':camera['id']} for camera in CAMERAS]
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT id FROM monitor_runs WHERE status IN ('queued','running')").fetchone():raise HTTPException(409,'已有检测任务正在执行，请等待本次完成')
        for job in jobs:
            c.execute('INSERT INTO monitor_runs(id,camera_id,status,created_by,created_at) VALUES(?,?,?,?,?)',(job['id'],job['camera_id'],'queued',user['id'],db.now()))
            db.audit(c,user['id'],'start_detection','monitor_run',job['id'],{'camera_id':job['camera_id'],'max_frames':body.max_frames,'confidence':body.confidence,'batch':True})
    for job in jobs:pool.submit(process,job['id'],job['camera_id'],body.max_frames,body.confidence)
    return {'code':0,'data':{'runs':jobs},'message':'四路录像已排队，单任务串行检测'}

@router.post('/detect')
def detect(body:DetectInput,user=Depends(current_user)):
    require_operator(user)
    if body.camera_id not in {c['id'] for c in CAMERAS}:raise ValueError('摄像头不存在')
    camera=next(c for c in CAMERAS if c['id']==body.camera_id)
    if not (db.ROOT/'videos'/camera['file']).is_file():raise HTTPException(404,'本地录像不存在，无法进行真实检测')
    rid=uuid.uuid4().hex
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT id FROM monitor_runs WHERE status IN ('queued','running')").fetchone():raise HTTPException(409,'已有检测任务正在执行，请等待本次完成')
        c.execute('INSERT INTO monitor_runs(id,camera_id,status,created_by,created_at) VALUES(?,?,?,?,?)',(rid,body.camera_id,'queued',user['id'],db.now()));db.audit(c,user['id'],'start_detection','monitor_run',rid,body.model_dump())
    pool.submit(process,rid,body.camera_id,body.max_frames,body.confidence)
    return {'code':0,'data':{'id':rid},'message':'真实YOLO检测已受理'}

@router.get('/latest')
def latest(user=Depends(current_user)):
    items=[]
    for camera in CAMERAS:
        r=db.one('SELECT * FROM monitor_runs WHERE camera_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(camera['id'],))
        completed=db.one("SELECT * FROM monitor_runs WHERE camera_id=? AND status='done' ORDER BY created_at DESC,rowid DESC LIMIT 1",(camera['id'],))
        for item in (r,completed):
            if item:item['result']=json.loads(item.pop('result_json') or '{}')
        items.append({'camera_id':camera['id'],'latest':r,'completed':completed})
    return {'code':0,'data':items,'message':'ok'}

@router.get('/runs/{rid}')
def run(rid:str,user=Depends(current_user)):
    r=db.one('SELECT * FROM monitor_runs WHERE id=?',(rid,))
    if not r:raise HTTPException(404,'检测任务不存在')
    r['result']=json.loads(r['result_json'] or '{}');return {'code':0,'data':r,'message':'ok'}

@router.get('/frames/{fid:int}')
def frame(fid:int,user=Depends(current_user)):
    f=db.one('SELECT * FROM monitor_frames WHERE id=?',(fid,))
    if not f or not (db.ROOT/f['image_path']).is_file():raise HTTPException(404,'检测帧不存在或图片缺失')
    return FileResponse(db.ROOT/f['image_path'])
