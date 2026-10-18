import json
import sqlite3
import uuid
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from backend.app import db
from backend.app.main import app
from backend.app.memory import context
from backend.app.chat import grounded_answer
from backend.rag.query import resolve_query,analyze_query
from backend.rag.knowledge import search,Knowledge,cite_allowed

RESULTS=[]

@pytest.fixture(scope='module',autouse=True)
def report():
    yield
    (db.ROOT/'artifacts/assistant-conversation-regression.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf-8')

@pytest.fixture
def client(tmp_path,monkeypatch):
    path=tmp_path/'conversation.db'
    with sqlite3.connect(db.db_path()) as src,sqlite3.connect(path) as dst:src.backup(dst)
    src.close();dst.close()
    monkeypatch.setenv('APP_DB',str(path));monkeypatch.setenv('LLM_ENABLED','0')
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'}).json()['data']['token']
        yield c

def send(c,question,sid=None,source_id=None):
    response=c.post('/api/chat/stream',json={'message':question,'session_id':sid,'source_id':source_id})
    assert response.status_code==200,response.text
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['type']=='done',events
    sid=events[0]['session_id'];answer=''.join(e['content'] for e in events if e['type']=='token')
    messages=c.get(f'/api/sessions/{sid}/messages').json()['data']
    assert messages[-1]['content']==answer
    for ref in events[-1]['references']:
        current=db.one('SELECT text,source_id,section FROM kb_chunks WHERE chunk_id=?',(ref['chunk_id'],))
        assert current=={k:ref[k] for k in current}
        assert ref['citation_eligible'] or ref['category']!='法规依据'
        detail=c.get(f"/api/kb/sources/{ref['source_id']}?chunk={ref['chunk_id']}")
        assert detail.status_code==200 and any(r['text']==ref['text'] for r in detail.json()['data']['chunks'])
    return {'question':question,'session_id':sid,'answer':answer,'references':events[-1]['references'],'mode':events[-1]['mode']}

def railing(result):
    assert any(e['doc_no']=='JGJ80-2016' and e['section']=='4.3.1' for e in result['references'])
    assert not any(e['section']=='4.1.1' for e in result['references'])
    assert '未检索到相关依据' not in result['answer']

def test_a_b_c_d_e_api_conversation(client):
    a=send(client,'基坑临边防护有什么要求？');railing(a)
    b=send(client,'那工地上，这种防护常见的不规范情况有哪些？',a['session_id']);railing(b)
    c=send(client,'那这个防护常见的隐患有哪些？',a['session_id']);railing(c)
    for r in [b,c]:
        assert '当前讨论：基坑临边防护' in r['answer']
        assert '归纳的检查项' in r['answer'] and '不是经过实际统计的高频隐患' in r['answer']
        for term in ['核查','两道横杆','1.2m','立杆间距','2m','挡脚板','180mm','依据[']:assert term in r['answer']
        assert all('脚手架' not in ref['name'] or '基坑' in ref['text'] for ref in r['references'])
    d=send(client,'基坑临边防护常见的隐患有哪些？');railing(d)
    e=send(client,'施工临时用电接地要求',a['session_id'])
    assert e['references'] and all(x['doc_no']!='JGJ80-2016' for x in e['references'])
    assert any(x['doc_no']=='JGJ/T46-2024' for x in e['references'])
    follow=send(client,'它有哪些不合规情况需要核查？',a['session_id'])
    assert '当前讨论：施工临时用电接地' in follow['answer']
    assert all(x['doc_no']!='JGJ80-2016' for x in follow['references'])
    RESULTS.append({'scenario':'A—E实际API','result':'通过','turns':[a,b,c,d,e,follow]})

@pytest.mark.parametrize('question',[
    '基坑边的栏杆有哪些不合规现象？','请列出临边防护需要排查的缺陷。','施工现场的防护栏杆怎么验收？',
    '基坑临边护栏有哪些容易忽略的风险点？','防护栏杆的横杆和挡脚板应该如何检查？',
    '工地基坑临边防护最常见的问题有没有统计？',
])
def test_natural_variants_recall(question):
    rows=search(question,regulatory_only=True)
    assert any(r['doc_no']=='JGJ80-2016' and r['section']=='4.3.1' for r in rows)
    assert all(r['citation_eligible'] for r in rows)

@pytest.mark.parametrize('question',[
    '那工地上，这种防护常见的不规范情况有哪些？','那这个防护常见的隐患有哪些？','它需要检查哪些项目？',
    '上述措施有哪些薄弱环节？','刚才说的还需要注意哪些检查事项？','这类设施还有哪些检查点需要关注？',
    '还有哪些检查点需要关注？',
    '那现场，你刚才说的这种防护有哪些隐患？','前述这类措施，能再讲讲检查要点吗？',
    '请概括一下它需要注意的检查事项。','刚才提到的这种防护，现场验收时该注意什么？',
])
def test_pronoun_resolution(question):
    history=[{'id':1,'role':'user','content':'请介绍基坑临边防护的要求。'},{'id':2,'role':'assistant','content':'不要把助手中提到的临时用电当作用户话题。'},{'id':3,'role':'user','content':'那这种防护常见的隐患有哪些？'}]
    result=resolve_query(question,history)
    assert result['subject']=='基坑临边防护' and result['context_message_id']==1 and not result['needs_clarification']

def test_long_chain_reload_summary_and_long_memory(client):
    first=send(client,'基坑临边防护有什么要求？');sid=first['session_id']
    client.post('/api/memory',json={'value':'记住，我平常负责临时用电接地项目'})
    memory=send(client,'请记住，我负责厦门项目',sid);assert memory['mode']=='memory'
    for _ in range(7):
        r=send(client,'还有哪些检查点需要关注？',sid);railing(r)
        assert '当前讨论：基坑临边防护' in r['answer']
    recall=send(client,'请告诉我，你记住了什么？',sid);assert recall['mode']=='memory'
    assert '当前讨论：基坑临边防护' in send(client,'这种措施还要检查哪些项目？',sid)['answer']
    summary=db.one('SELECT * FROM session_summaries WHERE session_id=?',(sid,));assert summary and summary['source_message_ids']
    for _ in range(32):
        db.write('INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(sid,'user','还有哪些检查点需要关注？'+' '*230,db.now()))
        db.write('INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(sid,'assistant','尚待继续核查。'*40,db.now()))
    state=context(1,sid);assert len(state['recent_messages'])==8
    assert '基坑临边防护有什么要求' not in state['session_summary']
    assert client.get(f'/api/sessions/{sid}/messages').status_code==200
    reloaded=send(client,'刚才说的这种防护，有哪些隐患？',sid);railing(reloaded)
    assert '当前讨论：基坑临边防护' in reloaded['answer']
    recalled=send(client,'你记得我的项目背景吗');assert recalled['mode']=='memory' and '厦门项目' in recalled['answer']
    assert client.get('/api/memory').json()['data']['long_term']
    RESULTS.append({'scenario':'G历史重载、超出短期及摘要窗口、长期记忆不污染','result':'通过','turns':[reloaded,recalled]})

def test_new_session_unknown_and_ambiguous_topics(client):
    first=send(client,'基坑临边防护要求')
    empty=send(client,'这种防护有哪些隐患？');assert empty['mode']=='clarification' and not empty['references']
    mixed=send(client,'临边防护和临时用电接地都讨论过，这个有哪些隐患？',first['session_id'])
    assert mixed['mode']=='clarification' and not mixed['references']
    unknown=send(client,'那火星量子计算机维修怎么检查？',first['session_id'])
    assert unknown['mode']=='no_evidence' and '离线兜底' not in unknown['answer']
    after=send(client,'它还有哪些不规范情况？',first['session_id'])
    assert after['mode']=='no_evidence' and not after['references']
    explicit=send(client,'这个消防水泵有哪些缺陷？',first['session_id'])
    assert all(ref['doc_no']!='JGJ80-2016' for ref in explicit['references']) and '当前讨论：基坑临边防护' not in explicit['answer']
    RESULTS.append({'scenario':'不明确指代及未知话题切换','result':'通过','turns':[empty,mixed,unknown,after,explicit]})

def test_account_isolation_and_duplicate_inflight(client):
    first=send(client,'基坑临边防护要求');sid=first['session_id']
    token=client.post('/api/auth/login',json={'username':'AQ20260002','password':'123456'}).json()['data']['token']
    headers={'Authorization':'Bearer '+token}
    assert client.get(f'/api/sessions/{sid}/messages',headers=headers).status_code==404
    assert client.post('/api/chat/stream',headers=headers,json={'message':'这个怎么查','session_id':sid}).status_code==404
    with pytest.raises(HTTPException):context(2,sid)
    db.write('INSERT INTO chat_runs(id,session_id,user_id,status,created_at) VALUES(?,?,?,?,?)',(uuid.uuid4().hex,sid,1,'running',db.now()))
    assert client.post('/api/chat/stream',json={'message':'这个怎么查','session_id':sid}).status_code==409

@pytest.mark.parametrize('state',[
    {'status':'待核验'},{'status':'历史版本','legal_status':'已废止'},{'region':'北京'},
    {'parsed':0},{'effective_date':'2099-01-01'},
])
def test_f_source_status_and_region_guards(client,state):
    sid=db.one("SELECT id FROM kb_sources WHERE doc_no='JGJ80-2016' AND status='现行'")['id']
    assignments=','.join(k+'=?' for k in state)
    db.write('UPDATE kb_sources SET '+assignments+' WHERE id=?',(*state.values(),sid))
    result=send(client,'基坑临边防护隐患检查',source_id=sid)
    assert result['mode']=='no_evidence' and not result['references'] and '离线兜底' not in result['answer']

def test_f_inactive_clause_source_limit_and_multiple_standards(client):
    rows=search('基坑临边防护',regulatory_only=True)
    assert {'JGJ80-2016','GB55034-2022'}.issubset({r['doc_no'] for r in rows})
    row=next(r for r in rows if r['doc_no']=='JGJ80-2016' and r['section']=='4.3.1')
    limited=search('基坑临边防护隐患',source_id=row['source_id'],regulatory_only=True)
    assert limited and all(r['source_id']==row['source_id'] for r in limited)
    db.write('UPDATE chunk_states SET active=0 WHERE chunk_id=?',(row['chunk_id'],))
    assert not search('基坑临边防护',source_id=row['source_id'],regulatory_only=True)
    assert not search('基坑临边防护',source_id=0,regulatory_only=True)
    history=search('基坑临边防护',include_history=True)
    assert all(not r['citation_eligible'] for r in history if r['section']=='4.1.1')
    RESULTS.append({'scenario':'F规范共存、source_id、条款失效和引用追溯','result':'通过','retrieved_before_inactivation':rows})

def test_model_output_is_limited_to_verifiable_choices(client,monkeypatch):
    rows=search('基坑临边防护',regulatory_only=True)
    import backend.app.chat as chat_module
    def malicious(*args,**kwargs):return {'evidence_ids':['invented-source'],'check_ids':['invented-check'],'answer':'根据JGJ999-2099第9.9.9条，立杆间距99m'}, {'mode':'online','model':'controlled-invalid-response'}
    monkeypatch.setattr(chat_module,'ask_json',malicious)
    result=send(client,'基坑临边防护有哪些隐患？');railing(result)
    assert result['mode']=='offline' and 'JGJ999' not in result['answer'] and '99m' not in result['answer']
    def unavailable(*args,**kwargs):return None,{'mode':'offline','reason':'受控接口失败'}
    monkeypatch.setattr(chat_module,'ask_json',unavailable)
    failed=send(client,'基坑临边防护有哪些检查项目？');railing(failed)
    assert '180mm' in failed['answer'] and failed['mode']=='offline'
    def unexpected(*args,**kwargs):raise AssertionError('无证据时不得调用模型')
    monkeypatch.setattr(chat_module,'ask_json',unexpected)
    empty=send(client,'火星量子计算机维修');assert empty['mode']=='no_evidence' and '离线兜底' not in empty['answer']

def test_check_items_preserve_condition_values_and_recommendations(client):
    rows=search('基坑临边防护',regulatory_only=True)
    from backend.app.answers import check_units
    units=check_units(rows)
    conditional=next(u for u in units if '600mm' in u['text'])
    assert '当防护栏杆高度大于1.2m时' in conditional['text']
    for unit in units:
        ref=next(e for e in rows if e['chunk_id']==unit['chunk_id'])
        assert unit['excerpt'] in ref['text']

def test_component_followups_keep_parent_scope():
    history=[{'id':1,'role':'user','content':'基坑临边防护要求'},{'id':3,'role':'user','content':'那横杆有哪些检查项目？'},{'id':5,'role':'user','content':'请告诉我，你记住了什么？'}]
    result=resolve_query('这种防护还有什么隐患？',history)
    assert result['subject']=='基坑临边防护' and result['facets']==('横杆',)
    scaffold=resolve_query('它的横杆有哪些检查要点？',[{'id':1,'role':'user','content':'脚手架搭设要求'}])
    assert scaffold['kind']=='scaffold' and scaffold['subject']=='脚手架'
    changed=resolve_query('好的，改问施工临时用电接地要求',history)
    assert changed['kind']=='electric'
    assert not cite_allowed({'region':'福建','status':'现行','legal_status':'现行','parsed':1,'category':'法规依据','content_kind':'全文/正文'},region='北京')
    assert resolve_query('这种措施还要检查哪些项目？',history)['subject']=='基坑临边防护'

def test_modal_words_do_not_rewrite_emergency_nouns():
    from backend.app.answers import check_units
    rows=[r for r in Knowledge().chunks if r['status']=='现行' and r['legal_status']=='现行' and '应急' in r['text']]
    assert rows
    units=check_units(rows)
    assert all('是否急' not in u['text'] and '相是否' not in u['text'] for u in units)

def test_evidence_withdrawn_while_model_is_selecting(client,monkeypatch):
    import backend.app.chat as chat_module
    sid=db.one("SELECT id FROM kb_sources WHERE doc_no='JGJ80-2016' AND status='现行'")['id']
    def withdraw(system,payload,**kwargs):
        db.write("UPDATE kb_sources SET status='历史版本',legal_status='已废止' WHERE id=?",(sid,))
        return {'evidence_ids':[payload['evidence'][0]['chunk_id']],'check_ids':[]},{'mode':'online','model':'controlled-version-change'}
    monkeypatch.setattr(chat_module,'ask_json',withdraw)
    result=send(client,'基坑临边防护有哪些隐患？',source_id=sid)
    assert result['mode']=='no_evidence' and not result['references']
    assert 'JGJ80-2016' not in result['answer'] and '180mm' not in result['answer']
