"""Explicit local configuration and bounded OpenAI-compatible gateway. Never logs keys."""
from __future__ import annotations
import json
import os
import time
import httpx
from backend.app import db

def config():
    result={}
    path=db.ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                k,v=line.split('=',1);result[k.strip()]=v.strip()
    result.update({k:v for k,v in os.environ.items() if k.startswith(('LLM_','OPENAI_'))})
    return result

def ask_json(system,payload,role='main',max_tokens=2500):
    cfg=config()
    if cfg.get('LLM_ENABLED','1').lower() in {'0','false','no'} or not cfg.get('OPENAI_API_KEY'):
        return None,{'mode':'offline','model':None,'reason':'未启用大模型接口'}
    model=cfg.get('LLM_REVIEW_MODEL','doubao-seed-2-1-turbo-260628') if role=='review' else cfg.get('LLM_MAIN_MODEL','deepseek-v4.1-flash')
    started=time.monotonic()
    try:
        with httpx.Client(timeout=float(cfg.get('LLM_TIMEOUT','30')),trust_env=True) as client:
            response=client.post(cfg.get('OPENAI_BASE_URL','https://api.openai-proxy.org/v1').rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+cfg['OPENAI_API_KEY']},json={'model':model,'messages':[{'role':'system','content':system+'\n只输出合法JSON，不使用代码围栏。'},{'role':'user','content':db.dumps(payload)}],'max_tokens':max_tokens,'thinking':{'type':'disabled'}})
            if response.status_code>=400:return None,{'mode':'offline','model':model,'reason':f'接口HTTP {response.status_code}','seconds':round(time.monotonic()-started,3)}
            result=response.json();text=result['choices'][0]['message'].get('content','') or ''
            start,end=text.find('{'),text.rfind('}')
            parsed=json.loads(text[start:end+1]) if start>=0 else None
            if not isinstance(parsed,dict):raise ValueError('JSON object required')
            return parsed,{'mode':'online','model':result.get('model',model),'seconds':round(time.monotonic()-started,3),'usage':result.get('usage',{})}
    except Exception as e:
        return None,{'mode':'offline','model':model,'reason':'接口或结构化输出不可用：'+type(e).__name__,'seconds':round(time.monotonic()-started,3)}
