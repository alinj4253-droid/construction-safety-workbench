"""Short context, incremental extractive summaries and explicit opt-in long-term memory."""
from __future__ import annotations
import re
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from backend.app import db
from backend.app.security import current_user
router=APIRouter(prefix='/api/memory')
RECENT=8

def remember(user_id,text,session_id=None,message_id=None):
    text=text.strip()
    if re.search(r'sk-[A-Za-z0-9]{12,}|密码|口令|密钥|API.?KEY',text,re.I):return None
    same=db.one('SELECT id FROM user_memories WHERE user_id=? AND value=? AND active=1',(user_id,text))
    if same:return same['id']
    with db.connect() as c:
        mid=c.execute('INSERT INTO user_memories(user_id,value,source_session_id,source_message_id,created_at,updated_at) VALUES(?,?,?,?,?,?)',(user_id,text[:1500],session_id,message_id,db.now(),db.now())).lastrowid
        db.audit(c,user_id,'remember_explicit','memory',mid,{'source_message_id':message_id})
    return mid

def context(user_id,sid,through_message_id=None):
    if not db.one('SELECT id FROM chat_sessions WHERE id=? AND user_id=?',(sid,user_id)):raise HTTPException(404,'会话不存在')
    messages=db.rows('SELECT id,role,content FROM chat_messages WHERE session_id=? '+('AND id<=? ' if through_message_id is not None else '')+'ORDER BY id',(sid,through_message_id) if through_message_id is not None else (sid,))
    older=messages[:-RECENT]
    summary=db.one('SELECT * FROM session_summaries WHERE session_id=?',(sid,))
    if older and (not summary or older[-1]['id']>summary['summarized_through']):
        # Extract original user facts and original assistant conclusions; never invent a memory fact.
        lines=[f"消息{m['id']} {m['role']}：{m['content'][:220]}" for m in older]
        text='\n'.join(lines)[-6000:]
        ids=[m['id'] for m in older if f"消息{m['id']} " in text]
        with db.connect() as c:
            c.execute('INSERT INTO session_summaries VALUES(?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary,summarized_through=excluded.summarized_through,source_message_ids=excluded.source_message_ids,updated_at=excluded.updated_at',(sid,text,older[-1]['id'],db.dumps(ids),db.now()))
            c.execute('UPDATE chat_sessions SET summary=? WHERE id=?',(text,sid))
        summary={'summary':text,'source_message_ids':db.dumps(ids)}
    memories=db.rows('SELECT id,value,source_session_id,source_message_id FROM user_memories WHERE user_id=? AND active=1 ORDER BY id DESC LIMIT 20',(user_id,))
    return {'recent_messages':messages[-RECENT:],'session_summary':summary['summary'] if summary else '', 'long_term_user_provided':memories,'boundary':'记忆是用户提供的项目背景，不是法规依据；没有确认过的现场事实不得用于文书签发。'}

@router.get('')
def list_memory(user=Depends(current_user)):
    return {'code':0,'data':{'long_term':db.rows('SELECT id,value,source_session_id,source_message_id,created_at FROM user_memories WHERE user_id=? AND active=1 ORDER BY id DESC',(user['id'],)),'summaries':db.rows('SELECT s.id,s.title,s.summary FROM chat_sessions s WHERE s.user_id=? AND s.summary<>\'\' ORDER BY s.updated_at DESC LIMIT 10',(user['id'],)),'recent_window':RECENT},'message':'ok'}

class MemoryInput(BaseModel):value:str=Field(min_length=2,max_length=1500)
@router.post('')
def add_memory(body:MemoryInput,user=Depends(current_user)):
    mid=remember(user['id'],body.value)
    if not mid:raise ValueError('密码、密钥等敏感内容不能加入长期记忆')
    return {'code':0,'data':{'id':mid},'message':'已按当前身份保存长期记忆'}

@router.delete('/{mid:int}')
def forget(mid:int,user=Depends(current_user)):
    with db.connect() as c:
        row=c.execute('SELECT id FROM user_memories WHERE id=? AND user_id=? AND active=1',(mid,user['id'])).fetchone()
        if not row:raise HTTPException(404,'记忆不存在')
        c.execute('UPDATE user_memories SET active=0,updated_at=? WHERE id=?',(db.now(),mid));db.audit(c,user['id'],'forget_memory','memory',mid)
    return {'code':0,'data':None,'message':'记忆已删除，不再参与回答'}
