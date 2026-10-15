from __future__ import annotations
import uuid
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from backend.app import db
from backend.app.security import current_user,require_operator

router=APIRouter(prefix='/api/hazards')
def decorated(h):return {**h,'overdue':db.overdue(h),'overdue_days':max(0,(db.today()-__import__('datetime').date.fromisoformat(h['deadline'][:10])).days) if h.get('deadline') and db.overdue(h) else 0}

def get_hazard(hid):
    h=db.one('SELECT * FROM hazards WHERE id=?',(hid,))
    if not h:raise HTTPException(404,'隐患不存在')
    return decorated(h)

@router.get('')
def list_hazards(filter:str='all',user=Depends(current_user)):
    all_rows=[decorated(h) for h in db.rows('SELECT * FROM hazards ORDER BY id DESC')]
    selected=[h for h in all_rows if filter=='all' or h['track']==filter or filter in {'over','overdue'} and h['overdue']]
    return {'code':0,'data':{'items':selected,'counts':{'all':len(all_rows),'light':sum(h['track']=='light' for h in all_rows),'heavy':sum(h['track']=='heavy' for h in all_rows),'over':sum(h['overdue'] for h in all_rows)}},'message':'ok'}

class HazardInput(BaseModel):
    title:str=Field(min_length=2,max_length=300)
    category:str='现场隐患'
    location:str=''
    description:str=''
    track:str='heavy'
    source:str='manual'
    responsible_team:str=''
    responsible_person:str=''
    deadline:str|None=None

@router.post('')
def create_hazard(body:HazardInput,user=Depends(current_user)):
    require_operator(user)
    if body.track not in {'light','heavy'}:raise ValueError('请选择轻轨或重轨')
    if body.source!='manual':raise ValueError('监控隐患必须从抓拍记录人工确认，不能绕过确认入口')
    if body.deadline:
        __import__('datetime').date.fromisoformat(body.deadline)
    with db.connect() as c:
        cur=c.execute('INSERT INTO hazards(code,title,category,location,description,track,level,status,source,responsible_team,responsible_person,deadline,created_by,created_at,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
          ('HZ-'+db.today().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:8].upper(),body.title,body.category,body.location,body.description or body.title,body.track,'一般隐患' if body.track=='heavy' else '轻微违章','待整改' if body.track=='heavy' else '待确认','manual',body.responsible_team,body.responsible_person,body.deadline,user['id'],db.now(),db.now() if body.track=='heavy' else None))
        hid=cur.lastrowid;db.event(c,hid,'register',user['id'],body.model_dump())
    return {'code':0,'data':get_hazard(hid),'message':'ok'}

@router.get('/{hid:int}')
def detail(hid:int,user=Depends(current_user)):
    h=get_hazard(hid)
    h['events']=db.rows('SELECT * FROM hazard_events WHERE hazard_id=? ORDER BY id',(hid,))
    h['documents']=db.rows('SELECT id,doc_no,title,status,issued_at FROM documents WHERE hazard_id=? ORDER BY id DESC',(hid,))
    h['attachments']=db.rows('SELECT id,kind,original_name FROM attachments WHERE hazard_id=?',(hid,))
    return {'code':0,'data':h,'message':'ok'}

class ActionInput(BaseModel):
    action:str
    note:str=''
    version:int|None=None

@router.post('/{hid:int}/actions')
def act(hid:int,body:ActionInput,user=Depends(current_user)):
    if body.action!='urge':require_operator(user)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM hazards WHERE id=?',(hid,)).fetchone()
        if not row:raise HTTPException(404,'隐患不存在')
        h=dict(row)
        if body.version is not None and body.version!=h['version']:raise HTTPException(409,'记录已更新，请刷新后操作')
        status=db.next_status(h['track'],h['status'],body.action,body.note)
        c.execute('UPDATE hazards SET status=?,version=version+1,rectify_note=CASE WHEN ?=\'submit_rectify\' THEN ? ELSE rectify_note END,review_note=CASE WHEN ? IN (\'review_close\',\'review_return\') THEN ? ELSE review_note END,confirmed_at=CASE WHEN ?=\'confirm\' THEN ? ELSE confirmed_at END,closed_at=CASE WHEN ? IN (\'已闭环\',\'已销项\') THEN ? ELSE closed_at END WHERE id=?',
                  (status,body.action,body.note,body.action,body.note,body.action,db.now(),status,db.now(),hid))
        db.event(c,hid,body.action,user['id'],{'before':h['status'],'after':status,'note':body.note,'delivery':'仅记录催办，未对接短信' if body.action=='urge' else None})
    return {'code':0,'data':get_hazard(hid),'message':'ok'}
