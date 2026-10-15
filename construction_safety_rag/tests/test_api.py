from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import app.api as api_module
from app.api import app


def test_health_frontend_and_graph_routes():
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "施工安全证据助手 RAG",
    }

    page = client.get("/")
    assert page.status_code == 200
    assert "施工安全证据助手" in page.text
    assert "示例问题" in page.text
    assert "/project" in page.text

    graph = client.get("/api/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert isinstance(payload["nodes"], list)
    assert isinstance(payload["edges"], list)
    assert payload["depth"] == 2
    assert len(payload["nodes"]) > 20
    assert len(payload["nodes"]) <= 60
    assert len(payload["edges"]) > 20
    clause_search = client.get("/api/graph?entity=第二十五条").json()
    assert clause_search["nodes"]
    assert "· 第二十五条" in clause_search["center"]
    assert clause_search["nodes"][0]["source_refs"]
    assert client.get("/graph").status_code == 200
    assert client.get("/graph.html").status_code == 200

    project = client.get("/project")
    assert project.status_code == 200
    assert "Chunk 切分规则" in project.text
    assert "答辩表达可以概括为" not in project.text
    assert client.get("/project.html").status_code == 200


def test_project_info_exposes_current_kb_metadata():
    payload = TestClient(app).get("/api/project-info").json()
    assert payload["stats"]["sources"] == 18
    assert payload["stats"]["catalog_sources"] == 18
    assert payload["stats"]["chunks"] == 446
    assert payload["stats"]["entities"] == 1456
    assert payload["chunk_rule"]["target_size"] == 650
    assert any("安全检查标准" in source["title"] for source in payload["sources"])


def test_stream_keeps_original_session_memory_contract(monkeypatch):
    fake_db = MagicMock()
    fake_db.create_session.return_value = "s1"
    fake_db.build_chat_history.return_value = [
        {"role": "user", "content": "上一个问题"},
    ]

    fake_pipeline = MagicMock()
    fake_pipeline.generator.client = MagicMock()

    def stream(*args, **kwargs):
        yield {"type": "status", "message": "正在检索"}
        yield {"type": "token", "content": "**答案**"}
        yield {"type": "done", "references": []}

    fake_pipeline.query_stream.side_effect = stream
    monkeypatch.setattr(api_module, "get_db", lambda: fake_db)
    monkeypatch.setattr(api_module, "get_pipeline", lambda: fake_pipeline)

    response = TestClient(app).post(
        "/api/chat/stream",
        json={"message": "安全帽佩戴的法规依据是什么？"},
    )

    assert response.status_code == 200
    assert '"type": "session"' in response.text
    assert '"type": "status"' in response.text
    assert '"type": "token"' in response.text
    assert '"type": "done"' in response.text
    fake_db.build_chat_history.assert_called_once()
    assert fake_pipeline.query_stream.call_args.kwargs["history"] == (
        fake_db.build_chat_history.return_value
    )

