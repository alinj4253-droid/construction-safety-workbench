from __future__ import annotations
import hashlib
import re
from backend.rag.query import analyze_query

MODAL=re.compile(r'不得|不应(?!急)|严禁|应当|必须|(?<![相反适响供效])应(?=由|为|在|采用|使用|设置|安装|增设|采取|与|符合|满足|按|进行|保证|保持|检查|检测|落实|建立|制定|编制|组织|提供|具备|有|将|经|穿|戴|选|标|配|接|设|采|装|连接|分|遵守|执行|确定|控制|禁止|清|监|测|验|报|向|及时|先|定|予|做|保护)|(?<![适便])宜(?=由|为|在|采用|使用|设置|安装|增设|采取|与|按|选|配|大于|小于|不)')

def evidence_label(e):
    semantic={'法规依据':'法规原文，适用范围仍需人工核对','项目资料':'项目内部执行资料，不作为法规依据','案例参考':'仅供学习警示，不作为法规依据'}
    return e['display_status']+'；'+semantic[e['category']]

def answer_intro(profile):
    if profile['intent'] in {'checks','statistics'}:
        return '当前讨论：'+profile['subject']+'。\n以下为依据条款归纳的检查项，不是经过实际统计的高频隐患，也不代表已认定当前工地存在这些问题：'
    return '根据已核验的知识库原文，检索到以下依据：'

def check_units(evidence):
    units=[]
    for e in evidence:
        text=re.sub(r'^(?:第[一二三四五六七八九十百零〇\d]+条|\d+\.\d+\.\d+)\s*','',e['text']).strip()
        text=re.sub(r'([：:；;。])\s*\d+(?:[、．.](?!\d)|\s+)',r'\1\n',text)
        text=re.sub(r'[^，。；;\n]*应符合下列规定[：:]?','',text)
        for excerpt in re.split(r'[。；;\n]+',text):
            excerpt=excerpt.strip(' ，,：:')
            if not MODAL.search(excerpt):continue
            excerpt=re.sub(r'^\d+[、.．]?\s+','',excerpt)
            question=MODAL.sub(lambda m:{'不得':'是否避免','不应':'是否不','严禁':'是否避免','宜':'是否按建议'}.get(m.group(),'是否'),excerpt)+'？'
            cid=hashlib.sha256((e['chunk_id']+'|'+excerpt).encode()).hexdigest()[:20]
            units.append({'id':cid,'chunk_id':e['chunk_id'],'excerpt':excerpt,'text':'核查'+question})
    return units

def build_answer(question,evidence,history,selector,profile=None):
    profile=profile or analyze_query(question)
    if not evidence:
        return '知识库中未检索到相关依据。缺少与当前对象和问题相关、已核验且适用的原文，暂不能据此归纳检查项或给出条款结论。请补充具体作业对象、适用范围或核验相关资料。此状态表示证据不足，尚未调用模型，不能据此判断模型接口是否可用。',[],{'mode':'no_evidence','reason':'没有相关有效证据，未调用模型'}
    candidates=check_units(evidence) if profile['intent'] in {'checks','statistics'} else []
    facets=profile.get('facets',())
    focused=[u for u in candidates if any(facet in u['excerpt'] for facet in facets)]
    if focused:candidates=focused
    choice,meta=selector('你是证据选择助手。根据当前明确对象和问题意图，只选择给定原文片段及已从原文转换的检查项。输出 {"evidence_ids":["chunk_id"],"check_ids":["id"]}，原文最多3条。不得输出新增条款、检查项、现场事实或频率结论。',{'question':question,'subject':profile['subject'],'intent':profile['intent'],'history':history or {},'evidence':[{k:e.get(k) for k in ['chunk_id','doc_no','section','text']} for e in evidence],'check_candidates':candidates},max_tokens=800)
    selected=evidence[:3]
    allowed={e['chunk_id'] for e in evidence}
    chosen_checks=[]
    if choice is not None:
        ids=choice.get('evidence_ids') if isinstance(choice,dict) else None
        checks=choice.get('check_ids',[]) if isinstance(choice,dict) else None
        valid=isinstance(ids,list) and bool(ids) and all(isinstance(x,str) and x in allowed for x in ids)
        valid=valid and isinstance(checks,list) and all(isinstance(x,str) and any(u['id']==x for u in candidates) for x in checks)
        if valid:
            selected=([evidence[0]]+[e for e in evidence if e['chunk_id'] in ids and e['chunk_id']!=evidence[0]['chunk_id']])[:3]
            chosen_checks=[u for u in candidates if u['id'] in checks]
        else:meta={**meta,'mode':'offline','reason':'模型返回的选择无法通过证据编号校验，使用本地原文检查项'}
    selected_ids={e['chunk_id'] for e in selected}
    ordered=chosen_checks+[u for u in candidates if u['id'] not in {chosen['id'] for chosen in chosen_checks}]
    units=[u for u in ordered if u['chunk_id'] in selected_ids][:10]
    numbers={e['chunk_id']:i for i,e in enumerate(selected,1)}
    by_id={e['chunk_id']:e for e in selected}
    lines=[answer_intro(profile)]
    if profile['intent'] in {'checks','statistics'}:
        if not units:lines.append('\n现有证据没有足够具体的可归纳检查要求，不能补造检查项目；请核验下面原文并补充专项依据。')
        for i,u in enumerate(units,1):
            e=by_id[u['chunk_id']]
            lines.append(f"\n{i}. {u['text']}（依据[{numbers[u['chunk_id']]}]：{e['doc_no']} {e['section']}）")
        lines.append('\n是否构成隐患、是否适用于当前作业条件，需要安全员结合现场和专项方案核实。当前证据不包含隐患发生率、排序或占比统计。\n\n对应原文：')
    elif profile['intent']=='explanation':
        lines.append('\n现有证据提供的是规范要求；未检索到独立的原因分析或论证材料，不能将推测写成规范结论。')
    for i,e in enumerate(selected,1):
        lines.append(f"\n[{i}]《{e['name']}》 {e['doc_no']} {e['section']}（{evidence_label(e)}）\n{e['text']}")
    lines.append('\n以上原文和检查项均可通过引用定位核对，不代替现场确认或正式技术方案。')
    return '\n'.join(lines),selected,meta
