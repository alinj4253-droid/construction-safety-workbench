"""Reviewed sources and explicitly registered version relations; no simulated web crawler."""
from __future__ import annotations
import hashlib
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from backend.app import db
from backend.app.security import current_user
from backend.rag.knowledge import Knowledge, canonical, cite_allowed, extract, put_chunks

router=APIRouter(prefix='/api/kb')
CATEGORIES={'法规依据','项目资料','案例参考'}
STATES={'现行','待核验','历史版本'}

def source(sid,c=None):
    s=dict(c.execute('SELECT * FROM kb_sources WHERE id=?',(sid,)).fetchone() or {}) if c else db.one('SELECT * FROM kb_sources WHERE id=?',(sid,))
    if not s:raise HTTPException(404,'资料不存在')
    return s

def rule_for(no,c):
    return next((dict(r) for r in c.execute('SELECT * FROM version_rules') if canonical(r['old_no'])==canonical(no) and r['effective_date']<=str(db.today())),None)

def change(c,sid,action,before,after,user):
    cid=c.execute('INSERT INTO kb_changes(source_id,action,before_json,after_json,actor,created_at) VALUES(?,?,?,?,?,?)',(sid,action,db.dumps(before),db.dumps(after),str(user['id']),db.now())).lastrowid
    db.audit(c,user['id'],action,'kb_source',sid,{'change_id':cid,'before':before,'after':after})
    return cid

def state(s):return {k:s.get(k) for k in ('status','legal_status','verified_by','verified_at')}

@router.get('/sources')
def sources(type:str='',status:str='',keyword:str='',sort:str='newest',user=Depends(current_user)):
    if type and type not in CATEGORIES:raise ValueError('资料类型不合法')
    if status and status not in STATES:raise ValueError('资料状态不合法')
    items=db.rows('SELECT s.*,(SELECT count(*) FROM kb_chunks k LEFT JOIN chunk_states cs ON cs.chunk_id=k.chunk_id WHERE k.source_id=s.id AND coalesce(cs.active,1)=1) chunk_count FROM kb_sources s ORDER BY s.id DESC')
    stats={'total':len(items),'parsed':sum(s['parsed']==1 for s in items),'pending':sum(s['status']=='待核验' for s in items)}
    filtered=[s for s in items if (not type or s['category']==type) and (not status or s['status']==status) and (not keyword or canonical(keyword) in canonical(s['name']+' '+s['doc_no']))]
    if sort=='cited':filtered.sort(key=lambda s:(-s['cite_count'],-s['id']))
    return {'code':0,'data':{'items':filtered,'stats':stats},'message':'ok'}

@router.get('/sources/{sid:int}')
def detail(sid:int,chunk:str='',user=Depends(current_user)):
    s=source(sid)
    # Do not truncate the requested clause when the source has more than 100 chunks.
    clauses=db.rows("SELECT k.*,coalesce(cs.active,1) chunk_active,coalesce(cs.legal_status,'现行') chunk_legal_status,cs.note chunk_note FROM kb_chunks k LEFT JOIN chunk_states cs ON cs.chunk_id=k.chunk_id WHERE k.source_id=? "+('AND k.chunk_id=? ' if chunk else '')+'ORDER BY page,k.rowid LIMIT 100',(sid,chunk) if chunk else (sid,))
    s['chunks']=[{**k,'citation_eligible':cite_allowed({**s,**k})} for k in clauses]
    return {'code':0,'data':s,'message':'ok'}

@router.get('/sources/{sid:int}/file')
def file(sid:int,user=Depends(current_user)):
    s=source(sid);p=(db.ROOT/s['file_path']).resolve()
    if not p.is_relative_to(db.ROOT.resolve()) or not p.is_file():raise HTTPException(404,'原文件不存在')
    return FileResponse(p,filename=p.name)

@router.post('/sources')
async def upload(name:str=Form(...),category:str=Form(...),doc_no:str=Form(''),region:str=Form('厦门'),effective_date:str=Form(''),source_url:str=Form(''),file:UploadFile=File(...),user=Depends(current_user)):
    if category not in CATEGORIES:raise ValueError('资料类型不合法')
    if not name.strip() or not region.strip():raise ValueError('请填写名称与适用地域')
    if category=='法规依据' and not doc_no.strip():raise ValueError('法规依据必须填写文号或标准号')
    if effective_date:
        from datetime import date
        date.fromisoformat(effective_date)
    data=await file.read(20*1024*1024+1)
    if not data or len(data)>20*1024*1024:raise ValueError('请选择不超过20MB的文件')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in {'.pdf','.docx','.txt','.md','.html','.htm','.doc'}:raise ValueError('支持 PDF、DOCX、TXT、Markdown、HTML；旧DOC登记后仍待人工转换')
    sha=hashlib.sha256(data).hexdigest()
    if db.one('SELECT id FROM kb_sources WHERE sha256=?',(sha,)):raise HTTPException(409,'相同文件已经登记，请查看现有资料')
    folder=db.ROOT/'backend/data/uploads';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(uuid.uuid4().hex+suffix);path.write_bytes(data)
    try:
        pages=extract(path)
        if sum(len(t) for _,t in pages)<80:raise ValueError('正文不足80字，无法建立可靠检索片段')
        parsed=1;note='正文已抽取，待人工核对原文、元数据和效力'
    except Exception as exc:pages=[];parsed=0;note='未完成解析：'+str(exc)[:160]
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT id FROM kb_sources WHERE sha256=?',(sha,)).fetchone():
            path.unlink(missing_ok=True);raise HTTPException(409,'相同文件已经登记')
        sid=c.execute('INSERT INTO kb_sources(name,category,doc_no,effective_date,region,status,legal_status,source_url,file_path,sha256,created_at,parsed,parse_note,content_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(name.strip(),category,doc_no.strip(),effective_date,region.strip(),'待核验','待核验',source_url.strip(),str(path.relative_to(db.ROOT)),sha,db.now(),parsed,note,'全文/正文')).lastrowid
        if parsed:put_chunks(c,source(sid,c),pages)
        change(c,sid,'upload_source',{},state(source(sid,c)),user)
    return {'code':0,'data':source(sid),'message':'文件已登记，人工确认前不会参与检索或引用'}

class Confirm(BaseModel):
    confirmed:bool=False
    note:str=Field(default='',max_length=2000)

@router.post('/sources/{sid:int}/confirm')
def confirm(sid:int,body:Confirm,user=Depends(current_user)):
    if not body.confirmed or not body.note.strip():raise ValueError('请核对原文、地域、版本效力并填写审核记录')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');s=source(sid,c)
        if not s['parsed']:raise ValueError('正文未成功解析，请转换原文后重新上传，不能只确认元数据')
        if rule_for(s['doc_no'],c) or s['legal_status']=='已废止':raise ValueError('该版本已被替代或废止，禁止确认成现行依据')
        if s['effective_date'] and s['effective_date']>str(db.today()):raise ValueError('尚未到生效日期，暂不能确认为现行')
        if s['status']=='现行':return {'code':0,'data':s,'message':'已经生效，无重复变更'}
        after={'status':'现行','legal_status':'现行','verified_by':f"{user['id']} {user['display_name']}：{body.note}",'verified_at':db.now()}
        c.execute('UPDATE kb_sources SET status=?,legal_status=?,verified_by=?,verified_at=? WHERE id=?',(*after.values(),sid))
        change(c,sid,'confirm_source',state(s),after,user)
    Knowledge().save()
    return {'code':0,'data':source(sid),'message':'人工核验已生效，检索索引已更新'}

class VersionRule(BaseModel):
    old_no:str=Field(min_length=1,max_length=150)
    new_no:str=Field(min_length=1,max_length=150)
    effective_date:str
    basis_url:str=Field(min_length=5,max_length=2000)

@router.get('/version-rules')
def rules(user=Depends(current_user)):return {'code':0,'data':db.rows('SELECT * FROM version_rules ORDER BY effective_date DESC'),'message':'ok'}

@router.post('/version-rules')
def register_rule(body:VersionRule,user=Depends(current_user)):
    from datetime import date
    date.fromisoformat(body.effective_date)
    if canonical(body.old_no)==canonical(body.new_no):raise ValueError('新旧版本不能相同')
    with db.connect() as c:
        if any(canonical(r['old_no'])==canonical(body.old_no) for r in c.execute('SELECT old_no FROM version_rules')):raise HTTPException(409,'替代关系已登记；修正法律事实需管理员核实后迁移，不能用撤销恢复旧法')
        c.execute('INSERT INTO version_rules VALUES(?,?,?,?)',(body.old_no.strip(),body.new_no.strip(),body.effective_date,body.basis_url.strip()))
        db.audit(c,user['id'],'register_version_rule','version_rule',body.old_no,body.model_dump())
    return {'code':0,'data':body.model_dump(),'message':'已登记替代关系；检查更新可查看影响并执行状态变更'}

@router.post('/check-updates')
def check(user=Depends(current_user)):
    suggestions=[]
    with db.connect() as c:
        for s in c.execute('SELECT * FROM kb_sources'):
            r=rule_for(s['doc_no'],c)
            if r:suggestions.append({'source_id':s['id'],'name':s['name'],'status':s['status'],'legal_status':s['legal_status'],'rule':r,'needs_change':s['status']!='历史版本' or s['legal_status']!='已废止'})
        db.audit(c,user['id'],'check_updates','kb','all',{'suggestions':len(suggestions),'method':'已登记版本关系本地比对，未自动访问外部站点'})
    return {'code':0,'data':{'suggestions':suggestions,'method':'按人工登记的版本替代关系比对；不代表实时联网检索全部法规'},'message':'ok'}

@router.post('/sources/{sid:int}/apply-update')
def apply_update(sid:int,body:Confirm,user=Depends(current_user)):
    if not body.confirmed or not body.note.strip():raise ValueError('需要人工确认版本变更并填写依据')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');s=source(sid,c);r=rule_for(s['doc_no'],c)
        if not r:raise ValueError('没有已生效的替代关系，请先登记并核实')
        if s['status']=='历史版本' and s['legal_status']=='已废止':return {'code':0,'data':s,'message':'已是历史版本'}
        after={**state(s),'status':'历史版本','legal_status':'已废止'}
        c.execute("UPDATE kb_sources SET status='历史版本',legal_status='已废止' WHERE id=?",(sid,))
        change(c,sid,'apply_version_update',state(s),after,user)
    Knowledge().save()
    return {'code':0,'data':source(sid),'message':'旧版停止新引用，历史文书引用快照保留'}

@router.get('/changelog')
def logs(user=Depends(current_user)):
    return {'code':0,'data':db.rows('SELECT k.*,s.name FROM kb_changes k JOIN kb_sources s ON s.id=k.source_id ORDER BY k.id DESC LIMIT 150'),'message':'ok'}

@router.post('/changelog/{cid:int}/undo')
def undo(cid:int,body:Confirm,user=Depends(current_user)):
    if not body.confirmed or not body.note.strip():raise ValueError('请填写撤销原因并确认')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');log=c.execute('SELECT * FROM kb_changes WHERE id=?',(cid,)).fetchone()
        if not log:raise HTTPException(404,'变更不存在')
        if log['undone']:raise ValueError('该操作已经撤销')
        if log['action'] in {'upload_source','undo_change'}:raise ValueError('上传原文及撤销记录需保留追溯，不能删除')
        if c.execute("SELECT 1 FROM kb_changes WHERE source_id=? AND id>? AND undone=0 AND action<>'undo_change'",(log['source_id'],cid)).fetchone():raise HTTPException(409,'该资料有后续变更，请先处理最新变更')
        s=source(log['source_id'],c);before=json.loads(log['before_json']);restore={**state(s),**before}
        # Undo review state, never undo an independently registered withdrawal fact.
        if rule_for(s['doc_no'],c) or s['legal_status']=='已废止':restore.update(status='历史版本',legal_status='已废止')
        c.execute('UPDATE kb_sources SET status=?,legal_status=?,verified_by=?,verified_at=? WHERE id=?',(restore['status'],restore['legal_status'],restore.get('verified_by'),restore.get('verified_at'),s['id']))
        c.execute('UPDATE kb_changes SET undone=1 WHERE id=?',(cid,));change(c,s['id'],'undo_change',state(s),restore,user)
        db.audit(c,user['id'],'undo_kb_change','kb_change',cid,{'reason':body.note,'legal_status':restore['legal_status']})
    Knowledge().save()
    return {'code':0,'data':source(s['id']),'message':'管理操作已撤销；法定废止事实与已签发引用快照保留'}
