"""Two independent model contexts, deterministic blocking rules and at most one rework."""
from __future__ import annotations
import copy
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from backend.app import db
from backend.app.llm import ask_json
from backend.rag.knowledge import search,cite_allowed,canonical

pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='safety-handle')

def issue(kind,location,basis,fix,block=True):
    return {'type':kind,'location':location,'basis':basis,'fix':fix,'block':block}

def rule_check(draft,facts,evidence):
    issues=[]
    for field in ['responsible_team','responsible_person','deadline']:
        if not draft.get(field):issues.append(issue('missing_field',field,'签发必填字段缺失','请安全员补充'+field))
        elif draft[field]!=facts.get(field):issues.append(issue('invented_fact',field,'与现场事实快照不一致','只能使用安全员明确提供的值'))
    if facts.get('source')=='ai_monitor' and not facts.get('confirmed_at'):
        issues.append(issue('unconfirmed_monitor','hazard','监控线索未经人工确认','先在监控页现场确认，不能直接办理文书'))
    refs=draft.get('evidence_ids',[])
    if not refs:issues.append(issue('missing_evidence','evidence','没有相关现行原文','请补充并核验适用原文'))
    available={e['chunk_id']:e for e in evidence}
    for cid in refs:
        current=db.one('SELECT k.*,s.* FROM kb_chunks k JOIN kb_sources s ON s.id=k.source_id WHERE k.chunk_id=?',(cid,))
        if cid not in available or not current:issues.append(issue('missing_chunk',str(cid),'引用不在本次检索证据或不存在','使用本次已检索到的真实片段'));continue
        if not cite_allowed(current):issues.append(issue('invalid_source',str(cid),'版本、审核、类型或地域不满足引用规则','替换为现行、已核验、适用地域的法规原文'))
        if current['text']!=available[cid]['text']:issues.append(issue('changed_evidence',str(cid),'依据正文已更新','重新检索并复核'))
    if draft.get('hazard_title')!=facts['title']:issues.append(issue('invented_fact','hazard_title','隐患描述与已登记事实不一致','保留已登记描述'))
    if draft.get('type')!='rectification_notice':issues.append(issue('wrong_type','type','当前任务为整改通知单','修正文书类型'))
    # A model may never embed a version or clause outside the supplied evidence.
    for no in re.findall(r'(?:JGJ/?T?|GB/?T?|DBJ/?T?)\s*[\d/-]+',draft.get('body',''),flags=re.I):
        if not any(canonical(no)==canonical(e['doc_no']) for e in evidence):issues.append(issue('unsupported_standard','body',no,'删除未提供原文的标准引用'))
    return issues

def local_draft(facts,evidence):
    return {'type':'rectification_notice','hazard_title':facts['title'],'location':facts.get('location',''),'responsible_team':facts.get('responsible_team',''),'responsible_person':facts.get('responsible_person',''),'deadline':facts.get('deadline',''),'body':'已登记隐患：'+facts['description']+'\n\n整改要求：请责任班组结合现场情况，按照下列原文及已批准的专项方案组织整改。具体措施需安全员核对适用条件。整改完成后提交实际整改情况及证据，由安全员现场复查，未复查合格不得销项。','evidence_ids':[e['chunk_id'] for e in evidence[:3]]}

def agent_a(facts,evidence,feedback=None):
    base=local_draft(facts,evidence)
    generated,meta=ask_json('你是Agent A业务办理员。只根据事实快照和给定原文起草整改通知单。输出与template完全相同的JSON字段。责任人、期限、位置不得猜测，未提供必须留空。evidence_ids只能选给定片段。body只写有原文支持的建议，不添加未发生事实。若有反馈逐项修正。不要生成文书编号，不得签发。',{'facts':facts,'evidence':evidence,'template':base,'review_feedback':feedback or []},max_tokens=2200)
    draft=base
    if generated and all(k in generated for k in base) and isinstance(generated.get('evidence_ids'),list) and all(isinstance(generated[k],str) for k in base if k!='evidence_ids') and all(isinstance(k,str) for k in generated['evidence_ids']):
        draft={k:generated[k] for k in base}
    elif generated:meta={**meta,'mode':'offline','reason':'办理输出结构不完整，已使用本地模板'}
    # An identified deterministic defect is fixed from authoritative facts on rework.
    if feedback:
        for problem in feedback:
            field=problem.get('location')
            if field in {'responsible_team','responsible_person','deadline'}:draft[field]=facts.get(field,'')
            if problem.get('type') in {'missing_chunk','invalid_source','unsupported_standard'}:draft=base
    return draft,meta

def agent_b(draft,facts,evidence):
    # New model call: no A instructions, hidden state, reasoning or previous dialogue.
    result,meta=ask_json('你是Agent B独立文书复核员。独立核对draft、现场事实快照facts和原文evidence。检查虚构事实、缺字段、错误引用、证据不支持结论、未确认监控事实、类型错误。给出真实问题，不必为了演示而找错。输出 {"issues":[{"type":"...","location":"...","basis":"...","fix":"...","block":true}]}。不签发，不补造条款。',{'draft':draft,'facts':facts,'evidence':evidence},role='review',max_tokens=1700)
    if result and isinstance(result.get('issues'),list):
        valid=[]
        for p in result['issues']:
            if isinstance(p,dict) and all(k in p for k in ['type','location','basis','fix','block']) and isinstance(p['block'],bool):valid.append({k:p[k] for k in ['type','location','basis','fix','block']})
        if len(valid)==len(result['issues']):return valid,meta
    # Offline independent review re-reads records; it is honestly labelled as rule fallback.
    return rule_check(copy.deepcopy(draft),copy.deepcopy(facts),copy.deepcopy(evidence)),{**meta,'mode':'offline','reason':'独立复核为规则兜底，不能替代人工语义审核'}

def step(task_id,name,payload,status):
    with db.connect() as c:
        task=dict(c.execute('SELECT * FROM handle_tasks WHERE id=?',(task_id,)).fetchone())
        steps=json.loads(task['steps_json'] or '[]');steps.append({'name':name,'time':db.now(),'payload':payload})
        c.execute('UPDATE handle_tasks SET status=?,steps_json=? WHERE id=?',(status,db.dumps(steps),task_id))
        db.event(c,task['hazard_id'],name,task['created_by'],{'task_id':task_id,'payload':payload})

def execute(task_id):
    task=db.one('SELECT * FROM handle_tasks WHERE id=?',(task_id,));inp=db.one('SELECT * FROM task_inputs WHERE task_id=?',(task_id,))
    facts=json.loads(inp['facts_json']);case=inp['test_case'];did=None
    try:
        query=facts.get('category','')+' '+facts['title']
        topics=[x for x in ['临边','楼梯口','临时用电','接地','脚手架','连墙件','安全帽','模板','有限空间','起重机械'] if x in query]
        evidence=[] if case=='no_evidence' else search(' '.join(topics) if topics else query,for_document=True,limit=3)
        step(task_id,'检索规范原文',{'evidence':evidence,'facts':facts,'test_case':case or None},'drafting')
        with db.connect() as c:
            did=c.execute('INSERT INTO documents(hazard_id,type,title,content_json,status,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(task['hazard_id'],'rectification_notice','安全隐患整改通知单',db.dumps({}),'draft',task['created_by'],db.now())).lastrowid
            c.execute('UPDATE handle_tasks SET document_id=? WHERE id=?',(did,task_id))
        if not evidence:
            content={**local_draft(facts,[]),'evidence':[],'mode':'offline','missing_fields':['相关适用原文'],'test_case':case}
            db.write('UPDATE documents SET content_json=?,status=? WHERE id=?',(db.dumps(content),'rework',did))
            db.write('INSERT INTO document_reviews(document_id,round,reviewer,result_json,created_at) VALUES(?,?,?,?,?)',(did,0,'规则校验',db.dumps({'issues':[issue('missing_evidence','evidence','知识库中未检索到相关依据','补充原文后重新办理')]}),db.now()))
            step(task_id,'转人工补充资料',{'reason':'知识库中未检索到相关依据；未起草可签发文书'},'needs_input');return
        feedback=[]
        for attempt in range(2):
            draft,meta_a=agent_a(facts,evidence,feedback)
            if case in {'invented_deadline','stubborn'} and (attempt==0 or case=='stubborn'):
                draft['deadline']='2099-12-31'
            if case=='expired_reference' and attempt==0:draft['evidence_ids']=['test-nonexistent-expired-JGJ46-2005']
            step(task_id,'Agent A '+('起草' if attempt==0 else '返工修订'),{'version':attempt+1,'draft':draft,'evidence':evidence,'model':meta_a,'fixture_label':'明确标记的验收测试草稿' if case else None},'rule_check')
            rules=rule_check(draft,facts,evidence)
            step(task_id,'程序规则校验',{'issues':rules,'round':attempt+1},'reviewing')
            review,meta_b=agent_b(draft,facts,evidence)
            issues=rules+review
            payload={**draft,'evidence':[e for e in evidence if e['chunk_id'] in draft.get('evidence_ids',[])],'mode':'offline' if meta_a['mode']=='offline' or meta_b['mode']=='offline' else 'online','models':{'a':meta_a,'b':meta_b},'test_case':case,'missing_fields':[p['location'] for p in issues if p['type']=='missing_field']}
            with db.connect() as c:
                c.execute('UPDATE documents SET content_json=?,draft_version=?,status=? WHERE id=?',(db.dumps(payload),attempt+1,'reviewing',did))
                c.execute('INSERT INTO document_versions(document_id,version,content_json,created_at) VALUES(?,?,?,?)',(did,attempt+1,db.dumps(payload),db.now()))
                for reviewer,problems,meta in [('规则校验',rules,{'mode':'rules'}),('Agent B',review,meta_b)]:
                    c.execute('INSERT INTO document_reviews(document_id,round,reviewer,result_json,created_at) VALUES(?,?,?,?,?)',(did,attempt+1,reviewer,db.dumps({'issues':problems,'model':meta}),db.now()))
            step(task_id,'Agent B 独立复核',{'round':attempt+1,'issues':review,'rule_issues':rules,'model':meta_b},'reviewing')
            if not any(p.get('block') for p in issues):
                db.write('UPDATE documents SET status=? WHERE id=?',('pending_human',did))
                step(task_id,'等待人工确认签发',{'conclusion':'AI 检查未发现阻断问题，待人工确认'},'pending_human');return
            feedback=issues
            if attempt==0:
                db.write('UPDATE documents SET status=? WHERE id=?',('rework',did));step(task_id,'复核退回',{'issues':issues,'rework_count':1},'rework')
            else:
                db.write('UPDATE documents SET status=? WHERE id=?',('rework',did));step(task_id,'转人工补充资料',{'issues':issues,'reason':'已达到最多1轮返工，请补资料后重新办理'},'needs_input')
    except Exception as e:
        db.write('UPDATE handle_tasks SET status=?,error=? WHERE id=?',('error','办理中断：'+type(e).__name__,task_id))
        if did:db.write('UPDATE documents SET status=? WHERE id=?',('rework',did))
