from __future__ import annotations
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from backend.app import db
from backend.app.security import current_user
from backend.app.llm import ask_json
from backend.rag.knowledge import search,cite_allowed,region_applies,canonical
from backend.app.memory import context as memory_context,remember
from backend.rag.query import resolve_query,memory_intent
from backend.app.answers import build_answer,answer_intro,evidence_label
router=APIRouter()
pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='safety-chat')

def session_for(sid,user):
    s=db.one('SELECT * FROM chat_sessions WHERE id=? AND user_id=?',(sid,user['id']))
    if not s:raise HTTPException(404,'会话不存在')
    return s

def new_session(user,title='新对话'):
    sid=uuid.uuid4().hex
    db.write('INSERT INTO chat_sessions(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(sid,user['id'],title[:40],db.now(),db.now()))
    return sid

class SessionInput(BaseModel):title:str='新对话'
@router.get('/api/sessions')
def sessions(user=Depends(current_user)):return {'code':0,'data':db.rows('SELECT * FROM chat_sessions WHERE user_id=? ORDER BY updated_at DESC',(user['id'],)),'message':'ok'}
@router.post('/api/sessions')
def create_session(body:SessionInput,user=Depends(current_user)):return {'code':0,'data':{'id':new_session(user,body.title)},'message':'ok'}
@router.get('/api/sessions/{sid}/messages')
def messages(sid:str,user=Depends(current_user)):
    session_for(sid,user)
    return {'code':0,'data':db.rows('SELECT * FROM chat_messages WHERE session_id=? ORDER BY id',(sid,)),'message':'ok'}
@router.delete('/api/sessions/{sid}')
def delete_session(sid:str,user=Depends(current_user)):
    session_for(sid,user)
    with db.connect() as c:
        if c.execute("SELECT 1 FROM chat_runs WHERE session_id=? AND status='running'",(sid,)).fetchone():raise HTTPException(409,'会话仍在生成，请完成后再删除')
        c.execute('DELETE FROM chat_sessions WHERE id=?',(sid,));db.audit(c,user['id'],'delete_session','session',sid)
    return {'code':0,'data':None,'message':'ok'}

def grounded_answer(question,evidence,history=None,profile=None):
    return build_answer(question,evidence,history,ask_json,profile)

def references_current(references,regulatory_only):
    for ref in references:
        current=db.one("SELECT k.source_id,k.text,k.section,s.*,coalesce(cs.active,1) chunk_active,coalesce(cs.legal_status,'现行') chunk_legal_status FROM kb_chunks k JOIN kb_sources s ON s.id=k.source_id LEFT JOIN chunk_states cs ON cs.chunk_id=k.chunk_id WHERE k.chunk_id=?",(ref['chunk_id'],))
        if not current or any(current[k]!=ref[k] for k in ('source_id','text','section','name')) or canonical(current['doc_no'])!=canonical(ref['doc_no']):return False
        if not current['chunk_active'] or current['chunk_legal_status']!='现行' or current['status']!='现行' or current['legal_status']!='现行' or not current['parsed'] or not region_applies(current):return False
        if current['effective_date'] and current['effective_date']>str(db.today()):return False
        if regulatory_only and not cite_allowed(current):return False
    return True

def run_chat(run_id,question,sid,source_id,message_id=None):
    try:
        owner=db.one('SELECT user_id FROM chat_sessions WHERE id=?',(sid,))['user_id']
        memory=memory_context(owner,sid,message_id)
        history=memory['recent_messages']
        prior=db.rows('SELECT id,role,content FROM chat_messages WHERE session_id=? AND role=? '+('AND id<? ' if message_id is not None else '')+'ORDER BY id',(sid,'user',message_id) if message_id is not None else (sid,'user'))
        profile=resolve_query(question,prior)
        memory_command=memory_intent(question)
        selected_source=db.one('SELECT category FROM kb_sources WHERE id=?',(source_id,)) if source_id is not None else None
        regulatory_only=not selected_source or selected_source['category']=='法规依据'
        evidence=[] if memory_command or profile['needs_clarification'] else search(question,source_id=source_id,profile=profile,regulatory_only=regulatory_only,applicable_only=True)
        if evidence:
            db.write('UPDATE chat_runs SET answer=? WHERE id=?',(answer_intro(profile),run_id))
        status='正在处理当前身份的记忆' if memory_command else '需要澄清当前讨论对象' if profile['needs_clarification'] else '已检索到有效原文，正在组织回答' if evidence else '没有检索到相关有效证据，未调用模型'
        db.write('UPDATE chat_runs SET status_message=? WHERE id=?',(status,run_id))
        if memory_command=='remember':
            mid=remember(owner,question,sid,history[-1]['id'] if history else None)
            answer=('已按当前身份保存这条长期记忆：'+question+'。可在“小安的记忆与背景”查看或删除。') if mid else '这条信息涉及密码或密钥，未加入长期记忆。'
            refs=[];meta={'mode':'memory','reason':'显式记忆操作，不需要调用大模型'}
        elif memory_command=='recall':
            answer='当前身份的长期记忆（用户提供，未经现场独立核验）：\n'+'\n'.join(m['value'] for m in memory['long_term_user_provided']) if memory['long_term_user_provided'] else '当前身份没有已确认的长期记忆。你可以用“记住……”明确指定。'
            refs=[];meta={'mode':'memory'}
        elif profile['needs_clarification']:
            answer=profile['reason'];refs=[];meta={'mode':'clarification'}
        else:answer,refs,meta=grounded_answer(question,evidence,memory,profile)
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM chat_sessions WHERE id=?',(sid,)).fetchone():return
            if refs and not references_current(refs,regulatory_only):
                fresh=search(question,source_id=source_id,profile=profile,regulatory_only=regulatory_only,applicable_only=True)
                answer,refs,meta=build_answer(question,fresh,memory,lambda *args,**kwargs:(None,{'mode':'offline','reason':'整理期间引用效力或正文发生变化，已按当前原文重新核对'}),profile)
                if not answer.startswith(answer_intro(profile)):answer=answer_intro(profile)+'\n\n'+answer
            if meta['mode']=='offline':answer+='\n\n当前为离线兜底结果（本地证据整理）：'+meta.get('reason','模型未参与本次整理')+'；以上仍依据检索原文生成。'
            elif meta['mode']=='online':answer+=f"\n\n大模型辅助选择证据 · {meta['model']}；正文检查项由可追溯原文转换。"
            c.execute('INSERT INTO chat_messages(session_id,role,content,sources,created_at) VALUES(?,?,?,?,?)',(sid,'assistant',answer,db.dumps(refs),db.now()))
            c.execute('UPDATE chat_sessions SET updated_at=? WHERE id=?',(db.now(),sid))
            c.execute('UPDATE chat_runs SET status=?,answer=?,references_json=?,mode=?,status_message=? WHERE id=?',('done',answer,db.dumps(refs),meta['mode'],'回答已保存',run_id))
    except Exception as e:
        db.write('UPDATE chat_runs SET status=?,error=? WHERE id=?',('error','生成未完成：'+type(e).__name__,run_id))

class ChatInput(BaseModel):
    message:str=Field(min_length=1,max_length=4000)
    session_id:str|None=None
    source_id:int|None=None

@router.post('/api/chat/stream')
def chat(body:ChatInput,user=Depends(current_user)):
    sid=body.session_id or new_session(user,body.message)
    session_for(sid,user)
    rid=uuid.uuid4().hex
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM chat_runs WHERE session_id=? AND status='running'",(sid,)).fetchone():raise HTTPException(409,'当前会话仍在生成，请完成后继续提问')
        message_id=c.execute('INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(sid,'user',body.message,db.now())).lastrowid
        c.execute('INSERT INTO chat_runs(id,session_id,user_id,status,status_message,created_at) VALUES(?,?,?,?,?,?)',(rid,sid,user['id'],'running','正在检索知识库原文',db.now()))
        db.audit(c,user['id'],'ask','session',sid,{'run_id':rid})
    pool.submit(run_chat,rid,body.message,sid,body.source_id,message_id)
    def stream():
        yield 'data: '+db.dumps({'type':'session','session_id':sid,'run_id':rid})+'\n\n'
        status='';pos=0
        while True:
            r=db.one('SELECT * FROM chat_runs WHERE id=?',(rid,))
            if not r:return
            if r['status_message']!=status:
                status=r['status_message'];yield 'data: '+db.dumps({'type':'status','message':status})+'\n\n'
            while pos<len(r['answer']):
                delta=r['answer'][pos:pos+24];pos+=len(delta)
                yield 'data: '+db.dumps({'type':'token','content':delta})+'\n\n'
            if r['status']=='done':
                yield 'data: '+db.dumps({'type':'done','references':json.loads(r['references_json']),'mode':r['mode']})+'\n\n';return
            if r['status']=='error':yield 'data: '+db.dumps({'type':'error','message':r['error']})+'\n\n';return
            time.sleep(.08)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@router.get('/api/task/{rid}/status')
def task_status(rid:str,user=Depends(current_user)):
    r=db.one('SELECT * FROM chat_runs WHERE id=? AND user_id=?',(rid,user['id']))
    if not r:raise HTTPException(404,'生成任务不存在')
    return {'code':0,'data':r,'message':'ok'}

class DraftInput(BaseModel):
    kind:str
    context:str=Field(default='',max_length=4000)
    session_id:str|None=None

@router.post('/api/draft')
def draft(body:DraftInput,user=Depends(current_user)):
    titles={'jsa':'班前安全分析 JSA','jiaodi':'安全技术交底','log':'安全员工作日志'}
    if body.kind not in titles:raise ValueError('不支持的起草类型')
    topics=[t for t in ['楼梯口','临边','脚手架','模板','临时用电','接地','安全帽','有限空间','起重机械'] if t in body.context]
    evidence=search(' '.join(topics)+' 防护' if topics else body.context,for_document=True,limit=3)
    # The model selects grounded passages; facts and operational fields stay source-bound.
    answer,refs,meta=grounded_answer(body.context,evidence)
    if body.kind=='log':
        hs=db.rows('SELECT title,status FROM hazards WHERE substr(created_at,1,10)=?',(str(db.today()),))
        pending=db.one("SELECT count(*) n FROM monitor_snapshots WHERE status='pending'")['n']
        content='日期：'+str(db.today())+'\n今日登记事项：\n'+'\n'.join(h['title']+' · '+h['status'] for h in hs)+f'\n监控尚有 {pending} 条线索待现场确认，不能记为已纠正。\n实际巡查经过、教育内容及明日安排：待安全员填写。'
    else:content='任务说明：'+body.context+'\n\n一、现场信息\n作业日期、班组及人员名单、现场条件：待人工填写。\n\n二、班前检查与交底\n核对作业任务和专项方案；按下列原文逐项检查；未满足要求的项目由安全员确认处置后再开展作业。\n\n三、相关原文要求\n'+answer+'\n\n四、作业过程与复核记录\n实际作业步骤、现场风险、具体责任分工及异常处置安排：待安全员结合本次作业补充并签字；整改和复查情况据实记录。'
    payload={'body':content,'evidence':refs,'mode':meta['mode'],'model':meta.get('model'),'kind':body.kind}
    sid=body.session_id or new_session(user,body.context)
    session_for(sid,user)
    with db.connect() as c:
        did=c.execute('INSERT INTO documents(type,title,content_json,status,created_by,created_at) VALUES(?,?,?,?,?,?)',(body.kind,titles[body.kind],db.dumps(payload),'draft',user['id'],db.now())).lastrowid
        db.audit(c,user['id'],'create_draft','document',did,{'kind':body.kind,'status':'draft'})
        c.execute('INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(sid,'user',body.context,db.now()))
        c.execute('INSERT INTO chat_messages(session_id,role,content,sources,created_at) VALUES(?,?,?,?,?)',(sid,'assistant','草稿待审核 · '+titles[body.kind]+'\n'+content,db.dumps(refs),db.now()))
        c.execute('UPDATE chat_sessions SET updated_at=? WHERE id=?',(db.now(),sid))
    return {'code':0,'data':{'id':did,'session_id':sid,'title':titles[body.kind],'status':'draft','content':payload,'mode':meta['mode']},'message':'草稿待审核'}
