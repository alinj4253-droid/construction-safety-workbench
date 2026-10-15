import pytest
from backend.app import db

@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DB',str(tmp_path/'test.db'))
    db.init_db()
    return db

def test_schema_seed_idempotence(store):
    store.init_db()
    assert store.one('SELECT count(*) n FROM hazards')['n']==6
    assert store.one('SELECT count(*) n FROM kb_sources')['n']==74
    assert store.one("SELECT count(*) n FROM hazards WHERE confirmed_at IS NULL AND source='ai_monitor'")['n']==0
    assert store.one("SELECT count(*) n FROM monitor_snapshots WHERE status='pending'")['n']==4
    assert sum(store.overdue(h) for h in store.rows('SELECT * FROM hazards'))==1

def test_transition_guards(store):
    with pytest.raises(ValueError):store.next_status('heavy','待整改','review_close','合格')
    with pytest.raises(ValueError):store.next_status('heavy','pending_human','review_close','合格')
    with pytest.raises(ValueError):store.next_status('heavy','待复查','review_close','')
    assert store.next_status('heavy','待复查','review_return','防护未固定')=='整改中'
    assert store.password_ok('123456',store.one('SELECT * FROM users WHERE id=1')['password_hash'])
