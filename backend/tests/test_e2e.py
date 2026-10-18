"""Five acceptance stories. Synthetic review defect is explicitly gated in test env only."""
import csv
import hashlib
import io
import json
import sqlite3
import time
import uuid
from datetime import timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import db
from backend.app.main import app
from backend.rag.knowledge import search

RESULTS=[]
@pytest.fixture(scope='module',autouse=True)
def evidence_report():
    yield
    out=db.ROOT/'artifacts/e2e-results.json'
    out.write_text(db.dumps({'run_at':db.now(),'environment':'隔离SQLite副本；关闭LLM；返工缺陷为明确标记的验收草稿注入，正式业务不会故意制造错误','scenarios':RESULTS,'all_passed':len(RESULTS)==5 and all(r['result']=='通过' for r in RESULTS)}),encoding='utf-8')

@pytest.fixture
def client(tmp_path,monkeypatch):
    target=tmp_path/'e2e.db'
    with sqlite3.connect(db.db_path()) as src,sqlite3.connect(target) as dst:src.backup(dst)
    monkeypatch.setenv('APP_DB',str(target));monkeypatch.setenv('LLM_ENABLED','0');monkeypatch.setenv('ALLOW_TEST_DRAFTS','1')
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        yield c

def chat(c,q,source_id=None):
    r=c.post('/api/chat/stream',json={'message':q,'source_id':source_id});assert r.status_code==200,r.text
    events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ')]
    done=next(e for e in events if e['type']=='done');sid=events[0]['session_id']
    answer=''.join(e['content'] for e in events if e['type']=='token')
    stored=c.get(f'/api/sessions/{sid}/messages').json()['data'][-1]['content'];assert stored==answer
    return {'question':q,'answer':answer,'references':done['references'],'mode':done['mode'],'session_id':sid}

def handling(c,fixture=None):
    h=c.post('/api/hazards',json={'title':'E2E 7#楼临边防护缺失，坠落高度3m','location':'7#楼二层','track':'heavy','responsible_team':'E2E木工班组','responsible_person':'E2E实际责任人','deadline':str(db.today()+timedelta(days=2))}).json()['data']
    before=db.one('SELECT count(*) n FROM hazards')['n']
    body={'hazard_id':h['id']}
    if fixture:body['test_case']=fixture
    tid=c.post('/api/handle/tasks',json=body).json()['data']['task_id']
    for _ in range(200):
        task=c.get('/api/handle/tasks/'+tid).json()['data']
        if task['status'] in {'pending_human','needs_input','error'}:break
        time.sleep(.05)
    assert task['status']=='pending_human',task
    did=task['document_id'];assert task['document']['content']['mode']=='offline'
    assert db.one('SELECT status FROM hazards WHERE id=?',(h['id'],))['status']=='待整改'
    assert c.post(f'/api/documents/{did}/issue',json={'confirmed':False}).status_code==400
    issued=c.post(f'/api/documents/{did}/issue',json={'confirmed':True});assert issued.status_code==200,issued.text
    assert db.one('SELECT count(*) n FROM hazards')['n']==before
    assert c.post(f'/api/documents/{did}/issue',json={'confirmed':True}).json()['data']==issued.json()['data']
    for action,note in [('urge','E2E已电话督促，记录实际意见'),('submit_rectify','现场已安装防护栏杆和挡脚板并提交照片，申请复查'),('review_return','复查发现挡脚板仍未固定，退回整改'),('submit_rectify','挡脚板重新固定完成，请复查'),('review_close','现场复查防护设施符合适用原文与方案要求，确认销项')]:
        r=c.post(f"/api/hazards/{h['id']}/actions",json={'action':action,'note':note});assert r.status_code==200,r.text
    detail=c.get(f"/api/hazards/{h['id']}").json()['data'];assert detail['status']=='已销项' and detail['track']=='heavy' and detail['source']=='manual'
    actions=[e['action'] for e in detail['events']]
    assert {'register','create_handle_task','Agent A 起草','Agent B 独立复核','issue_document','urge','submit_rectify','review_return','review_close'}.issubset(set(actions))
    export=c.get('/api/hazards/export?filter=heavy');assert export.status_code==200
    rows=list(csv.DictReader(io.StringIO(export.content.decode('utf-8-sig'))));exported=next(r for r in rows if int(r['id'])==h['id'])
    assert exported['status']=='已销项' and 'review_close' in exported['event_summary'] and issued.json()['data']['doc_no'] in exported['documents']
    citations=db.rows('SELECT * FROM document_citations WHERE document_id=?',(did,));assert citations
    for cite in citations:
        sid=json.loads(cite['snapshot_json'])['source_id']
        count=db.one('SELECT count(DISTINCT dc.document_id) n FROM document_citations dc JOIN kb_chunks k ON k.chunk_id=dc.chunk_id WHERE k.source_id=?',(sid,))['n']
        assert count==db.one('SELECT cite_count FROM kb_sources WHERE id=?',(sid,))['cite_count']
    word=c.get(f'/api/documents/{did}/export');assert word.content.startswith(b'PK')
    reviews=db.rows('SELECT * FROM document_reviews WHERE document_id=?',(did,))
    return {'hazard_id':h['id'],'document':issued.json()['data'],'final_status':detail['status'],'mode':'offline','draft_version':task['document']['draft_version'],'reviews':reviews,'events':detail['events'],'citation_count':len(citations),'word_sha256':hashlib.sha256(word.content).hexdigest(),'ledger_sha256':hashlib.sha256(export.content).hexdigest()}

def test_scenario_1_hazard_closed_loop(client):
    result=handling(client,'invented_deadline')
    assert result['draft_version']==2
    first=[json.loads(r['result_json']) for r in result['reviews'] if r['round']==1]
    assert any(any(p['type']=='invented_fact' for p in r['issues']) for r in first)
    assert all(not any(p['block'] for p in json.loads(r['result_json'])['issues']) for r in result['reviews'] if r['round']==2)
    RESULTS.append({'scenario':1,'name':'隐患闭环主线','result':'通过','evidence':result})

def test_scenario_2_monitor_clue(client):
    c=client;pending=c.get('/api/monitor/snapshots').json()['data'];assert len(pending)>=2
    a,b=pending[:2];before=db.one('SELECT count(*) n FROM hazards')['n']
    hid=c.post(f"/api/monitor/snapshots/{a['id']}/confirm",json={'note':'E2E人工现场核实未戴安全帽'}).json()['data']['hazard_id']
    assert c.post(f"/api/monitor/snapshots/{b['id']}/dismiss",json={'note':'E2E遮挡误报，不构成隐患'}).status_code==200
    assert db.one('SELECT count(*) n FROM hazards')['n']==before+1
    assert db.one('SELECT hazard_id FROM monitor_snapshots WHERE id=?',(b['id'],))['hazard_id'] is None
    assert c.post(f'/api/hazards/{hid}/actions',json={'action':'submit_rectify','note':'现场已佩戴安全帽并完成纠正教育'}).status_code==200
    h=c.get(f'/api/hazards/{hid}').json()['data'];assert h['track']=='light' and h['status']=='已闭环' and h['source']=='ai_monitor'
    RESULTS.append({'scenario':2,'name':'监控线索线','result':'通过','evidence':{'confirmed_snapshot':a['id'],'dismissed_snapshot':b['id'],'hazard':h,'ledger_delta':1}})

def test_scenario_3_regulation_search(client):
    border=chat(client,'临边防护要求');power=chat(client,'临时用电接地要求');none=chat(client,'火星量子计算机维修')
    assert any(e['doc_no']=='JGJ80-2016' and e['section']=='4.3.1' for e in border['references'])
    assert all(e['section']!='4.1.1' for e in border['references'])
    assert any(e['doc_no']=='JGJ/T46-2024' for e in power['references'])
    assert all(e['doc_no']!='JGJ46-2005' for e in power['references'])
    assert '知识库中未检索到相关依据' in none['answer'] and not none['references']
    RESULTS.append({'scenario':3,'name':'法规检索线','result':'通过','evidence':[border,power,none]})

def test_scenario_4_kb_governance(client):
    c=client;marker=uuid.uuid4().hex[:8]
    def upload(no,extra):
        text='第一条 红杉围挡巡检应登记现场时间、地点、人员、发现事项和整改经过。第二条 对发现的围挡损坏，应及时组织维护并登记检查结果。第三条 红杉围挡巡检应按项目制度落实责任人员，维修后留存复查记录，资料应如实归档。'+extra
        r=c.post('/api/kb/sources',data={'name':'E2E合成红杉围挡巡检'+extra,'category':'法规依据','doc_no':no,'region':'国家','effective_date':'2020-01-01'},files={'file':('qa.txt',text.encode(),'text/plain')});assert r.status_code==200,r.text
        return r.json()['data']
    old=upload('QA-OLD-'+marker,'旧版');new=upload('QA-NEW-'+marker,'新版')
    assert old['status']=='待核验' and not search('红杉围挡巡检',source_id=old['id'])
    for s in [old,new]:assert c.post(f"/api/kb/sources/{s['id']}/confirm",json={'confirmed':True,'note':'E2E合成资料，核实全文与元数据'}).status_code==200
    answer=chat(c,'红杉围挡巡检',old['id']);assert any(e['source_id']==old['id'] for e in answer['references'])
    issued_before=db.rows("SELECT id,content_json FROM documents WHERE status='issued'")
    rule={'old_no':old['doc_no'],'new_no':new['doc_no'],'effective_date':'2020-02-01','basis_url':'E2E合成替代公告，仅验收使用'}
    assert c.post('/api/kb/version-rules',json=rule).status_code==200
    suggestions=c.post('/api/kb/check-updates').json()['data'];assert any(s['source_id']==old['id'] for s in suggestions['suggestions'])
    assert c.post(f"/api/kb/sources/{old['id']}/apply-update",json={'confirmed':True,'note':'已核验替代关系'}).status_code==200
    log=next(l for l in c.get('/api/kb/changelog').json()['data'] if l['source_id']==old['id'] and l['action']=='apply_version_update')
    assert c.post(f"/api/kb/changelog/{log['id']}/undo",json={'confirmed':True,'note':'验证撤销不能恢复废止效力'}).status_code==200
    assert not search('红杉围挡巡检',source_id=old['id'],for_document=True)
    assert search('红杉围挡巡检',source_id=new['id'],for_document=True)
    assert issued_before==db.rows("SELECT id,content_json FROM documents WHERE status='issued'")
    RESULTS.append({'scenario':4,'name':'知识库治理线','result':'通过','evidence':{'old_source':old['id'],'new_source':new['id'],'answer_after_review':answer,'update':rule,'undone_change':log,'old_citation_allowed_after_undo':False,'issued_snapshots_unchanged':True}})

def test_scenario_5_offline_fallback(client):
    closed=handling(client)
    answers=[chat(client,q) for q in ['临边防护','临时用电接地','火星量子计算机维修']]
    assert all(a['mode']=='offline' and '当前为离线兜底结果' in a['answer'] for a in answers[:2])
    assert answers[2]['mode']=='no_evidence' and '未检索到相关依据' in answers[2]['answer'] and '离线兜底' not in answers[2]['answer']
    assert closed['final_status']=='已销项'
    RESULTS.append({'scenario':5,'name':'离线降级线','result':'通过','evidence':{'llm_enabled':False,'closed_loop':closed,'answers':answers}})
