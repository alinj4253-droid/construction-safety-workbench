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
from backend.rag.knowledge import search
from backend.app.memory import context as memory_context,remember
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

def grounded_answer(question,evidence,history=None):
    if not evidence:return '知识库中未检索到相关依据。请补充作业类型或上传并核验相关原文，我不会编造条款。',[],{'mode':'offline','reason':'无相关证据，未调用生成模型'}
    choice,meta=ask_json('你是法规检索助手。根据问题和历史，选择最能直接回答问题的原文片段，最多3条。不得改写或补造条款。输出 {"evidence_ids":["chunk_id"]}。',{'question':question,'history':history or [],'evidence':[{k:e.get(k) for k in ['chunk_id','doc_no','section','text']} for e in evidence]},max_tokens=600)
    selected=[]
    if choice:
        ids=choice.get('evidence_ids',[])
        selected=[e for e in evidence if e['chunk_id'] in ids][:3]
    selected=([evidence[0]]+[e for e in selected if e['chunk_id']!=evidence[0]['chunk_id']])[:3] if selected else evidence[:3]
    # Only original source text is emitted. A model cannot introduce an unverified clause.
    lines=['根据已核验的知识库原文，检索到以下依据：']
    for i,e in enumerate(selected,1):
        lines.append(f"\n{i}.《{e['name']}》 {e['doc_no']} {e['section']}（{evidence_label(e)}）\n{e['text']}")
    lines.append('\n请结合现场实际、适用范围及专项方案人工核对；以上为原文检索结果。')
    return '\n'.join(lines),selected,meta

def evidence_label(e):
    semantic={'法规依据':'法规原文，适用范围仍需人工核对','项目资料':'项目内部执行资料，不作为法规依据','案例参考':'仅供学习警示，不作为法规依据'}
    return e['display_status']+'；'+semantic[e['category']]

def run_chat(run_id,question,sid,source_id):
    try:
        owner=db.one('SELECT user_id FROM chat_sessions WHERE id=?',(sid,))['user_id']
        memory=memory_context(owner,sid)
        history=memory['recent_messages']
        retrieval=question
        if any(x in question for x in ['上述','这个','它的','那条','再解释']) and len(question)<25:
            previous=[m['content'] for m in history[:-1] if m['role']=='user']
            if previous:retrieval=previous[-1]+' '+question
        memory_command=question.startswith(('记住','请记住')) or any(x in question for x in ['你记得我','记住了什么','我的项目背景'])
        evidence=[] if memory_command else search(retrieval,source_id=source_id)
        if evidence:
            e=evidence[0]
            prelude=f"根据已核验的知识库原文，检索到以下依据：\n\n1.《{e['name']}》 {e['doc_no']} {e['section']}（{evidence_label(e)}）\n{e['text']}"
            db.write('UPDATE chat_runs SET answer=? WHERE id=?',(prelude,run_id))
        db.write('UPDATE chat_runs SET status_message=? WHERE id=?',('已完成检索，正在依据原文整理回答',run_id))
        if question.startswith(('记住','请记住')):
            mid=remember(owner,question,sid,history[-1]['id'] if history else None)
            answer=('已按当前身份保存这条长期记忆：'+question+'。可在“小安的记忆与背景”查看或删除。') if mid else '这条信息涉及密码或密钥，未加入长期记忆。'
            refs=[];meta={'mode':'offline','reason':'显式记忆操作，不需要调用大模型'}
        elif any(x in question for x in ['你记得我','记住了什么','我的项目背景']):
            answer='当前身份的长期记忆（用户提供，未经现场独立核验）：\n'+'\n'.join(m['value'] for m in memory['long_term_user_provided']) if memory['long_term_user_provided'] else '当前身份没有已确认的长期记忆。你可以用“记住……”明确指定。'
            refs=[];meta={'mode':'offline'}
        else:answer,refs,meta=grounded_answer(question,evidence,memory)
        prefix='当前为离线兜底结果\n\n' if meta['mode']=='offline' else f"大模型辅助检索 · {meta['model']}\n\n"
        answer=answer+'\n\n'+prefix.strip()
        with db.connect() as c:
            if not c.execute('SELECT 1 FROM chat_sessions WHERE id=?',(sid,)).fetchone():return
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
        c.execute('INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(sid,'user',body.message,db.now()))
        c.execute('INSERT INTO chat_runs(id,session_id,user_id,status,status_message,created_at) VALUES(?,?,?,?,?,?)',(rid,sid,user['id'],'running','正在检索知识库原文',db.now()))
        db.audit(c,user['id'],'ask','session',sid,{'run_id':rid})
    pool.submit(run_chat,rid,body.message,sid,body.source_id)
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
