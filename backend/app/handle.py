from __future__ import annotations
import json
import os
import uuid
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from backend.app import db
from backend.app.hazards import get_hazard
from backend.app.security import current_user,require_operator
from backend.agents.handling import pool,execute,rule_check,step
from backend.app.documents import get_document
router=APIRouter()

class TaskInput(BaseModel):
    hazard_id:int
    note:str=Field(default='',max_length=2000)
    responsible_person:str|None=None
    responsible_team:str|None=None
    deadline:str|None=None
    test_case:str|None=None

@router.post('/api/handle/tasks')
def create(body:TaskInput,user=Depends(current_user)):
    require_operator(user);h=get_hazard(body.hazard_id)
    if h['track']!='heavy':raise ValueError('轻轨事项请即查即改；限期整改文书只办理重轨隐患')
    if h['status'] in db.TERMINAL:raise ValueError('已闭环隐患不能重复办理')
    if body.test_case and os.getenv('ALLOW_TEST_DRAFTS')!='1':raise HTTPException(403,'测试草稿仅在隔离验收环境启用')
    facts={**h,'supplement_note':body.note}
    for key in ['responsible_person','responsible_team','deadline']:
        val=getattr(body,key)
        if val is not None:facts[key]=val
    if facts.get('deadline'):__import__('datetime').date.fromisoformat(facts['deadline'])
    tid=uuid.uuid4().hex
    with db.connect() as c:
        running=c.execute("SELECT id FROM handle_tasks WHERE hazard_id=? AND status IN ('queued','drafting','rule_check','reviewing','rework')",(h['id'],)).fetchone()
        if running:raise HTTPException(409,'该隐患已有正在办理的任务，请等待现有任务')
        c.execute('INSERT INTO handle_tasks(id,hazard_id,status,steps_json,note,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(tid,h['id'],'queued','[]',body.note,user['id'],db.now()))
        c.execute('INSERT INTO task_inputs VALUES(?,?,?)',(tid,db.dumps(facts),body.test_case))
        db.event(c,h['id'],'create_handle_task',user['id'],{'task_id':tid})
    pool.submit(execute,tid)
    return {'code':0,'data':{'task_id':tid},'message':'已受理'}

@router.get('/api/handle/tasks/{tid}')
def task(tid:str,user=Depends(current_user)):
    t=db.one('SELECT * FROM handle_tasks WHERE id=?',(tid,))
    if not t:raise HTTPException(404,'办理任务不存在')
    t['steps']=json.loads(t.pop('steps_json'));t['document']=get_document(t['document_id']) if t['document_id'] else None
    return {'code':0,'data':t,'message':'ok'}

@router.get('/api/handle/tasks')
def list_tasks(hazard_id:int,user=Depends(current_user)):
    return {'code':0,'data':db.rows('SELECT id,status,document_id,created_at FROM handle_tasks WHERE hazard_id=? ORDER BY rowid DESC',(hazard_id,)),'message':'ok'}

class IssueInput(BaseModel):confirmed:bool=False
@router.post('/api/documents/{did:int}/issue')
def issue_document(did:int,body:IssueInput,user=Depends(current_user)):
    require_operator(user)
    if not body.confirmed:raise ValueError('请明确确认人工签发')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not row:raise HTTPException(404,'文书不存在')
        doc=dict(row)
        if doc['status']=='issued':return {'code':0,'data':{'id':did,'doc_no':doc['doc_no'],'hazard_id':doc['hazard_id']},'message':'已签发，无重复操作'}
        if doc['status']!='pending_human' or doc['type']!='rectification_notice':raise ValueError('草稿仍有阻断或属于资料起草，不可签发')
        task=c.execute('SELECT * FROM handle_tasks WHERE document_id=? ORDER BY created_at DESC LIMIT 1',(did,)).fetchone()
        inp=c.execute('SELECT * FROM task_inputs WHERE task_id=?',(task['id'],)).fetchone()
        facts=json.loads(inp['facts_json']);draft=json.loads(doc['content_json'])
        hazard=dict(c.execute('SELECT * FROM hazards WHERE id=?',(doc['hazard_id'],)).fetchone())
        if hazard['version']!=facts['version']:raise HTTPException(409,'隐患已发生变化，请重新办理复核')
        problems=rule_check(draft,facts,draft.get('evidence',[]))
        if any(p['block'] for p in problems):raise ValueError('签发前校验发现引用或事实变化，请重新办理')
        no=('DEMO-' if inp['test_case'] else '')+f'AQ-{db.today():%Y%m%d}-{did:06d}'
        stamp=db.now()
        c.execute('UPDATE documents SET status=?,doc_no=?,issued_by=?,issued_at=? WHERE id=?',('issued',no,user['id'],stamp,did))
        status='整改中' if hazard['status']=='待整改' else hazard['status']
        c.execute('UPDATE hazards SET track=?,status=?,responsible_team=?,responsible_person=?,deadline=?,version=version+1 WHERE id=?',('heavy',status,facts.get('responsible_team'),facts.get('responsible_person'),facts.get('deadline'),hazard['id']))
        for e in draft.get('evidence',[]):
            c.execute('INSERT OR IGNORE INTO document_citations VALUES(?,?,?)',(did,e['chunk_id'],db.dumps(e)))
        c.execute('UPDATE kb_sources SET cite_count=(SELECT count(DISTINCT dc.document_id) FROM document_citations dc JOIN kb_chunks k ON k.chunk_id=dc.chunk_id WHERE k.source_id=kb_sources.id)')
        c.execute('UPDATE handle_tasks SET status=? WHERE id=?',('issued',task['id']))
        db.event(c,hazard['id'],'issue_document',user['id'],{'document_id':did,'doc_no':no,'source_preserved':hazard['source']})
        db.audit(c,user['id'],'issue_document','document',did,{'doc_no':no})
    return {'code':0,'data':{'id':did,'doc_no':no,'hazard_id':doc['hazard_id']},'message':'已由人工确认签发并关联原隐患'}
