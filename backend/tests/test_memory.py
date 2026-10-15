from backend.app import db
from backend.app.memory import remember,context
from backend.app.chat import new_session

def test_long_short_memory_and_provenance(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'memory.db'));db.init_db()
    user={'id':1};sid=new_session(user)
    for i in range(15):db.write('INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(sid,'user' if i%2==0 else 'assistant',f'现场事实原文{i}',db.now()))
    mid=remember(1,'记住我负责3号楼，项目在厦门',sid,1)
    result=context(1,sid)
    assert len(result['recent_messages'])==8
    assert '现场事实原文0' in result['session_summary']
    assert result['long_term_user_provided'][0]['source_message_id']==1
    assert context(1,new_session(user))['long_term_user_provided'][0]['id']==mid
    assert context(2,new_session({'id':2}))['long_term_user_provided']==[]
    assert remember(1,'请记住我的密码是123456') is None
    assert context(1,sid)['session_summary']==result['session_summary']
