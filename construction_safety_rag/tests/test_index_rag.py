from app.index import HybridIndex
from app.rag import SafetyRAG


def test_hybrid_search_returns_relevant_chunk():
    chunks = [
        {"chunk_id": "helmet", "title": "安全法规", "issuer": "住建部门", "document_no": "A", "status": "现行", "source_url": "u", "section": "1", "text": "进入施工现场必须佩戴安全帽。", "tags": ["安全帽"]},
        {"chunk_id": "unrelated", "title": "其他资料", "issuer": "部门", "document_no": "B", "status": "现行", "source_url": "u", "section": "1", "text": "项目应当做好资料归档。", "tags": []},
    ]
    result = HybridIndex(chunks).search("施工现场安全帽", top_k=1)
    assert result[0]["chunk_id"] == "helmet"


def test_local_answer_has_citation():
    chunks = [{"chunk_id": "c1", "title": "安全法规", "issuer": "部门", "document_no": "A", "status": "现行", "source_url": "u", "section": "1", "text": "安全帽必须佩戴。", "tags": [], "score": 0.8}]
    rag = SafetyRAG.__new__(SafetyRAG)
    answer = rag._local_answer("安全帽", chunks)
    assert "安全法规" in answer


def test_built_kb_covers_safety_helmet_requirement():
    index = HybridIndex.load()
    results = index.search("安全帽佩戴的法规依据是什么？", top_k=3)
    assert any("建筑施工安全检查标准" in row["title"] for row in results)
    assert any("施工现场人员未戴安全帽" in row["text"] for row in results)
